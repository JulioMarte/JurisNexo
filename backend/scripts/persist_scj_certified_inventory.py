from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.recovery import classify_infrastructure_error
from jurisnexo.acquisition.s3_object_store import build_s3_object_store

EXPECTED_BUCKET_SHA256 = os.environ["EXPECTED_BUCKET_SHA256"]
CERTIFIED_DIR = Path(os.environ["SCJ_CERTIFIED_ARTIFACT_DIR"])
MAX_ATTEMPTS = int(os.environ.get("SCJ_STORAGE_PREFLIGHT_ATTEMPTS", "5"))


def _retry(label: str, operation: Callable[[], Any]) -> Any:
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            failure = classify_infrastructure_error(exc)
            if failure is None or not failure.retryable or attempt >= MAX_ATTEMPTS:
                raise
            print(
                json.dumps(
                    {
                        "event": "scj.storage_preflight.retry",
                        "operation": label,
                        "attempt": attempt,
                        "max_attempts": MAX_ATTEMPTS,
                        "cause": failure.kind,
                        "detail": failure.detail,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            time.sleep(delay)
            delay = min(delay * 2, 8.0)
    assert last_error is not None
    raise last_error


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    store = build_s3_object_store()
    actual_bucket_sha256 = hashlib.sha256(store.config.bucket.encode()).hexdigest()
    if actual_bucket_sha256 != EXPECTED_BUCKET_SHA256:
        raise RuntimeError(
            "bucket fingerprint mismatch: "
            f"expected={EXPECTED_BUCKET_SHA256} actual={actual_bucket_sha256}"
        )

    summary = json.loads((CERTIFIED_DIR / "summary.json").read_text(encoding="utf-8"))
    inventory_sha = str(summary["acquisition_inventory_sha256"])
    snapshot_prefix = f"_inventories/scj/sentencias-1994-actualidad/{inventory_sha}"
    names = (
        "summary.json",
        "scj-1994-source.inventory.jsonl",
        "scj-1994-acquisition.inventory.jsonl",
        "scj-1994-no-locator.inventory.jsonl",
        "duplicate-document-urls.json",
    )
    persisted: list[dict[str, object]] = []

    for name in names:
        path = CERTIFIED_DIR / name
        payload = path.read_bytes()
        digest = _sha256(payload)
        key = f"{snapshot_prefix}/{name}"

        try:
            head = _retry(
                f"head:{name}",
                lambda key=key: store.client.head_object(
                    Bucket=store.config.bucket,
                    Key=key,
                ),
            )
        except Exception as exc:
            if not store.is_not_found(exc):
                raise
            _retry(
                f"put:{name}",
                lambda key=key, payload=payload, digest=digest, name=name: store.client.put_object(
                    Bucket=store.config.bucket,
                    Key=key,
                    Body=payload,
                    ContentType=(
                        "application/json"
                        if name.endswith(".json")
                        else "application/x-ndjson"
                    ),
                    Metadata={
                        "sha256": digest,
                        "inventory_sha256": inventory_sha,
                    },
                ),
            )
            persisted.append(
                {"key": key, "status": "uploaded", "bytes": len(payload)}
            )
            continue

        if not isinstance(head, dict):
            raise TypeError(f"unexpected HeadObject response for {key}")
        metadata = head.get("Metadata") or {}
        if int(head.get("ContentLength") or -1) != len(payload):
            raise RuntimeError(f"inventory snapshot size mismatch: {key}")
        stored_sha = str(metadata.get("sha256") or "")
        if stored_sha and stored_sha != digest:
            raise RuntimeError(f"inventory snapshot sha mismatch: {key}")
        persisted.append(
            {"key": key, "status": "already_present", "bytes": len(payload)}
        )

    count = 0
    size = 0
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": store.config.bucket,
            "Prefix": "jurisdictions/do/scj/decisions/",
            "MaxKeys": 1000,
        }
        if token:
            kwargs["ContinuationToken"] = token
        response = _retry(
            "list:decisions",
            lambda kwargs=kwargs: store.client.list_objects_v2(**kwargs),
        )
        if not isinstance(response, dict):
            raise TypeError("unexpected ListObjectsV2 response")
        for item in response.get("Contents", []):
            count += 1
            size += int(item.get("Size") or 0)
        if not response.get("IsTruncated"):
            break
        token = str(response.get("NextContinuationToken") or "")
        if not token:
            raise RuntimeError("truncated S3 listing lacks continuation token")

    print(
        json.dumps(
            {
                "bucket_sha256": actual_bucket_sha256,
                "inventory_sha256": inventory_sha,
                "snapshot_prefix": snapshot_prefix,
                "snapshot_objects": persisted,
                "existing_decision_objects": count,
                "existing_decision_bytes": size,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
