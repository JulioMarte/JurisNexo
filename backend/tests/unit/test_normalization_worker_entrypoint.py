from __future__ import annotations

import argparse
from dataclasses import dataclass

import pytest

import jurisnexo.entrypoints.worker.normalization as normalization_worker
from jurisnexo.acquisition.s3_object_store import (
    S3ObjectStore,
    S3ObjectStoreConfig,
)
from jurisnexo.entrypoints.worker.normalization import (
    build_parser,
    read_manifest,
    validate_args,
)


@dataclass
class _Body:
    payload: bytes

    def read(self) -> bytes:
        return self.payload


@dataclass
class _Client:
    payload: bytes
    metadata: dict[str, str]

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        assert Bucket == "fixture"
        assert Key == "manifest.json"
        return {
            "Body": _Body(self.payload),
            "Metadata": self.metadata,
        }


def _store(payload: bytes, metadata: dict[str, str]) -> S3ObjectStore:
    return S3ObjectStore(
        client=_Client(payload, metadata),  # type: ignore[arg-type]
        config=S3ObjectStoreConfig(bucket="fixture", region="us-east-1"),
    )


def _valid_args() -> argparse.Namespace:
    return build_parser().parse_args(
        [
            "--scope-id",
            "scope-1",
            "--manifest-key",
            "manifest.json",
            "--pipeline-version",
            "normalization-v1",
            "--config-sha256",
            "a" * 64,
        ]
    )


def test_worker_cli_requires_durable_run_identity_arguments() -> None:
    parsed = _valid_args()
    assert parsed.scope_id == "scope-1"
    assert parsed.manifest_key == "manifest.json"
    assert parsed.pipeline_version == "normalization-v1"
    assert parsed.config_sha256 == "a" * 64


def test_worker_manifest_reader_rejects_metadata_hash_mismatch() -> None:
    with pytest.raises(RuntimeError, match="payload hash"):
        read_manifest(
            _store(b"{}", {"payload_sha256": "0" * 64}),
            "manifest.json",
        )


def test_worker_validation_rejects_non_hex_digest() -> None:
    args = _valid_args()
    args.config_sha256 = "z" * 64
    with pytest.raises(ValueError, match="hexadecimal"):
        validate_args(args)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("docling_timeout_seconds", 0.0, "timeout"),
        ("docling_max_source_bytes", 0, "byte limits"),
        ("docling_max_output_bytes", 0, "byte limits"),
        ("circuit_breaker_threshold", 0, "circuit-breaker"),
    ],
)
def test_worker_validation_rejects_non_positive_limits(
    field: str,
    value: float | int,
    message: str,
) -> None:
    args = _valid_args()
    setattr(args, field, value)
    with pytest.raises(ValueError, match=message):
        validate_args(args)


def test_worker_validation_rejects_empty_resume_identity() -> None:
    args = _valid_args()
    args.resume_run_id = "   "
    with pytest.raises(ValueError, match="resume-run-id"):
        validate_args(args)


def test_worker_validation_accepts_explicit_resume_identity() -> None:
    args = _valid_args()
    args.resume_run_id = "run-123"
    validate_args(args)


def _retryable_result(args: argparse.Namespace) -> dict[str, object]:
    del args
    return {
        "run_id": "run-1",
        "final_status": "retryable_pending",
    }


def test_worker_main_returns_distinct_retryable_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        normalization_worker,
        "run",
        _retryable_result,
    )
    exit_code = normalization_worker.main(
        [
            "--scope-id",
            "scope-1",
            "--manifest-key",
            "manifest.json",
            "--pipeline-version",
            "normalization-v1",
            "--config-sha256",
            "a" * 64,
        ]
    )
    assert exit_code == 3
