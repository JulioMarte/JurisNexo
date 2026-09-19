from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from jurisnexo.acquisition.s3_object_store import S3ObjectStore, build_s3_object_store

MANIFEST_PREFIX = "_manifests/scj/sentencias-1994-actualidad/"
OBJECT_PREFIX = "jurisdictions/do/scj/decisions/"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _list_keys(store: S3ObjectStore, prefix: str) -> list[str]:
    client = cast(Any, store.client)
    keys: list[str] = []
    token: str | None = None
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
            if key:
                keys.append(key)
        if not response.get("IsTruncated"):
            return sorted(keys)
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError("S3 listing truncated without continuation token")


def _read_json(store: S3ObjectStore, key: str) -> dict[str, Any]:
    client = cast(Any, store.client)
    response = client.get_object(Bucket=store.config.bucket, Key=key)
    payload = json.loads(response["Body"].read())
    if not isinstance(payload, dict):
        raise TypeError(f"manifest {key} is not a JSON object")
    return cast(dict[str, Any], payload)


def _inventory_ids(path: Path) -> set[str]:
    values: set[str] = set()
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise TypeError("certified SCJ inventory contains non-object row")
            source_identifier = str(item.get("source_identifier") or "").strip()
            if not source_identifier:
                raise ValueError("certified SCJ inventory row lacks source_identifier")
            if source_identifier in values:
                raise RuntimeError(
                    f"certified acquisition inventory repeats source_identifier={source_identifier}"
                )
            values.add(source_identifier)
    return values


def main() -> None:
    batch_id = os.environ["ACQUISITION_BATCH_ID"].strip()
    inventory_path = Path(os.environ["SCJ_1994_INVENTORY_FILE"])
    output_dir = Path(os.environ["SCJ_VERIFY_OUTPUT"])
    expected_bucket_sha256 = os.environ.get("EXPECTED_BUCKET_SHA256", "").strip()
    if not batch_id:
        raise ValueError("ACQUISITION_BATCH_ID must not be empty")

    store = build_s3_object_store()
    bucket_sha256 = hashlib.sha256(store.config.bucket.encode("utf-8")).hexdigest()
    endpoint_host = (urlparse(store.config.endpoint_url or "").hostname or "").casefold()
    if expected_bucket_sha256 and bucket_sha256 != expected_bucket_sha256:
        raise RuntimeError(
            f"storage bucket fingerprint mismatch: actual={bucket_sha256}"
        )

    inventory_ids = _inventory_ids(inventory_path)
    manifest_keys = _list_keys(store, MANIFEST_PREFIX)
    batch_manifests: list[tuple[str, dict[str, Any]]] = []
    for key in manifest_keys:
        if not key.endswith(".json"):
            continue
        payload = _read_json(store, key)
        if str(payload.get("batch_id") or "") == batch_id:
            batch_manifests.append((key, payload))
    if not batch_manifests:
        raise RuntimeError(f"no manifests found for batch_id={batch_id}")

    partition_counts = {int(payload["partition_count"]) for _, payload in batch_manifests}
    if len(partition_counts) != 1:
        raise RuntimeError(f"batch manifests disagree on partition_count: {partition_counts}")
    partition_count = partition_counts.pop()
    partition_indexes = {int(payload["partition_index"]) for _, payload in batch_manifests}
    if partition_indexes != set(range(partition_count)):
        raise RuntimeError(
            f"incomplete manifest partitions: expected={partition_count} "
            f"observed={sorted(partition_indexes)}"
        )

    observed_ids: set[str] = set()
    object_keys: set[str] = set()
    sha256s: set[str] = set()
    uploaded_count = 0
    already_present_count = 0
    failed_count = 0
    total_items = 0
    manifest_statuses: dict[str, str] = {}

    for key, payload in sorted(batch_manifests):
        status = str(payload.get("status") or "")
        manifest_statuses[key] = status
        if status != "succeeded":
            raise RuntimeError(f"non-success manifest in batch: {key} status={status}")
        failed_count += int(payload.get("failed_count") or 0)
        uploaded_count += int(payload.get("uploaded_count") or 0)
        already_present_count += int(payload.get("already_present_count") or 0)
        items = payload.get("items")
        if not isinstance(items, list):
            raise TypeError(f"manifest {key} lacks items array")
        for item in items:
            if not isinstance(item, dict):
                raise TypeError(f"manifest {key} contains non-object item")
            total_items += 1
            item_status = str(item.get("status") or "")
            if item_status not in {"uploaded", "already_present"}:
                raise RuntimeError(
                    f"manifest {key} contains unresolved item status={item_status}"
                )
            source_identifier = str(item.get("source_identifier") or "").strip()
            object_key = str(item.get("object_key") or "").strip()
            digest = str(item.get("sha256") or "").strip()
            if not source_identifier or not object_key or len(digest) != 64:
                raise RuntimeError(f"manifest {key} contains incomplete stored item")
            if source_identifier in observed_ids:
                raise RuntimeError(
                    f"source_identifier appears in multiple manifest items: {source_identifier}"
                )
            observed_ids.add(source_identifier)
            object_keys.add(object_key)
            sha256s.add(digest)

    if failed_count:
        raise RuntimeError(f"batch reports failed_count={failed_count}")
    missing_ids = sorted(inventory_ids - observed_ids)
    unexpected_ids = sorted(observed_ids - inventory_ids)
    if missing_ids or unexpected_ids:
        raise RuntimeError(
            "manifest/source inventory mismatch: "
            f"missing={len(missing_ids)} unexpected={len(unexpected_ids)} "
            f"missing_sample={missing_ids[:10]} unexpected_sample={unexpected_ids[:10]}"
        )
    if total_items != len(inventory_ids):
        raise RuntimeError(
            f"manifest item count mismatch: items={total_items} inventory={len(inventory_ids)}"
        )

    stored_keys = set(_list_keys(store, OBJECT_PREFIX))
    missing_objects = sorted(object_keys - stored_keys)
    if missing_objects:
        raise RuntimeError(
            f"manifests reference {len(missing_objects)} missing S3 objects: "
            f"{missing_objects[:20]}"
        )

    summary = {
        "status": "COMPLETE",
        "batch_id": batch_id,
        "storage_identity": {
            "bucket_sha256": bucket_sha256,
            "endpoint_host": endpoint_host,
        },
        "partition_count": partition_count,
        "manifest_count": len(batch_manifests),
        "inventory_source_identifier_count": len(inventory_ids),
        "manifest_item_count": total_items,
        "uploaded_count": uploaded_count,
        "already_present_count": already_present_count,
        "failed_count": failed_count,
        "unique_object_key_count": len(object_keys),
        "unique_sha256_count": len(sha256s),
        "objects_visible_under_decisions_prefix": len(stored_keys),
        "missing_object_count": len(missing_objects),
        "manifest_statuses": manifest_statuses,
    }
    _write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
