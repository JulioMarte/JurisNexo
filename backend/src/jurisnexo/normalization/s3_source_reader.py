from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from jurisnexo.acquisition.s3_object_store import S3ObjectStore


@dataclass(slots=True)
class S3SourceByteReader:
    """Read immutable source bytes from the configured S3-compatible store."""

    object_store: S3ObjectStore

    def read(self, key: str) -> bytes:
        if not key.strip():
            raise ValueError("object key must not be empty")
        client = cast(Any, self.object_store.client)
        response = client.get_object(
            Bucket=self.object_store.config.bucket,
            Key=key,
        )
        body = response["Body"]
        payload = body.read()
        if not isinstance(payload, bytes):
            payload = bytes(payload)
        return payload
