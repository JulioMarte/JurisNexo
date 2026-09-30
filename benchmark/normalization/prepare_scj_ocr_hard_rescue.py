from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from jurisnexo.acquisition.s3_object_store import build_s3_object_store

EVIDENCE_PREFIX = "benchmarks/scj-principales/corpus-verification/v1/"
SOURCE_PREFIX = "jurisdictions/do/scj/principales-sentencias/"
EXPECTED_DOCUMENTS = 36
EXPECTED_PAGES = 29811
SEED = 20260930


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _body_bytes(response: dict[str, Any]) -> bytes:
    body = response["Body"].read()
    return body if isinstance(body, bytes) else bytes(body)


def _list_objects(store: Any, prefix: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": store.config.bucket,
            "Prefix": prefix,
            "MaxKeys": 1000,
        }
        if token:
            kwargs["ContinuationToken"] = token
        response = store.client.list_objects_v2(**kwargs)
        rows.extend(response.get("Contents", []))
        if not response.get("IsTruncated"):
            return rows
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError("truncated S3 listing without continuation token")


def _latest_complete_dataset(store: Any) -> tuple[str, dict[str, Any]]:
    candidates: list[tuple[Any, str, dict[str, Any]]] = []
    for item in _list_objects(store, EVIDENCE_PREFIX):
        key = str(item.get("Key") or "")
        if not key.endswith("/_SUCCESS.json"):
            continue
        payload = json.loads(
            _body_bytes(
                store.client.get_object(Bucket=store.config.bucket, Key=key)
            )
        )
        if (
            int(payload.get("document_count") or 0) == EXPECTED_DOCUMENTS
            and int(payload.get("total_pages") or 0) == EXPECTED_PAGES
        ):
            candidates.append((item.get("LastModified"), key, payload))
    if not candidates:
        raise RuntimeError("no complete 36-PDF/29,811-page census dataset found")
    candidates.sort(key=lambda row: (row[0], row[1]))
    _, success_key, payload = candidates[-1]
    return success_key.removesuffix("_SUCCESS.json"), payload


def _archive_records(payload: bytes) -> tuple[dict[str, Any], list[dict[str, Any]], dict[int, str], dict[int, str]]:
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        def read_text(name: str) -> str:
            member = archive.getmember(name)
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"archive member unreadable: {name}")
            return source.read().decode("utf-8")

        document = json.loads(read_text("document.json"))
        pages = [
            json.loads(line)
            for line in read_text("pages.jsonl").splitlines()
            if line.strip()
        ]
        native: dict[int, str] = {}
        historical_ocr: dict[int, str] = {}
        for page in pages:
            idx = int(page["page_index"])
            n = f"observations/native/page-{idx:05d}.txt"
            o = f"observations/ocr/page-{idx:05d}.txt"
            try:
                native[idx] = read_text(n)
            except KeyError:
                native[idx] = ""
            try:
                historical_ocr[idx] = read_text(o)
            except KeyError:
                historical_ocr[idx] = ""
        return document, pages, native, historical_ocr


def _render_selected(pdf_bytes: bytes, indices: set[int]) -> dict[int, bytes]:
    rendered: dict[int, bytes] = {}
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        for idx in sorted(indices):
            page = document[idx]
            try:
                bitmap = page.render(scale=2.0)
                try:
                    out = io.BytesIO()
                    bitmap.to_pil().save(out, format="PNG")
                    rendered[idx] = out.getvalue()
                finally:
                    bitmap.close()
            finally:
                page.close()
    finally:
        document.close()
    return rendered


def _deterministic_order(rows: list[dict[str, Any]], object_key: str) -> list[dict[str, Any]]:
    ordered = list(rows)
    random.Random(f"{SEED}:{object_key}").shuffle(ordered)
    return ordered


