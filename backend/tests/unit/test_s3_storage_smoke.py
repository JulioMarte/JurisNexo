from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jurisnexo.acquisition.s3_object_store import S3RuntimeSettings
from jurisnexo.acquisition.s3_smoke import (
    SMOKE_PREFIX,
    run_s3_storage_smoke,
    smoke_object_key,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _objects() -> dict[tuple[str, str], bytes]:
    return {}


def _calls() -> list[str]:
    return []


@dataclass(slots=True)
class FakeSmokeClient:
    objects: dict[tuple[str, str], bytes] = field(default_factory=_objects)
    delete_allowed: bool = True
    calls: list[str] = field(default_factory=_calls)

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        Metadata: dict[str, str],
    ) -> object:
        self.calls.append("put")
        assert ContentType == "text/plain"
        assert Metadata == {"jurisnexo-purpose": "storage-smoke"}
        self.objects[(Bucket, Key)] = Body
        return {"ETag": "fixture"}

    def head_object(self, *, Bucket: str, Key: str) -> object:
        self.calls.append("head")
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def list_objects_v2(self, *, Bucket: str, Prefix: str, MaxKeys: int) -> object:
        self.calls.append("list")
        assert MaxKeys == 10
        return {
            "Contents": [
                {"Key": key}
                for bucket, key in self.objects
                if bucket == Bucket and key.startswith(Prefix)
            ]
        }

    def delete_object(self, *, Bucket: str, Key: str) -> object:
        self.calls.append("delete")
        if not self.delete_allowed:
            raise PermissionError("delete disabled")
        self.objects.pop((Bucket, Key), None)
        return {}


@dataclass(slots=True)
class MissingListSmokeClient(FakeSmokeClient):
    def list_objects_v2(self, *, Bucket: str, Prefix: str, MaxKeys: int) -> object:
        self.calls.append("list")
        return {"Contents": []}


def _settings() -> S3RuntimeSettings:
    return S3RuntimeSettings(
        bucket="jurisnexo-official",
        region="us-east-005",
        endpoint_url="https://s3.us-east-005.backblazeb2.com",
    )


def test_smoke_object_key_isolated_from_legal_corpus_namespace() -> None:
    key = smoke_object_key("github/run 123")

    assert key == f"{SMOKE_PREFIX}/github-run-123.txt"
    assert not key.startswith("jurisdictions/")


def test_storage_smoke_exercises_required_contract_and_cleans_up() -> None:
    client = FakeSmokeClient()

    result = run_s3_storage_smoke(
        _settings(),
        run_id="123-1",
        client_factory=lambda _: client,
    )

    assert result.key == f"{SMOKE_PREFIX}/123-1.txt"
    assert result.cleaned_up is True
    assert client.calls == ["put", "head", "list", "delete"]
    assert client.objects == {}


def test_storage_smoke_does_not_require_delete_permission() -> None:
    client = FakeSmokeClient(delete_allowed=False)

    result = run_s3_storage_smoke(
        _settings(),
        run_id="123-2",
        client_factory=lambda _: client,
    )

    assert result.cleaned_up is False
    assert client.calls == ["put", "head", "list", "delete"]
    assert ("jurisnexo-official", result.key) in client.objects


def test_storage_smoke_fails_when_list_contract_does_not_observe_written_object() -> None:
    client = MissingListSmokeClient()

    with pytest.raises(RuntimeError, match="ListObjectsV2 did not return"):
        run_s3_storage_smoke(
            _settings(),
            run_id="123-3",
            client_factory=lambda _: client,
        )

    assert client.calls == ["put", "head", "list", "delete"]
