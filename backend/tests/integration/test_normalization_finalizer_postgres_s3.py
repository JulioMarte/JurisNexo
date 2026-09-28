from __future__ import annotations

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
from jurisnexo.normalization.planner import (
    NormalizationPlan,
    NormalizationPlanItem,
)
from jurisnexo.normalization.repository import PostgresNormalizationLedger

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.provenance,
]


class _NotFound(Exception):
    pass


@dataclass
class _MemoryS3Client:
    objects: dict[str, bytes] = field(default_factory=lambda: {})

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
            raise AssertionError("immutable manifest/object key must not be overwritten")
        self.objects[Key] = Body
        return {"ETag": "fixture"}


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def test_finalizer_reconciles_postgres_and_s3_before_terminal_success(
    connection: psycopg.Connection[Any],
) -> None:
    source_sha = "a" * 64
    normalized_sha = "b" * 64
    config_sha = "c" * 64
    input_manifest_sha = "d" * 64
    normalized_key = "derived/normalization/resolved-evidence-text/v1/fixture"

    client = _MemoryS3Client(objects={normalized_key: b"resolved evidence"})
    store = S3ObjectStore(
        client=client,
        config=S3ObjectStoreConfig(bucket="fixture", region="us-east-1"),
        is_not_found=lambda exc: isinstance(exc, _NotFound),
    )

    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
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
            values (
                %s, %s, 'normalize', 'fixture', 'v1', %s
            )
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
                's3://fixture/acquisition-manifest.json',
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
        item_id = str(item_row[0])

        cursor.execute(
            """
            insert into corpus.normalization_observations
                (run_item_id, artifact_id, observation_kind, payload, status)
            values (
                %s,
                %s,
                'deterministic_qa',
                '{"risk_flags":[]}'::jsonb,
                'accepted'
            )
            """,
            (item_id, artifact_id),
        )

        plan = NormalizationPlan(
            manifest_sha256=input_manifest_sha,
            pipeline_version="v1",
            config_sha256=config_sha,
            items=(
                NormalizationPlanItem(
                    source_identifier="principales-fixture",
                    source_sha256=source_sha,
                    object_key="official/source.pdf",
                    content_type="application/pdf",
                    disposition="normalize",
                    idempotency_key="e" * 64,
                ),
            ),
        )

        result = NormalizationFinalizer(
            ledger=PostgresNormalizationLedger(connection),
            object_store=store,
        ).finalize(
            plan=plan,
            run_id=run_id,
            scope_id="00000000-0000-0000-0000-000000000001",
            pipeline_version="v1",
            config_sha256=config_sha,
        )

        assert result.status == "succeeded"
        assert result.manifest_object_key in client.objects
        assert result.manifest_sha256
        manifest_payload = client.objects[result.manifest_object_key]
        assert b'"schema_version":1' in manifest_payload
        assert source_id.encode() in manifest_payload

        cursor.execute(
            """
            select status, normalized_count, failed_count, finished_at is not null
            from corpus.normalization_runs
            where id=%s
            """,
            (run_id,),
        )
        run_state = cursor.fetchone()
        assert run_state == ("succeeded", 1, 0, True)

        cursor.execute(
            """
            select sha256, storage_locator, selected_count, normalized_count
            from corpus.normalization_manifests
            where run_id=%s
            """,
            (run_id,),
        )
        manifest_row = cursor.fetchone()
        assert manifest_row is not None
        assert manifest_row[0] == result.manifest_sha256
        assert manifest_row[1] == result.manifest_object_key
        assert manifest_row[2:] == (1, 1)
