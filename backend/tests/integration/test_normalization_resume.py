from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from jurisnexo.normalization.contracts import FormatInspection, NormalizedDocument
from jurisnexo.normalization.executor import NormalizationExecutor
from jurisnexo.normalization.planner import NormalizationPlan, NormalizationPlanItem
from jurisnexo.normalization.recovery import CircuitBreaker
from jurisnexo.normalization.repository import PostgresNormalizationLedger

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.provenance,
]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def test_reuse_returns_resolved_evidence_not_structural_candidate(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (sha256, mime_type, byte_size)
            values (%s, 'application/pdf', 10)
            returning id::text
            """,
            ("a" * 64,),
        )
        source = cursor.fetchone()
        assert source is not None

        cursor.execute(
            """
            insert into corpus.derived_artifacts
                (sha256, artifact_kind, mime_type, byte_size, storage_locator)
            values
                (%s, 'docling-json', 'application/json', 10, 's3://d/structural'),
                (%s, 'resolved-evidence-text', 'text/plain', 5, 's3://d/resolved')
            returning id::text
            """,
            ("b" * 64, "c" * 64),
        )
        structural = cursor.fetchone()
        resolved = cursor.fetchone()
        assert structural is not None
        assert resolved is not None

        cursor.execute(
            """
            insert into corpus.artifact_derivations
                (source_artifact_id, derived_artifact_id, derivation_type,
                 engine, pipeline_version, config_sha256)
            values (%s, %s, 'normalize', 'docling', 'v1', %s)
            """,
            (source[0], structural[0], "d" * 64),
        )
        cursor.execute(
            """
            insert into corpus.artifact_derivations
                (parent_derived_artifact_id, derived_artifact_id, derivation_type,
                 engine, pipeline_version, config_sha256)
            values (
                %s, %s, 'resolve_evidence_text',
                'jurisnexo-resolver', 'v1', %s
            )
            """,
            (structural[0], resolved[0], "d" * 64),
        )

        ledger = PostgresNormalizationLedger(connection)
        reusable = ledger.find_reusable_artifact(
            scope_id="00000000-0000-0000-0000-000000000001",
            source_artifact_id=str(source[0]),
            pipeline_version="v1",
            config_sha256="d" * 64,
        )
        assert reusable == str(resolved[0])
        assert reusable != str(structural[0])


def test_resume_identity_and_checkpoint_are_durable(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (sha256, mime_type, byte_size)
            values (%s, 'application/pdf', 10)
            returning id::text
            """,
            ("e" * 64,),
        )
        source = cursor.fetchone()
        assert source is not None

        cursor.execute(
            """
            insert into corpus.normalization_runs
                (input_manifest_locator, input_manifest_sha256,
                 pipeline_version, config_sha256, selected_count,
                 status, started_at)
            values (
                's3://manifest/resume.json',
                %s, 'v1', %s, 1, 'running', clock_timestamp()
            )
            returning id::text
            """,
            ("f" * 64, "1" * 64),
        )
        run = cursor.fetchone()
        assert run is not None

        cursor.execute(
            """
            insert into corpus.normalization_run_items
                (run_id, source_artifact_id, status, started_at)
            values (%s, %s, 'running', clock_timestamp())
            returning id::text
            """,
            (run[0], source[0]),
        )
        item = cursor.fetchone()
        assert item is not None

        ledger = PostgresNormalizationLedger(connection)
        ledger.validate_resume_run(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=str(run[0]),
            manifest_sha256="f" * 64,
            pipeline_version="v1",
            config_sha256="1" * 64,
        )
        checkpoint = ledger.item_checkpoint(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=str(run[0]),
            source_artifact_id=str(source[0]),
        )
        assert checkpoint is not None
        assert checkpoint.item_id == str(item[0])
        assert checkpoint.status == "running"
        assert checkpoint.normalized_artifact_id is None

        with pytest.raises(RuntimeError, match="does not match"):
            ledger.validate_resume_run(
                scope_id="00000000-0000-0000-0000-000000000001",
                run_id=str(run[0]),
                manifest_sha256="0" * 64,
                pipeline_version="v1",
                config_sha256="1" * 64,
            )


