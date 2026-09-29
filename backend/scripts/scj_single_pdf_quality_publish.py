"""Publish targeted single-PDF OCR quality evidence durably to S3."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store

BASE_PREFIX = "benchmarks/scj-principales/single-pdf-quality/v1"
ALLOWED_STAGES = frozenset({"deterministic", "jev", "deepseek"})


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_hex(value: str, *, length: int, label: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != length or any(ch not in "0123456789abcdef" for ch in normalized):
        raise ValueError(f"{label} must be {length} lowercase hex characters")
    return normalized


def _head_metadata(store: Any, key: str) -> dict[str, str] | None:
    try:
        response = store.client.head_object(Bucket=store.config.bucket, Key=key)
    except Exception as exc:
        if store.is_not_found(exc):
            return None
        raise
    metadata = response.get("Metadata") if isinstance(response, dict) else None
    if not isinstance(metadata, dict):
        return {}
    return {str(k).lower(): str(v) for k, v in metadata.items()}


def _put_immutable(
    store: Any,
    *,
    key: str,
    payload: bytes,
    content_type: str,
    metadata: dict[str, str],
) -> None:
    payload_sha = _sha256(payload)
    existing = _head_metadata(store, key)
    if existing is not None:
        if existing.get("payload-sha256") != payload_sha:
            raise RuntimeError(f"immutable targeted evidence differs at {key}")
        return
    store.put(
        key=key,
        content=payload,
        content_type=content_type,
        metadata={**metadata, "payload-sha256": payload_sha},
    )


def publish_stage(
    *,
    source_json: Path,
    input_dir: Path,
    stage: str,
    code_revision: str,
    run_id: str,
    run_attempt: str,
    store: Any | None = None,
) -> dict[str, object]:
    if stage not in ALLOWED_STAGES:
        raise ValueError(f"unsupported stage: {stage}")
    revision = _require_hex(code_revision, length=40, label="code_revision")
    source = json.loads(source_json.read_text(encoding="utf-8"))
    source_sha = _require_hex(
        str(source["source_pdf_sha256"]),
        length=64,
        label="source_pdf_sha256",
    )
    if not input_dir.is_dir():
        raise RuntimeError(f"input directory does not exist: {input_dir}")

    files = sorted(path for path in input_dir.rglob("*") if path.is_file())
    if not files:
        raise RuntimeError("targeted quality stage produced no files")

    safe_run_id = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
    safe_attempt = "".join(ch for ch in run_attempt if ch.isalnum() or ch in "-_")
    if not safe_run_id or not safe_attempt:
        raise ValueError("run identity must contain safe characters")
    prefix = (
        f"{BASE_PREFIX}/{source_sha}/{revision}/"
        f"runs/github-{safe_run_id}-attempt-{safe_attempt}/{stage}"
    )
    resolved_store = store or build_s3_object_store()
    common_metadata = {
        "source-pdf-sha256": source_sha,
        "code-revision": revision,
        "stage": stage,
        "github-run-id": safe_run_id,
        "github-run-attempt": safe_attempt,
    }

    manifest_files: list[dict[str, object]] = []
    for path in files:
        relative = path.relative_to(input_dir).as_posix()
        payload = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        key = f"{prefix}/{relative}"
        _put_immutable(
            resolved_store,
            key=key,
            payload=payload,
            content_type=content_type,
            metadata=common_metadata,
        )
        manifest_files.append(
            {
                "path": relative,
                "key": key,
                "sha256": _sha256(payload),
                "byte_size": len(payload),
            }
        )

    manifest: dict[str, object] = {
        "schema_version": 1,
        "object_key": source.get("object_key"),
        "source_pdf_sha256": source_sha,
        "code_revision": revision,
        "github_run_id": safe_run_id,
        "github_run_attempt": safe_attempt,
        "stage": stage,
        "files": manifest_files,
    }
    manifest_payload = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    manifest_key = f"{prefix}/_MANIFEST.json"
    _put_immutable(
        resolved_store,
        key=manifest_key,
        payload=manifest_payload,
        content_type="application/json",
        metadata=common_metadata,
    )
    return {
        "prefix": prefix,
        "manifest_key": manifest_key,
        "source_pdf_sha256": source_sha,
        "stage": stage,
        "file_count": len(manifest_files),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-json", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=sorted(ALLOWED_STAGES), required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    args = parser.parse_args()
    result = publish_stage(
        source_json=args.source_json,
        input_dir=args.input_dir,
        stage=args.stage,
        code_revision=args.code_revision,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
