from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import psycopg
import pytest

from jurisnexo.acquisition.s3_object_store import (
    S3ObjectStore,
    S3ObjectStoreConfig,
)
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


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def _setup_reconciling_run(
    connection: psycopg.Connection[Any],
    *,
    source_sha: str,
    normalized_sha: str,
    config_sha: str,
    input_manifest_sha: str,
    normalized_key: str,
) -> tuple[str, NormalizationPlan]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (sha256, mime_type, byte_size)
            values (%s, 'application/pdf', 100)
            returning id::text
            """,
            (source_sha,),
        )
        source_row = cursor.fetchone()
        assert source_row is not None
        source_id = str(source_row[0])

        cursor.execute(
            """
            insert into corpus.derived_artifacts
                (sha256, artifact_kind, mime_type, byte_size, storage_locator)
            values (
                %s,
                'resolved-evidence-text',
                'text/plain; charset=utf-8',
                17,
                %s
            )
            returning id::text
            """,
            (normalized_sha, normalized_key),
        )
        artifact_row = cursor.fetchone()
        assert artifact_row is not None
        artifact_id = str(artifact_row[0])

        cursor.execute(
            """
            insert into corpus.artifact_derivations
                (source_artifact_id, derived_artifact_id, derivation_type,
                 engine, pipeline_version, config_sha256)
            values (%s, %s, 'normalize', 'fixture', 'v1', %s)
            """,
            (source_id, artifact_id, config_sha),
        )

        cursor.execute(
            """
            insert into corpus.normalization_runs
                (input_manifest_locator, input_manifest_sha256,
                 pipeline_version, config_sha256, selected_count,
                 status, started_at)
            values (
                's3://fixture/input.json',
                %s,
                'v1',
                %s,
                1,
                'reconciling',
                clock_timestamp()
            )
            returning id::text
            """,
            (input_manifest_sha, config_sha),
        )
        run_row = cursor.fetchone()
        assert run_row is not None
        run_id = str(run_row[0])

        cursor.execute(
            """
            insert into corpus.normalization_run_items
                (run_id, source_artifact_id, status,
                 normalized_artifact_id, started_at, finished_at)
            values (
                %s, %s, 'normalized', %s,
                clock_timestamp(), clock_timestamp()
            )
            returning id::text
            """,
            (run_id, source_id, artifact_id),
        )
        item_row = cursor.fetchone()
        assert item_row is not None

        cursor.execute(
            """
            insert into corpus.normalization_observations
                (run_item_id, artifact_id, observation_kind, payload, status)
            values (
                %s, %s, 'deterministic_qa',
                '{"risk_flags":[]}'::jsonb, 'accepted'
            )
            """,
            (str(item_row[0]), artifact_id),
        )

    plan = NormalizationPlan(
        manifest_sha256=input_manifest_sha,
        pipeline_version="v1",
        config_sha256=config_sha,
        items=(
            NormalizationPlanItem(
                source_identifier="retry-finalizer-fixture",
                source_sha256=source_sha,
                object_key="official/source.pdf",
                content_type="application/pdf",
                disposition="normalize",
                idempotency_key="9" * 64,
            ),
        ),
    )
    return run_id, plan


def test_finalizer_retry_after_manifest_storage_write_is_byte_stable(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        normalized_key = "derived/normalization/resolved-evidence-text/v1/retry-fixture"
        client = _MemoryS3Client(objects={normalized_key: b"resolved evidence"})
        store = S3ObjectStore(
            client=client,
            config=S3ObjectStoreConfig(bucket="fixture", region="us-east-1"),
            is_not_found=lambda exc: isinstance(exc, _NotFound),
        )
        run_id, plan = _setup_reconciling_run(
            connection,
            source_sha=_sha("finalizer-retry-storage-source"),
            normalized_sha=_sha("finalizer-retry-storage-derived"),
            config_sha="3" * 64,
            input_manifest_sha="4" * 64,
            normalized_key=normalized_key,
        )
        ledger = PostgresNormalizationLedger(connection)

        with pytest.raises(TimeoutError, match="after manifest storage"):
            NormalizationFinalizer(
                ledger=ledger,
                object_store=_CrashAfterManifestPut(store),
            ).finalize(
                plan=plan,
                run_id=run_id,
                scope_id="00000000-0000-0000-0000-000000000001",
                pipeline_version="v1",
                config_sha256="3" * 64,
            )

        manifest_keys_after_crash = {
            key
            for key in client.objects
            if key.startswith("_manifests/normalization/")
        }
        assert len(manifest_keys_after_crash) == 1

        with connection.cursor() as cursor:
            cursor.execute(
                """
                select count(m.id)::int,
                       r.metadata->>'manifest_published_at'
                from corpus.normalization_runs r
                left join corpus.normalization_manifests m
                  on m.scope_id=r.scope_id and m.run_id=r.id
                where r.id=%s
                group by r.metadata
                """,
                (run_id,),
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == 0
            assert row[1]

        result = NormalizationFinalizer(
            ledger=ledger,
            object_store=store,
        ).finalize(
            plan=plan,
            run_id=run_id,
            scope_id="00000000-0000-0000-0000-000000000001",
            pipeline_version="v1",
            config_sha256="3" * 64,
        )
        assert result.status == "succeeded"
        assert result.manifest_object_key in manifest_keys_after_crash
        assert {
            key
            for key in client.objects
            if key.startswith("_manifests/normalization/")
        } == manifest_keys_after_crash

        with connection.cursor() as cursor:
            cursor.execute(
                """
                select count(*)::int
                from corpus.normalization_manifests
                where run_id=%s
                """,
                (run_id,),
            )
            assert cursor.fetchone() == (1,)


def test_manifest_db_persistence_is_idempotent_but_rejects_drift(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        normalized_key = "derived/normalization/resolved-evidence-text/v1/idempotent-fixture"
        run_id, _ = _setup_reconciling_run(
            connection,
            source_sha=_sha("finalizer-retry-db-source"),
            normalized_sha=_sha("finalizer-retry-db-derived"),
            config_sha="7" * 64,
            input_manifest_sha="8" * 64,
            normalized_key=normalized_key,
        )
        ledger = PostgresNormalizationLedger(connection)
        summary = ledger.summarize_run(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=run_id,
        )

        first = ledger.persist_manifest(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=run_id,
            sha256="a" * 64,
            storage_locator=f"s3://fixture/{run_id}/manifest.json",
            byte_size=123,
            summary=summary,
        )
        second = ledger.persist_manifest(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=run_id,
            sha256="a" * 64,
            storage_locator=f"s3://fixture/{run_id}/manifest.json",
            byte_size=123,
            summary=summary,
        )
        assert second == first

        with pytest.raises(RuntimeError, match="does not match retry payload"):
            ledger.persist_manifest(
                scope_id="00000000-0000-0000-0000-000000000001",
                run_id=run_id,
                sha256="b" * 64,
                storage_locator=f"s3://fixture/{run_id}/manifest.json",
                byte_size=123,
                summary=summary,
            )
