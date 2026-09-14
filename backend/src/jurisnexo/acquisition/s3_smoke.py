from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import uuid4

from jurisnexo.acquisition.s3_object_store import (
    S3RuntimeSettings,
    create_boto3_s3_client,
)

SMOKE_PREFIX = "_system/smoke-tests"
_SMOKE_PAYLOAD = b"jurisnexo-s3-smoke-v1\n"
_SMOKE_METADATA = {"jurisnexo-purpose": "storage-smoke"}


class S3SmokeClient(Protocol):
    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        Metadata: dict[str, str],
    ) -> object: ...

    def head_object(self, *, Bucket: str, Key: str) -> object: ...

    def list_objects_v2(
        self,
        *,
        Bucket: str,
        Prefix: str,
        MaxKeys: int,
    ) -> object: ...

    def delete_object(self, *, Bucket: str, Key: str) -> object: ...


@dataclass(frozen=True, slots=True)
class S3SmokeResult:
    key: str
    cleaned_up: bool


def _object_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def smoke_object_key(run_id: str | None = None) -> str:
    raw_token = (run_id or uuid4().hex).strip()
    sanitized = "".join(
        character if character.isalnum() or character in {"-", "_", "."} else "-"
        for character in raw_token
    ).strip(".-")
    token = sanitized or uuid4().hex
    return f"{SMOKE_PREFIX}/{token}.txt"


def _listed_keys(response: object) -> set[str]:
    response_map = _object_mapping(response)
    if response_map is None:
        raise RuntimeError("S3 ListObjectsV2 returned an unexpected response shape")

    raw_contents = response_map.get("Contents", [])
    if not isinstance(raw_contents, list):
        raise RuntimeError("S3 ListObjectsV2 returned unexpected Contents data")

    keys: set[str] = set()
    for raw_item in cast(list[object], raw_contents):
        item = _object_mapping(raw_item)
        if item is None:
            continue
        key = item.get("Key")
        if isinstance(key, str):
            keys.add(key)
    return keys


def run_s3_storage_smoke(
    settings: S3RuntimeSettings | None = None,
    *,
    run_id: str | None = None,
    client_factory: Callable[[S3RuntimeSettings], Any] = create_boto3_s3_client,
) -> S3SmokeResult:
    resolved = settings or S3RuntimeSettings()  # type: ignore[call-arg]
    client = cast(S3SmokeClient, client_factory(resolved))
    key = smoke_object_key(run_id)
    bucket = resolved.bucket
    cleaned_up = False

    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=_SMOKE_PAYLOAD,
            ContentType="text/plain",
            Metadata=_SMOKE_METADATA,
        )

        head = _object_mapping(client.head_object(Bucket=bucket, Key=key))
        if head is None:
            raise RuntimeError("S3 HeadObject returned an unexpected response shape")
        if head.get("ContentLength") != len(_SMOKE_PAYLOAD):
            raise RuntimeError("S3 HeadObject did not confirm the smoke object byte length")

        listed_keys = _listed_keys(
            client.list_objects_v2(Bucket=bucket, Prefix=key, MaxKeys=10)
        )
        if key not in listed_keys:
            raise RuntimeError("S3 ListObjectsV2 did not return the smoke object")
    finally:
        try:
            client.delete_object(Bucket=bucket, Key=key)
        except Exception:
            cleaned_up = False
        else:
            cleaned_up = True

    return S3SmokeResult(key=key, cleaned_up=cleaned_up)


def main() -> int:
    result = run_s3_storage_smoke(run_id=os.getenv("JURISNEXO_S3_SMOKE_RUN_ID"))
    print("S3 storage smoke passed for the configured bucket.")
    print(f"Smoke namespace: {SMOKE_PREFIX}/")
    if not result.cleaned_up:
        print(
            "WARNING: smoke object cleanup was not permitted or failed; "
            "DeleteObject is not required by the corpus write/read contract.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
