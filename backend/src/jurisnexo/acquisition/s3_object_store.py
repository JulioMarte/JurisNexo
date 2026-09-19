from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlparse

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_EMPTY_MAPPING: Mapping[str, object] = {}


class S3Client(Protocol):
    def head_object(self, *, Bucket: str, Key: str) -> object: ...

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        Metadata: dict[str, str],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class S3ObjectStoreConfig:
    bucket: str
    region: str
    endpoint_url: str | None = None
    force_path_style: bool = True
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        if not self.bucket.strip():
            raise ValueError("bucket must not be empty")
        if not self.region.strip():
            raise ValueError("region must not be empty")
        if self.endpoint_url is not None:
            endpoint = self.endpoint_url.strip()
            parsed = urlparse(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("endpoint_url must be an absolute HTTP(S) URL")
            if parsed.scheme == "http" and not self.allow_insecure_http:
                raise ValueError(
                    "endpoint_url must use HTTPS unless insecure HTTP is explicitly enabled"
                )

    def locator_for(self, key: str) -> str:
        if not key.strip():
            raise ValueError("object key must not be empty")
        return f"s3://{self.bucket}/{key}"


class S3RuntimeSettings(BaseSettings):
    """Provider-neutral S3 runtime configuration loaded from JURISNEXO_S3_* variables."""

    model_config = SettingsConfigDict(
        env_prefix="JURISNEXO_S3_",
        case_sensitive=False,
        extra="ignore",
        str_strip_whitespace=True,
    )

    bucket: str
    region: str
    endpoint_url: str | None = None
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None
    session_token: SecretStr | None = None
    force_path_style: bool = True
    allow_insecure_http: bool = False
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 60.0
    max_attempts: int = 4
    max_pool_connections: int = 32

    @model_validator(mode="after")
    def validate_runtime_contract(self) -> S3RuntimeSettings:
        S3ObjectStoreConfig(
            bucket=self.bucket,
            region=self.region,
            endpoint_url=self.endpoint_url,
            force_path_style=self.force_path_style,
            allow_insecure_http=self.allow_insecure_http,
        )
        has_access_key = self.access_key_id is not None
        has_secret_key = self.secret_access_key is not None
        if has_access_key != has_secret_key:
            raise ValueError(
                "access_key_id and secret_access_key must be supplied together or both omitted"
            )
        if self.session_token is not None and not has_access_key:
            raise ValueError("session_token requires explicit access_key_id and secret_access_key")
        if self.connect_timeout_seconds <= 0 or self.read_timeout_seconds <= 0:
            raise ValueError("S3 timeouts must be greater than zero")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.max_pool_connections < 1:
            raise ValueError("max_pool_connections must be at least 1")
        return self

    def store_config(self) -> S3ObjectStoreConfig:
        return S3ObjectStoreConfig(
            bucket=self.bucket,
            region=self.region,
            endpoint_url=self.endpoint_url,
            force_path_style=self.force_path_style,
            allow_insecure_http=self.allow_insecure_http,
        )


def boto3_client_kwargs(settings: S3RuntimeSettings) -> dict[str, Any]:
    """Return provider-neutral boto3 client kwargs without defeating its credential chain."""

    kwargs: dict[str, Any] = {"region_name": settings.region}
    if settings.endpoint_url:
        kwargs["endpoint_url"] = settings.endpoint_url
    if settings.access_key_id is not None and settings.secret_access_key is not None:
        kwargs["aws_access_key_id"] = settings.access_key_id.get_secret_value()
        kwargs["aws_secret_access_key"] = settings.secret_access_key.get_secret_value()
        if settings.session_token is not None:
            kwargs["aws_session_token"] = settings.session_token.get_secret_value()
    return kwargs


def create_boto3_s3_client(settings: S3RuntimeSettings) -> Any:
    """Create one S3 client using boto3 and the normal AWS credential-provider chain."""

    try:
        boto3 = importlib.import_module("boto3")
        botocore_config = importlib.import_module("botocore.config")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "boto3 is required by S3-enabled jobs; install the storage runtime dependency"
        ) from exc

    sdk_config = botocore_config.Config(
        signature_version="s3v4",
        connect_timeout=settings.connect_timeout_seconds,
        read_timeout=settings.read_timeout_seconds,
        max_pool_connections=settings.max_pool_connections,
        retries={"mode": "standard", "max_attempts": settings.max_attempts},
        s3={"addressing_style": "path" if settings.force_path_style else "virtual"},
    )
    return boto3.client("s3", config=sdk_config, **boto3_client_kwargs(settings))


def _string_object_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def is_s3_not_found(exc: Exception) -> bool:
    response: object = getattr(exc, "response", None)
    response_map = _string_object_mapping(response)
    if response_map is None:
        return False

    error = _string_object_mapping(response_map.get("Error")) or _EMPTY_MAPPING
    metadata = _string_object_mapping(response_map.get("ResponseMetadata")) or _EMPTY_MAPPING

    code = str(error.get("Code", ""))
    raw_status = metadata.get("HTTPStatusCode", 0)
    if isinstance(raw_status, int):
        status = raw_status
    elif isinstance(raw_status, str) and raw_status.isdigit():
        status = int(raw_status)
    else:
        status = 0
    return status == 404 or code in {"404", "NoSuchKey", "NotFound", "NoSuchObject"}


@dataclass(slots=True)
class S3ObjectStore:
    """ObjectStore implementation usable with AWS S3 and compatible providers."""

    client: S3Client
    config: S3ObjectStoreConfig
    is_not_found: Callable[[Exception], bool] = is_s3_not_found

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.config.bucket, Key=key)
        except Exception as exc:
            if self.is_not_found(exc):
                return False
            raise
        return True

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        self.client.put_object(
            Bucket=self.config.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
            Metadata=metadata,
        )


    def put_file(
        self,
        *,
        key: str,
        path: Path,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        with path.open("rb") as stream:
            client = cast(Any, self.client)
            client.put_object(
                Bucket=self.config.bucket,
                Key=key,
                Body=stream,
                ContentType=content_type,
                Metadata=metadata,
            )


def build_s3_object_store(
    settings: S3RuntimeSettings | None = None,
    *,
    client_factory: Callable[[S3RuntimeSettings], Any] = create_boto3_s3_client,
) -> S3ObjectStore:
    resolved = settings or S3RuntimeSettings()  # type: ignore[call-arg]
    client = cast(S3Client, client_factory(resolved))
    return S3ObjectStore(client=client, config=resolved.store_config())
