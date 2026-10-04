"""Count pages of every SCJ decision document in the object store, sharded.

The `decisions/` collection is content-addressed as `<2hex>/<sha256>.<ext>`.
`plan` lists the collection and bins objects by their 2-hex directory so a
GitHub Actions matrix can count pages in disjoint shards; `count` processes one
shard; `aggregate` merges shards fail-closed and reports totals.

This is a storage-inventory tool. It does not modify source objects and does not
treat a page count as legal-evidence interpretation.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium

from jurisnexo.acquisition.object_store import StoredObject
from jurisnexo.acquisition.s3_object_store import S3ObjectStore, build_s3_object_store

HEX_PREFIXES: tuple[str, ...] = tuple(f"{index:02x}" for index in range(256))
DEFAULT_PREFIX = "jurisdictions/do/scj/decisions/"


def shard_hex_prefixes(shard_count: int) -> list[list[str]]:
    if shard_count < 1 or shard_count > len(HEX_PREFIXES):
        raise ValueError("shard_count must be between 1 and 256")
    buckets: list[list[str]] = [[] for _ in range(shard_count)]
    for index, hex_prefix in enumerate(HEX_PREFIXES):
        buckets[index % shard_count].append(hex_prefix)
    return buckets


def count_pages(pdf_bytes: bytes) -> int:
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return len(document)
    finally:
        document.close()


def is_pdf(key: str) -> bool:
    return key.lower().endswith(".pdf")


def record_for_object(store: S3ObjectStore, obj: StoredObject) -> dict[str, Any]:
    key = obj.key
    extension = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    if not is_pdf(key):
        return {
            "key": key,
            "size": obj.size,
            "format": extension or "unknown",
            "pages": None,
            "error": None,
        }
    try:
        pages = count_pages(store.get_bytes(key))
    except Exception as exc:  # noqa: BLE001 - per-object failures are recorded, not fatal
        return {
            "key": key,
            "size": obj.size,
            "format": "pdf",
            "pages": None,
            "error": f"{type(exc).__name__}: {exc}"[:300],
        }
    return {"key": key, "size": obj.size, "format": "pdf", "pages": pages, "error": None}


def iter_shard_records(
    store: S3ObjectStore,
    *,
    prefix: str,
    hex_prefixes: Sequence[str],
) -> Iterator[dict[str, Any]]:
    for hex_prefix in hex_prefixes:
        for obj in store.list_objects(f"{prefix}{hex_prefix}/"):
            yield record_for_object(store, obj)


def load_records(input_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(input_root.rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(fraction * (len(ordered) - 1)))
    return ordered[index]


def summarize_records(
    records: Sequence[dict[str, Any]],
    *,
    expected_total: int,
    expected_pdf: int,
    expected_non_pdf: int,
) -> dict[str, Any]:
    keys = [str(record["key"]) for record in records]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise RuntimeError(f"duplicate keys across shards: {duplicates[:5]}")
    if len(records) != expected_total:
        raise RuntimeError(f"processed {len(records)} objects, expected {expected_total}")

    pdf_records = [record for record in records if record["format"] == "pdf"]
    non_pdf_records = [record for record in records if record["format"] != "pdf"]
    if len(pdf_records) != expected_pdf or len(non_pdf_records) != expected_non_pdf:
        raise RuntimeError(
            f"format counts drifted: pdf={len(pdf_records)}/{expected_pdf} "
            f"non_pdf={len(non_pdf_records)}/{expected_non_pdf}"
        )

    failed = [record for record in pdf_records if record["pages"] is None]
    pages = [int(record["pages"]) for record in pdf_records if record["pages"] is not None]
    by_format: dict[str, int] = {}
    for record in non_pdf_records:
        by_format[str(record["format"])] = by_format.get(str(record["format"]), 0) + 1

    return {
        "object_count": len(records),
        "pdf_count": len(pdf_records),
        "non_pdf_count": len(non_pdf_records),
        "non_pdf_by_format": by_format,
        "pdf_failed_count": len(failed),
        "failed_keys": sorted(str(record["key"]) for record in failed)[:100],
        "total_pages": sum(pages),
        "pages_min": min(pages) if pages else None,
        "pages_median": statistics.median(pages) if pages else None,
        "pages_p95": _percentile(pages, 0.95),
        "pages_max": max(pages) if pages else None,
        "pages_mean": (sum(pages) / len(pages)) if pages else None,
        "total_bytes": sum(int(record["size"]) for record in records),
    }


def _list_all(store: S3ObjectStore, prefix: str) -> list[StoredObject]:
    return store.list_objects(prefix)


def plan(store: S3ObjectStore, *, prefix: str, shard_count: int, output: Path) -> dict[str, Any]:
    objects = _list_all(store, prefix)
    buckets = shard_hex_prefixes(shard_count)
    hex_to_shard = {
        hex_prefix: index for index, bucket in enumerate(buckets) for hex_prefix in bucket
    }
    per_shard: list[dict[str, Any]] = [
        {"hex_prefixes": bucket, "expected_total": 0, "expected_pdf": 0, "expected_non_pdf": 0}
        for bucket in buckets
    ]
    for obj in objects:
        relative = obj.key[len(prefix) :]
        hex_prefix = relative.split("/", 1)[0] if "/" in relative else ""
        shard = hex_to_shard.get(hex_prefix)
        if shard is None:
            continue
        per_shard[shard]["expected_total"] += 1
        if is_pdf(obj.key):
            per_shard[shard]["expected_pdf"] += 1
        else:
            per_shard[shard]["expected_non_pdf"] += 1

    matrix = {"include": []}
    for index, entry in enumerate(per_shard):
        matrix["include"].append(
            {
                "shard": index,
                "hex_prefixes": ",".join(entry["hex_prefixes"]),
                "expected_total": entry["expected_total"],
                "expected_pdf": entry["expected_pdf"],
                "expected_non_pdf": entry["expected_non_pdf"],
            }
        )
    result = {
        "prefix": prefix,
        "shard_count": shard_count,
        "expected_total": len(objects),
        "expected_pdf": sum(entry["expected_pdf"] for entry in per_shard),
        "expected_non_pdf": sum(entry["expected_non_pdf"] for entry in per_shard),
        "matrix": matrix,
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def count(
    store: S3ObjectStore,
    *,
    prefix: str,
    hex_prefixes: Sequence[str],
    expected_total: int,
    expected_pdf: int,
    expected_non_pdf: int,
    output: Path,
) -> dict[str, Any]:
    records = list(iter_shard_records(store, prefix=prefix, hex_prefixes=hex_prefixes))
    if len(records) != expected_total:
        raise RuntimeError(
            f"shard listed {len(records)} objects, expected {expected_total}"
        )
    pdf_count = sum(1 for record in records if record["format"] == "pdf")
    if pdf_count != expected_pdf:
        raise RuntimeError(f"shard pdf count {pdf_count}, expected {expected_pdf}")
    output.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    return {
        "object_count": len(records),
        "pdf_count": pdf_count,
        "non_pdf_count": len(records) - pdf_count,
        "total_pages": sum(
            int(record["pages"])
            for record in records
            if record["pages"] is not None
        ),
        "failed": sum(
            1
            for record in records
            if record["format"] == "pdf" and record["pages"] is None
        ),
    }


def aggregate(
    *,
    input_root: Path,
    expected_total: int,
    expected_pdf: int,
    expected_non_pdf: int,
    output: Path,
) -> dict[str, Any]:
    records = load_records(input_root)
    summary = summarize_records(
        records,
        expected_total=expected_total,
        expected_pdf=expected_pdf,
        expected_non_pdf=expected_non_pdf,
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output / "pages.jsonl").write_text(
        "".join(
            json.dumps(
                {"key": r["key"], "size": r["size"], "format": r["format"], "pages": r["pages"]},
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for r in records
        ),
        encoding="utf-8",
    )
    return summary


def _parse_hex_prefixes(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    plan_parser.add_argument("--shards", type=int, default=20)
    plan_parser.add_argument("--output", type=Path, required=True)

    count_parser = sub.add_parser("count")
    count_parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    count_parser.add_argument("--hex-prefixes", required=True)
    count_parser.add_argument("--expected-total", type=int, required=True)
    count_parser.add_argument("--expected-pdf", type=int, required=True)
    count_parser.add_argument("--expected-non-pdf", type=int, required=True)
    count_parser.add_argument("--output", type=Path, required=True)

    agg_parser = sub.add_parser("aggregate")
    agg_parser.add_argument("--input-root", type=Path, required=True)
    agg_parser.add_argument("--expected-total", type=int, required=True)
    agg_parser.add_argument("--expected-pdf", type=int, required=True)
    agg_parser.add_argument("--expected-non-pdf", type=int, required=True)
    agg_parser.add_argument("--output", type=Path, required=True)
    agg_parser.add_argument("--publish-prefix", default="")

    args = parser.parse_args()
    store = build_s3_object_store()
    if args.command == "plan":
        result = plan(store, prefix=args.prefix, shard_count=args.shards, output=args.output)
        print(json.dumps(result["matrix"]))
    elif args.command == "count":
        result = count(
            store,
            prefix=args.prefix,
            hex_prefixes=_parse_hex_prefixes(args.hex_prefixes),
            expected_total=args.expected_total,
            expected_pdf=args.expected_pdf,
            expected_non_pdf=args.expected_non_pdf,
            output=args.output,
        )
        print(json.dumps(result, sort_keys=True))
    else:
        result = aggregate(
            input_root=args.input_root,
            expected_total=args.expected_total,
            expected_pdf=args.expected_pdf,
            expected_non_pdf=args.expected_non_pdf,
            output=args.output,
        )
        if args.publish_prefix:
            store.put(
                key=f"{args.publish_prefix}/summary.json",
                content=(args.output / "summary.json").read_bytes(),
                content_type="application/json",
                metadata={"run": os.environ.get("GITHUB_RUN_ID", "")},
            )
            store.put(
                key=f"{args.publish_prefix}/pages.jsonl",
                content=(args.output / "pages.jsonl").read_bytes(),
                content_type="application/x-ndjson",
                metadata={"run": os.environ.get("GITHUB_RUN_ID", "")},
            )
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
