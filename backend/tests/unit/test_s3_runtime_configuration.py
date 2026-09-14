from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from pydantic import ValidationError

from jurisnexo.acquisition.s3_object_store import (
    S3RuntimeSettings,
    boto3_client_kwargs,
    build_s3_object_store,
    is_s3_not_found,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _objects() -> dict[tuple[str, str], bytes]:
    return {}


@dataclass(slots=True)
class FakeS3Client:
    objects: dict[tuple[str, str], bytes] = field(default_factory=_objects)

    def head_object(self, *, Bucket: str, Key: str) -> object:
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        Metadata: dict[str, str],
    ) -> object:
        self.objects[(Bucket, Key)] = Body
        return {"ETag": "fixture"}


def _settings(**overrides: object) -> S3RuntimeSettings:
    values: dict[str, object] = {
        "bucket": "jurisnexo-official",
        "region": "us-east-1",
        "endpoint_url": "https://storage.example.test",
        "access_key_id": None,
        "secret_access_key": None,
        "session_token": None,
    }
    values.update(overrides)
    return S3RuntimeSettings(**values)  # type: ignore[arg-type]


def test_runtime_settings_leave_credentials_to_boto3_chain_when_not_explicit() -> None:
    kwargs = boto3_client_kwargs(_settings(endpoint_url=None))

    assert kwargs == {"region_name": "us-east-1"}
    assert "aws_access_key_id" not in kwargs
    assert "aws_secret_access_key" not in kwargs


def test_runtime_settings_support_s3_compatible_static_credentials_and_session_token() -> None:
    settings = _settings(
        endpoint_url="https://account.r2.cloudflarestorage.com",
        region="auto",
        access_key_id="access",
        secret_access_key="secret",
        session_token="temporary-token",
    )

    assert boto3_client_kwargs(settings) == {
        "region_name": "auto",
        "endpoint_url": "https://account.r2.cloudflarestorage.com",
        "aws_access_key_id": "access",
        "aws_secret_access_key": "secret",
        "aws_session_token": "temporary-token",
    }


def test_runtime_settings_reject_partial_explicit_credentials() -> None:
    with pytest.raises(ValidationError, match="must be supplied together"):
        _settings(access_key_id="access")


def test_runtime_settings_allow_native_aws_endpoint_resolution() -> None:
    settings = _settings(endpoint_url=None, force_path_style=False)

    assert settings.endpoint_url is None
    assert settings.store_config().endpoint_url is None


def test_runtime_settings_reject_insecure_endpoint_by_default() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        _settings(endpoint_url="http://minio:9000")


def test_runtime_settings_allow_insecure_endpoint_only_with_explicit_opt_in() -> None:
    settings = _settings(
        endpoint_url="http://minio:9000",
        allow_insecure_http=True,
    )

    assert settings.store_config().allow_insecure_http is True


def test_shared_builder_uses_one_configured_store_boundary() -> None:
    client = FakeS3Client()
    captured: list[S3RuntimeSettings] = []

    def factory(settings: S3RuntimeSettings) -> FakeS3Client:
        captured.append(settings)
        return client

    settings = _settings()
    store = build_s3_object_store(settings, client_factory=factory)

    assert captured == [settings]
    assert store.client is client
    assert store.config.bucket == "jurisnexo-official"
    assert store.config.endpoint_url == "https://storage.example.test"


def test_not_found_detection_is_sdk_shape_based_not_provider_class_based() -> None:
    class CompatibleS3Error(Exception):
        response = {
            "Error": {"Code": "NoSuchKey"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        }

    assert is_s3_not_found(CompatibleS3Error()) is True
    assert is_s3_not_found(RuntimeError("network failure")) is False