def _round_robin(per_document: dict[str, list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    ordered_docs = sorted(per_document)
    queues = {key: _deterministic_order(per_document[key], key) for key in ordered_docs}
    selected: list[dict[str, Any]] = []
    rank = 0
    while len(selected) < limit:
        progressed = False
        for key in ordered_docs:
            rows = queues[key]
            if rank < len(rows):
                selected.append(rows[rank])
                progressed = True
                if len(selected) == limit:
                    return selected
        if not progressed:
            break
        rank += 1
    return selected


def prepare(output: Path, limit: int) -> int:
    if limit < 1:
        raise ValueError("limit must be positive")
    store = build_s3_object_store()
    dataset_prefix, success = _latest_complete_dataset(store)
    archive_items = [
        item for item in _list_objects(store, f"{dataset_prefix}documents/")
        if str(item.get("Key") or "").endswith(".tar.gz")
    ]
    if len(archive_items) != EXPECTED_DOCUMENTS:
        raise RuntimeError(f"expected {EXPECTED_DOCUMENTS} evidence archives, found {len(archive_items)}")

    per_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    observations: dict[tuple[str, int], tuple[str, str]] = {}
    source_shas: dict[str, str] = {}

    for item in sorted(archive_items, key=lambda row: str(row["Key"])):
        archive_key = str(item["Key"])
        archive_bytes = _body_bytes(
            store.client.get_object(Bucket=store.config.bucket, Key=archive_key)
        )
        document, pages, native, historical = _archive_records(archive_bytes)
        object_key = str(document["object_key"])
        source_shas[object_key] = str(document["source_pdf_sha256"])
        for row in pages:
            if row.get("classification") != "misaligned":
                continue
            idx = int(row["page_index"])
            candidate = {
                "object_key": object_key,
                "page_index": idx,
                "census_record": row,
            }
            per_document[object_key].append(candidate)
            observations[(object_key, idx)] = (native.get(idx, ""), historical.get(idx, ""))

    population = sum(len(rows) for rows in per_document.values())
    if population < limit:
        raise RuntimeError(f"only {population} misaligned pages available for {limit} requested")
    selected = _round_robin(per_document, limit)
    if len(selected) != limit:
        raise RuntimeError(f"selection produced {len(selected)} pages, expected {limit}")

    output.mkdir(parents=True, exist_ok=True)
    cases_root = output / "cases"
    selected_by_doc: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for case_index, row in enumerate(selected):
        selected_by_doc[str(row["object_key"])].append((case_index, row))

    manifest_cases: list[dict[str, Any] | None] = [None] * limit
    for object_key, rows in selected_by_doc.items():
        pdf_bytes = _body_bytes(
            store.client.get_object(Bucket=store.config.bucket, Key=object_key)
        )
        actual_sha = _sha256(pdf_bytes)
        if actual_sha != source_shas[object_key]:
            raise RuntimeError(f"source PDF checksum drift: {object_key}")
        indices = {int(row["page_index"]) for _, row in rows}
        rendered = _render_selected(pdf_bytes, indices)
        for case_index, row in rows:
            page_index = int(row["page_index"])
            sample_id = f"hard-{case_index:04d}"
            case_dir = cases_root / sample_id
            case_dir.mkdir(parents=True, exist_ok=True)
            image = rendered[page_index]
            native, historical = observations[(object_key, page_index)]
            (case_dir / "input-page.png").write_bytes(image)
            (case_dir / "observation-native.txt").write_text(native, encoding="utf-8")
            (case_dir / "observation-census-tesseract.txt").write_text(historical, encoding="utf-8")
            source = {
                "sample_id": sample_id,
                "object_key": object_key,
                "page_index": page_index,
                "source_pdf_sha256": actual_sha,
                "image_sha256": _sha256(image),
                "native_text_sha256": _sha256(native.encode("utf-8")),
                "historical_ocr_sha256": _sha256(historical.encode("utf-8")),
                "census_classification": "misaligned",
                "census_record": row["census_record"],
                "reference_reliable": False,
                "reference_authority": "none_hard_rescue",
            }
            (case_dir / "source.json").write_text(
                json.dumps(source, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_cases[case_index] = {
                **source,
                "image_path": f"cases/{sample_id}/input-page.png",
                "native_observation_path": f"cases/{sample_id}/observation-native.txt",
                "historical_ocr_observation_path": f"cases/{sample_id}/observation-census-tesseract.txt",
                "metadata_path": f"cases/{sample_id}/source.json",
            }

    final_cases = [row for row in manifest_cases if row is not None]
    counts = {key: len(rows) for key, rows in selected_by_doc.items()}
    manifest = {
        "schema_version": 1,
        "benchmark_kind": "hard_rescue_ocr_disagreement",
        "selection": {
            "population": "census classification == misaligned",
            "population_pages": population,
            "sample_size": limit,
            "seed": SEED,
            "method": "document-stratified deterministic round-robin with seeded within-document shuffle",
            "uses_candidate_engine_quality_for_selection": False,
        },
        "reference_semantics": {
            "has_gold": False,
            "native_text_is_gold": False,
            "historical_tesseract_is_gold": False,
            "purpose": "Generate independent candidate observations for later blind visual adjudication.",
        },
        "census_dataset_prefix": dataset_prefix,
        "census_success": success,
        "selected_pages_per_document": dict(sorted(counts.items())),
        "cases": final_cases,
    }
    (output / "prepared-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "prepared_cases": len(final_cases),
        "misaligned_population": population,
        "documents_represented": len(counts),
        "dataset_prefix": dataset_prefix,
    }, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    return prepare(args.output, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
