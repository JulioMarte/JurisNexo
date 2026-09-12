from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


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
    endpoint_url: str
    region: str
    force_path_style: bool = True

    def __post_init__(self) -> None:
        if not self.bucket.strip():
            raise ValueError("bucket must not be empty")
        if not self.endpoint_url.startswith("https://"):
            raise ValueError("endpoint_url must use HTTPS")
        if not self.region.strip():
            raise ValueError("region must not be empty")


@dataclass(slots=True)
class S3ObjectStore:
    """ObjectStore implementation usable with Supabase, B2, R2, AWS S3, or MinIO clients."""

    client: S3Client
    config: S3ObjectStoreConfig
    is_not_found: Callable[[Exception], bool]

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