def test_retryable_item_returns_to_pending_for_same_run_resume(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (sha256, mime_type, byte_size)
            values (%s, 'application/pdf', 10)
            returning id::text
            """,
            ("2" * 64,),
        )
        source = cursor.fetchone()
        assert source is not None

        cursor.execute(
            """
            insert into corpus.normalization_runs
                (input_manifest_locator, input_manifest_sha256,
                 pipeline_version, config_sha256, selected_count,
                 status, started_at)
            values (
                's3://manifest/retryable.json',
                %s, 'v1', %s, 1, 'running', clock_timestamp()
            )
            returning id::text
            """,
            ("3" * 64, "4" * 64),
        )
        run = cursor.fetchone()
        assert run is not None

        ledger = PostgresNormalizationLedger(connection)
        item_id = ledger.ensure_item(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=str(run[0]),
            source_artifact_id=str(source[0]),
        )
        ledger.mark_running(
            scope_id="00000000-0000-0000-0000-000000000001",
            item_id=item_id,
        )
        ledger.mark_retryable(
            scope_id="00000000-0000-0000-0000-000000000001",
            item_id=item_id,
            error_code="TimeoutError",
            error_message="temporary upstream timeout",
        )

        checkpoint = ledger.item_checkpoint(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=str(run[0]),
            source_artifact_id=str(source[0]),
        )
        assert checkpoint is not None
        assert checkpoint.status == "pending"
        summary = ledger.summarize_run(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=str(run[0]),
        )
        assert summary.pending_count == 1
        assert summary.failed_count == 0

        ledger.validate_resume_run(
            scope_id="00000000-0000-0000-0000-000000000001",
            run_id=str(run[0]),
            manifest_sha256="3" * 64,
            pipeline_version="v1",
            config_sha256="4" * 64,
        )



class _ResumeMemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def exists(self, key: str) -> bool:
        return key in self.objects

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        del content_type, metadata
        self.objects.setdefault(key, content)


class _ResumeSourceReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.read_count = 0

    def read(self, key: str) -> bytes:
        assert key == "official/retryable.pdf"
        self.read_count += 1
        return self.payload


class _PdfInspector:
    def inspect(
        self,
        source: bytes,
        *,
        filename: str | None = None,
    ) -> FormatInspection:
        del source, filename
        return FormatInspection(
            media_type="application/pdf",
            detected_format="application/pdf",
            metadata={},
        )


class _FlakyNormalizer:
    def __init__(self) -> None:
        self.calls = 0

    def normalize(
        self,
        source: bytes,
        inspection: FormatInspection,
        *,
        filename: str | None = None,
    ) -> NormalizedDocument:
        del source, inspection, filename
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("temporary parser timeout")
        payload = (
            b'{"texts":[{"text":"Sentencia SCJ-SS-22-1191 Articulo 5"}]}'
        )
        return NormalizedDocument(
            media_type="application/vnd.docling+json",
            payload=payload,
            engine="fixture-docling",
            engine_version="1",
            metadata={},
        )


def test_executor_timeout_can_resume_same_run_without_duplicate_item(
    connection: psycopg.Connection[Any],
) -> None:
    scope_id = "00000000-0000-0000-0000-000000000001"
    source_sha = hashlib.sha256(b"retryable-resume-integration-fixture").hexdigest()
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (sha256, mime_type, byte_size)
            values (%s, 'application/pdf', 10)
            returning id::text
            """,
            (source_sha,),
        )
        source_row = cursor.fetchone()
        assert source_row is not None
        source_artifact_id = str(source_row[0])

        plan = NormalizationPlan(
            manifest_sha256="6" * 64,
            pipeline_version="v1",
            config_sha256="7" * 64,
            items=(
                NormalizationPlanItem(
                    source_identifier="retryable.pdf",
                    source_sha256=source_sha,
                    object_key="official/retryable.pdf",
                    content_type="application/pdf",
                    disposition="normalize",
                    idempotency_key="8" * 64,
                ),
            ),
        )
        store = _ResumeMemoryStore()
        reader = _ResumeSourceReader(b"%PDF-fixture")
        normalizer = _FlakyNormalizer()
        ledger = PostgresNormalizationLedger(connection)
        executor = NormalizationExecutor(
            inspector=_PdfInspector(),
            normalizer=normalizer,
            source_reader=reader,
            derived_store=store,
            ledger=ledger,
            pipeline_version="v1",
            config_sha256="7" * 64,
            circuit_breaker=CircuitBreaker(threshold=3),
        )

        first = executor.execute(
            plan=plan,
            scope_id=scope_id,
            manifest_locator="s3://manifest/retryable.json",
        )
        assert first.retryable_pending == 1
        assert first.failed == 0

        checkpoint = ledger.item_checkpoint(
            scope_id=scope_id,
            run_id=first.run_id,
            source_artifact_id=source_artifact_id,
        )
        assert checkpoint is not None
        assert checkpoint.status == "pending"

        second = executor.execute(
            plan=plan,
            scope_id=scope_id,
            manifest_locator="s3://manifest/retryable.json",
            resume_run_id=first.run_id,
        )
        assert second.run_id == first.run_id
        assert second.retryable_pending == 0
        assert second.normalized == 1
        assert normalizer.calls == 2
        assert reader.read_count == 2

        cursor.execute(
            """
            select status,
                   (select count(*) from corpus.normalization_run_items i
                    where i.run_id=r.id)
            from corpus.normalization_runs r
            where id=%s
            """,
            (first.run_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "reconciling"
        assert row[1] == 1
