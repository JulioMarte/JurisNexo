from __future__ import annotations

from dataclasses import dataclass

import pytest

from jurisnexo.acquisition.s3_object_store import (
    S3ObjectStore,
    S3ObjectStoreConfig,
)
from jurisnexo.entrypoints.worker.normalization import build_parser, read_manifest


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


def test_worker_cli_requires_durable_run_identity_arguments() -> None:
    parsed = build_parser().parse_args(
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
