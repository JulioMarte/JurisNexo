from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, cast

from jurisnexo.acquisition.s3_object_store import S3ObjectStore, build_s3_object_store

PREFIX = "_manifests/scj/principales-sentencias/"
OUT = Path(os.environ.get("SCJ_PRINCIPALES_ADMIN_OUTPUT", "scj-principales-admin-output"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _list_manifest_keys(store: S3ObjectStore) -> list[str]:
    client = cast(Any, store.client)
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, object] = {
            "Bucket": store.config.bucket,
            "Prefix": PREFIX,
            "MaxKeys": 1000,
        }
        if token:
            kwargs["ContinuationToken"] = token
        response = client.list_objects_v2(**kwargs)
        for item in response.get("Contents", []):
            key = str(item.get("Key") or "")
            if key.endswith(".json"):
                keys.append(key)
        if not response.get("IsTruncated"):
            break
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError("S3 listing was truncated without a continuation token")
    return sorted(keys)


def _read_json(store: S3ObjectStore, key: str) -> dict[str, object]:
    client = cast(Any, store.client)
    response = client.get_object(Bucket=store.config.bucket, Key=key)
    body = response["Body"].read()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise TypeError(f"manifest is not a JSON object: {key}")
    return cast(dict[str, object], payload)


def _classify(key: str, payload: dict[str, object]) -> str:
    ingestion_id = str(payload.get("ingestion_id") or "")
    source = str(payload.get("source") or "")
    scope = str(payload.get("scope") or "")
    if source != "scj" or scope != "principales-sentencias":
        return "unexpected-contract"
    if ingestion_id.endswith("-scj-principales-canary"):
        return "canary"
    if "principales-canary" in key:
        return "canary"
    return "non-canary"


def audit(store: S3ObjectStore) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for key in _list_manifest_keys(store):
        try:
            payload = _read_json(store, key)
            classification = _classify(key, payload)
            records.append(
                {
                    "key": key,
                    "classification": classification,
                    "schema_version": payload.get("schema_version"),
                    "ingestion_id": payload.get("ingestion_id"),
                    "batch_id": payload.get("batch_id"),
                    "status": payload.get("status"),
                    "discovered_count": payload.get("discovered_count"),
                    "uploaded_count": payload.get("uploaded_count"),
                    "already_present_count": payload.get("already_present_count"),
                    "failed_count": payload.get("failed_count"),
                }
            )
        except Exception as exc:
            records.append(
                {
                    "key": key,
                    "classification": "unreadable",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    counts: dict[str, int] = {}
    for record in records:
        classification = str(record["classification"])
        counts[classification] = counts.get(classification, 0) + 1
    result = {
        "prefix": PREFIX,
        "bucket": store.config.bucket,
        "manifest_count": len(records),
        "classification_counts": dict(sorted(counts.items())),
        "records": records,
    }
    _write_json(OUT / "manifest-audit.json", result)
    return result


def cleanup_canary_manifests(store: S3ObjectStore) -> dict[str, object]:
    before = audit(store)
    unsafe = [
        record
        for record in before["records"]
        if record.get("classification") != "canary"
    ]
    if unsafe:
        raise RuntimeError(
            "refusing Principales cleanup because non-canary or unreadable manifests exist"
        )

    client = cast(Any, store.client)
    deleted: list[str] = []
    for record in before["records"]:
        key = str(record["key"])
        client.delete_object(Bucket=store.config.bucket, Key=key)
        deleted.append(key)

    after = audit(store)
    if after["manifest_count"] != 0:
        raise RuntimeError("Principales manifest cleanup did not leave an empty prefix")

    result = {
        "deleted_count": len(deleted),
        "deleted_keys": deleted,
        "before": before,
        "after": after,
    }
    _write_json(OUT / "manifest-cleanup.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit-only", action="store_true")
    mode.add_argument("--cleanup-canaries", action="store_true")
    args = parser.parse_args()

    store = build_s3_object_store()
    result = cleanup_canary_manifests(store) if args.cleanup_canaries else audit(store)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
