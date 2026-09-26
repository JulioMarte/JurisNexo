from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import psycopg
import pytest

from jurisnexo.acquisition.s3_object_store import S3ObjectStore, S3ObjectStoreConfig
from jurisnexo.normalization.finalizer import NormalizationFinalizer
from jurisnexo.normalization.planner import NormalizationPlan, NormalizationPlanItem
from jurisnexo.normalization.repository import PostgresNormalizationLedger


class _NotFound(Exception):
    pass


@dataclass
class _MemoryS3Client:
    objects: dict[str, bytes] = field(default_factory=dict)

    def head_object(self, *, Bucket: str, Key: str) -> object:
        del Bucket
        if Key not in self.objects:
            raise _NotFound(Key)
        return {"ContentLength": len(self.objects[Key])}

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        Metadata: dict[str, str],
    ) -> object:
        del Bucket, ContentType, Metadata
        if Key in self.objects:
            raise AssertionError("immutable object must not be overwritten")
        self.objects[Key] = Body
        return {"ETag": "fixture"}


@dataclass
class _CrashAfterManifestPut:
    base: S3ObjectStore
    injected: bool = False

    def exists(self, key: str) -> bool:
        return self.base.exists(key)

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        self.base.put(
            key=key,
            content=content,
            content_type=content_type,
            metadata=metadata,
        )
        if not self.injected and key.startswith("_manifests/normalization/"):
            self.injected = True
            raise TimeoutError("injected crash after manifest storage publication")


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        pytest.skip("DATABASE_URL is required")
    return value


@pytest.fixture
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(_database_url(), autocommit=True) as conn:
        yield conn


def _insert_source(
    connection: psycopg.Connection[Any], *, scope_id: str, sha256: str
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (scope_id, sha256, mime_type, byte_size)
            values (%s, %s, 'application/pdf', 4)
            returning id::text
            """,
            (scope_id, sha256),
        )
        row = cursor.fetchone()
        assert row is not None
        return str(row[0])


def test_finalizer_retries_after_manifest_put_without_duplicate_rows(
    connection: psycopg.Connection[Any],
) -> None:
    scope_id = "00000000-0000-0000-0000-000000000001"
    source_sha = _sha("finalizer-retry-source")
    source_artifact_id = _insert_source(connection, scope_id=scope_id, sha256=source_sha)
    pipeline_version = "retry-finalizer-v1"
    config_sha = _sha("retry-finalizer-config")
    manifest_sha = _sha("retry-finalizer-manifest")
    idempotency_key = _sha(f"{source_sha}:{pipeline_version}:{config_sha}")
    plan = NormalizationPlan(
        manifest_sha256=manifest_sha,
        pipeline_version=pipeline_version,
        config_sha256=config_sha,
        items=(
            NormalizationPlanItem(
                source_identifier="retry.pdf",
                source_sha256=source_sha,
                object_key="official/retry.pdf",
                content_type="application/pdf",
                disposition="normalize",
                idempotency_key=idempotency_key,
            ),
        ),
    )
    ledger = PostgresNormalizationLedger(connection)
    run_id = ledger.create_run(
        scope_id=scope_id,
        pipeline_version=pipeline_version,
        config_sha256=config_sha,
        manifest_sha256=manifest_sha,
        manifest_locator="ci://retry/manifest.json",
        selected_count=1,
    )
    item_id = ledger.ensure_item(
        scope_id=scope_id,
        run_id=run_id,
        source_artifact_id=source_artifact_id,
    )
    # A failed item is a valid terminal item for reconciliation and requires no
    # derived artifact. This keeps the test focused on manifest publication
    # idempotency rather than on the normalization executor itself.
    ledger.mark_running(scope_id=scope_id, item_id=item_id)
    ledger.mark_failed(
        scope_id=scope_id,
        item_id=item_id,
        error_code="fixture_failure",
        error_message="terminal fixture item",
    )

    client = _MemoryS3Client()
    store = S3ObjectStore(
        client=client,  # type: ignore[arg-type]
        config=S3ObjectStoreConfig(
            bucket="fixture",
            endpoint_url=None,
            region="us-east-1",
            access_key_id="fixture",
            secret_access_key="fixture",
            force_path_style=True,
        ),
    )
    crash_store = _CrashAfterManifestPut(store)
    finalizer = NormalizationFinalizer(ledger=ledger, object_store=crash_store)

    with pytest.raises(TimeoutError, match="manifest storage publication"):
        finalizer.finalize(
            plan=plan,
            run_id=run_id,
            scope_id=scope_id,
            pipeline_version=pipeline_version,
            config_sha256=config_sha,
        )

    assert len(client.objects) == 1
    manifest_key = next(iter(client.objects))
    assert manifest_key.startswith("_manifests/normalization/")
    ledger.validate_resume_run(
        scope_id=scope_id,
        run_id=run_id,
        manifest_sha256=manifest_sha,
        pipeline_version=pipeline_version,
        config_sha256=config_sha,
    )

    result = NormalizationFinalizer(ledger=ledger, object_store=store).finalize(
        plan=plan,
        run_id=run_id,
        scope_id=scope_id,
        pipeline_version=pipeline_version,
        config_sha256=config_sha,
    )
    assert result.status == "completed_with_errors"
    assert result.manifest_object_key == manifest_key
    assert len(client.objects) == 1

    with connection.cursor() as cursor:
        cursor.execute(
            """
            select count(*)::int
            from corpus.normalization_manifests
            where scope_id=%s and run_id=%s
            """,
            (scope_id, run_id),
        )
        row = cursor.fetchone()
        assert row is not None
        assert int(row[0]) == 1
