from __future__ import annotations

"""Build the immutable document inventory consumed by the corpus census matrix."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store

PREFIX = "jurisdictions/do/scj/principales-sentencias/"


def _list_pdf_objects(store: Any) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": store.config.bucket,
            "Prefix": PREFIX,
            "MaxKeys": 1000,
        }
        if token:
            kwargs["ContinuationToken"] = token

        response = store.client.list_objects_v2(**kwargs)
        for item in response.get("Contents", []):
            key = str(item.get("Key") or "")
            if not key.endswith(".pdf"):
                continue
            objects.append(
                {
                    "object_key": key,
                    "size_bytes": int(item.get("Size") or 0),
                    "etag": str(item.get("ETag") or "").strip('"'),
                }
            )

        if not response.get("IsTruncated"):
            break
        token = str(
            response.get("NextContinuationToken") or ""
        )
        if not token:
            raise RuntimeError(
                "S3 listing truncated without continuation token"
            )

    return sorted(
        objects,
        key=lambda item: item["object_key"],
    )


def build_inventory(store: Any) -> dict[str, Any]:
    documents = _list_pdf_objects(store)
    if not documents:
        raise RuntimeError(
            "Principales corpus listing returned no PDFs"
        )

    for index, document in enumerate(documents):
        document["document_index"] = index
        document["document_id"] = hashlib.sha256(
            document["object_key"].encode("utf-8")
        ).hexdigest()[:16]

    canonical = json.dumps(
        documents,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    inventory_sha = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "prefix": PREFIX,
        "document_count": len(documents),
        "inventory_sha256": inventory_sha,
        "documents": documents,
        "matrix": {"include": documents},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )
    args = parser.parse_args()

    inventory = build_inventory(
        build_s3_object_store()
    )
    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.output.write_text(
        json.dumps(
            inventory,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            inventory["matrix"],
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
