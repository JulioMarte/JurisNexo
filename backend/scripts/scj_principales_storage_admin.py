from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

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


def _storage_identity(store: S3ObjectStore) -> dict[str, object]:
    bucket = store.config.bucket
    endpoint = store.config.endpoint_url or ""
    endpoint_host = (urlparse(endpoint).hostname or "").casefold()
    return {
        "bucket_length": len(bucket),
        "bucket_sha256": hashlib.sha256(bucket.encode("utf-8")).hexdigest(),
        "endpoint_host": endpoint_host,
        "endpoint_host_sha256": hashlib.sha256(endpoint_host.encode("utf-8")).hexdigest(),
        "region": store.config.region,
    }


def _count_objects(store: S3ObjectStore, prefix: str) -> dict[str, object]:
    client = cast(Any, store.client)
    token: str | None = None
    count = 0
    total_size = 0
    sample_keys: list[str] = []
    while True:
        kwargs: dict[str, object] = {
            "Bucket": store.config.bucket,
            "Prefix": prefix,
            "MaxKeys": 1000,
        }
        if token:
            kwargs["ContinuationToken"] = token
        response = client.list_objects_v2(**kwargs)
        for item in response.get("Contents", []):
            key = str(item.get("Key") or "")
            size = int(item.get("Size") or 0)
            count += 1
            total_size += size
            if len(sample_keys) < 10:
                sample_keys.append(key)
        if not response.get("IsTruncated"):
            break
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError("S3 object listing truncated without continuation token")
    return {
        "prefix": prefix,
        "count": count,
        "total_size": total_size,
        "sample_keys": sample_keys,
    }


def _list_object_versions(store: S3ObjectStore, prefix: str) -> dict[str, object]:
    client = cast(Any, store.client)
    key_marker: str | None = None
    version_id_marker: str | None = None
    versions: list[dict[str, object]] = []
    delete_markers: list[dict[str, object]] = []
    while True:
        kwargs: dict[str, object] = {
            "Bucket": store.config.bucket,
            "Prefix": prefix,
            "MaxKeys": 1000,
        }
        if key_marker:
            kwargs["KeyMarker"] = key_marker
        if version_id_marker:
            kwargs["VersionIdMarker"] = version_id_marker
        response = client.list_object_versions(**kwargs)
        for item in response.get("Versions", []):
            versions.append(
                {
                    "key": str(item.get("Key") or ""),
                    "version_id": str(item.get("VersionId") or ""),
                    "is_latest": bool(item.get("IsLatest")),
                    "size": int(item.get("Size") or 0),
                }
            )
        for item in response.get("DeleteMarkers", []):
            delete_markers.append(
                {
                    "key": str(item.get("Key") or ""),
                    "version_id": str(item.get("VersionId") or ""),
                    "is_latest": bool(item.get("IsLatest")),
                }
            )
        if not response.get("IsTruncated"):
            break
        key_marker = str(response.get("NextKeyMarker") or "")
        version_id_marker = str(response.get("NextVersionIdMarker") or "")
        if not key_marker:
            raise RuntimeError("S3 version listing truncated without next key marker")
    return {
        "prefix": prefix,
        "version_count": len(versions),
        "delete_marker_count": len(delete_markers),
        "versions": versions,
        "delete_markers": delete_markers,
    }


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
        "storage_identity": _storage_identity(store),
        "manifest_count": len(records),
        "classification_counts": dict(sorted(counts.items())),
        "records": records,
        "principales_objects": _count_objects(
            store, "jurisdictions/do/scj/principales-sentencias/"
        ),
        "manifest_versions": _list_object_versions(store, PREFIX),
    }
    _write_json(OUT / "manifest-audit.json", result)
    return result


def cleanup_canary_manifests(store: S3ObjectStore) -> dict[str, object]:
    before = audit(store)
    current_records = before["records"]
    unsafe_current = [
        record
        for record in current_records
        if record.get("classification") not in {"canary", "non-canary"}
    ]
    if unsafe_current:
        raise RuntimeError(
            "refusing Principales cleanup because unreadable/unexpected current manifests exist"
        )

    client = cast(Any, store.client)
    version_state = cast(dict[str, object], before["manifest_versions"])
    version_items = [
        *cast(list[dict[str, object]], version_state["versions"]),
        *cast(list[dict[str, object]], version_state["delete_markers"]),
    ]
    canary_version_items = [
        item for item in version_items if "scj-principales-canary.json" in str(item["key"])
    ]
    non_canary_version_items = [
        item for item in version_items if "scj-principales-canary.json" not in str(item["key"])
    ]

    purged: list[dict[str, str]] = []
    for item in canary_version_items:
        key = str(item["key"])
        version_id = str(item["version_id"])
        if not key or not version_id:
            raise RuntimeError(f"refusing malformed version purge record: {item}")
        client.delete_object(
            Bucket=store.config.bucket,
            Key=key,
            VersionId=version_id,
        )
        purged.append({"key": key, "version_id": version_id})

    after = audit(store)
    remaining_versions = cast(dict[str, object], after["manifest_versions"])
    remaining_canary = [
        item
        for item in [
            *cast(list[dict[str, object]], remaining_versions["versions"]),
            *cast(list[dict[str, object]], remaining_versions["delete_markers"]),
        ]
        if "scj-principales-canary.json" in str(item["key"])
    ]
    if remaining_canary:
        raise RuntimeError(
            f"canary manifest versions remain after permanent purge: {remaining_canary}"
        )

    result = {
        "purged_version_count": len(purged),
        "purged_versions": purged,
        "preserved_non_canary_version_count": len(non_canary_version_items),
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
