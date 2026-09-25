from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from jurisnexo.acquisition.s3_object_store import S3ObjectStore, build_s3_object_store
from jurisnexo.normalization.contracts import FormatInspection, NormalizedDocument
from jurisnexo.normalization.executor import NormalizationExecutor
from jurisnexo.normalization.finalizer import NormalizationFinalizer
from jurisnexo.normalization.planner import NormalizationPlan, NormalizationPlanItem
from jurisnexo.normalization.recovery import CircuitBreaker
from jurisnexo.normalization.repository import PostgresNormalizationLedger
from jurisnexo.normalization.s3_source_reader import S3SourceByteReader

SCOPE_ID = "00000000-0000-0000-0000-000000000001"
PIPELINE_VERSION = "operational-resume-drill-v1"
CONFIG_SHA = hashlib.sha256(b"operational-resume-drill-config-v1").hexdigest()
MANIFEST_SHA = hashlib.sha256(b"operational-resume-drill-manifest-v1").hexdigest()
TEXT = (
    "SENTENCIA SCJ-SS-22-1191. Articulo 5 de la Ley 13-07. "
    "FALLA: Primero, rechaza el recurso."
)
OUTPUT = Path(
    os.environ.get(
        "NORMALIZATION_RESUME_DRILL_OUTPUT",
        ".artifacts/normalization-resume-drill/results.json",
    )
)


@dataclass
class _Inspector:
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


@dataclass
class _Normalizer:
    def normalize(
        self,
        source: bytes,
        inspection: FormatInspection,
        *,
        filename: str | None = None,
    ) -> NormalizedDocument:
        del source, inspection, filename
        payload = json.dumps(
            {
                "body": {"children": [{"$ref": "#/texts/0"}]},
                "texts": [{"text": TEXT}],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return NormalizedDocument(
            media_type="application/vnd.docling+json",
            payload=payload,
            engine="resume-drill-fixture",
            engine_version="1",
            metadata={},
        )


@dataclass
class _FailAfterFirstDerivedPut:
    store: S3ObjectStore
    faulted: bool = False
    fault_key: str | None = None
    written_keys: set[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.written_keys is None:
            self.written_keys = set()

    def exists(self, key: str) -> bool:
        return self.store.exists(key)

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        self.store.put(
            key=key,
            content=content,
            content_type=content_type,
            metadata=metadata,
        )
        self.written_keys.add(key)
        if (
            not self.faulted
            and key.startswith("derived/normalization/docling-json/")
        ):
            self.faulted = True
            self.fault_key = key
            raise TimeoutError(
                "injected crash after S3 write and before PostgreSQL registration"
            )


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value


def _source_key() -> str:
    run = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    return f"derived/normalization/drills/{run}-{attempt}/source.pdf"


def _source_bytes() -> bytes:
    run = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    return (
        b"%PDF-synthetic-operational-resume-drill\n"
        + f"run={run};attempt={attempt}\n".encode("utf-8")
    )


def _delete_keys(store: S3ObjectStore, keys: set[str]) -> None:
    client = store.client
    for key in sorted(keys):
        client.delete_object(Bucket=store.config.bucket, Key=key)  # type: ignore[attr-defined]
        if store.exists(key):
            raise RuntimeError(f"test object cleanup failed for {key}")


def main() -> int:
    store = build_s3_object_store()
    source_key = _source_key()
    source_bytes = _source_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    created_keys: set[str] = {source_key}

    store.put(
        key=source_key,
        content=source_bytes,
        content_type="application/pdf",
        metadata={
            "sha256": source_sha,
            "purpose": "normalization_operational_resume_drill",
        },
    )

    try:
        with psycopg.connect(_database_url(), autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    insert into corpus.source_artifacts
                        (scope_id, sha256, mime_type, byte_size)
                    values (%s, %s, 'application/pdf', %s)
                    returning id::text
                    """,
                    (SCOPE_ID, source_sha, len(source_bytes)),
                )
                source_row = cursor.fetchone()
                assert source_row is not None
                source_artifact_id = str(source_row[0])

            ledger = PostgresNormalizationLedger(connection)
            fault_store = _FailAfterFirstDerivedPut(store)
            plan = NormalizationPlan(
                manifest_sha256=MANIFEST_SHA,
                pipeline_version=PIPELINE_VERSION,
                config_sha256=CONFIG_SHA,
                items=(
                    NormalizationPlanItem(
                        source_identifier="synthetic-resume-drill.pdf",
                        source_sha256=source_sha,
                        object_key=source_key,
                        content_type="application/pdf",
                        disposition="normalize",
                        idempotency_key=hashlib.sha256(
                            f"{source_sha}:{PIPELINE_VERSION}:{CONFIG_SHA}".encode(
                                "utf-8"
                            )
                        ).hexdigest(),
                    ),
                ),
            )
            executor = NormalizationExecutor(
                inspector=_Inspector(),
                normalizer=_Normalizer(),
                source_reader=S3SourceByteReader(store),
                derived_store=fault_store,
                ledger=ledger,
                pipeline_version=PIPELINE_VERSION,
                config_sha256=CONFIG_SHA,
                circuit_breaker=CircuitBreaker(threshold=3),
            )

            first = executor.execute(
                plan=plan,
                scope_id=SCOPE_ID,
                manifest_locator="ci://operational-resume-drill/manifest.json",
            )
            if first.retryable_pending != 1 or first.failed != 0:
                raise RuntimeError(
                    "injected transient failure was not preserved as retryable pending"
                )
            if fault_store.fault_key is None or not store.exists(fault_store.fault_key):
                raise RuntimeError("fault injection did not leave the S3 object behind")
            created_keys.add(fault_store.fault_key)

            checkpoint = ledger.item_checkpoint(
                scope_id=SCOPE_ID,
                run_id=first.run_id,
                source_artifact_id=source_artifact_id,
            )
            if checkpoint is None or checkpoint.status != "pending":
                raise RuntimeError("retryable item did not return to pending")

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select count(*)::int
                    from corpus.derived_artifacts d
                    join corpus.artifact_derivations a
                      on a.scope_id=d.scope_id
                     and a.derived_artifact_id=d.id
                    where a.scope_id=%s
                      and a.source_artifact_id=%s
                      and d.storage_locator=%s
                    """,
                    (SCOPE_ID, source_artifact_id, fault_store.fault_key),
                )
                pre_resume_row = cursor.fetchone()
                assert pre_resume_row is not None
                if int(pre_resume_row[0]) != 0:
                    raise RuntimeError(
                        "DB registered the derived artifact before the injected crash"
                    )

            second = executor.execute(
                plan=plan,
                scope_id=SCOPE_ID,
                manifest_locator="ci://operational-resume-drill/manifest.json",
                resume_run_id=first.run_id,
            )
            if second.run_id != first.run_id:
                raise RuntimeError("resume created a different normalization run")
            if second.retryable_pending != 0 or second.normalized != 1:
                raise RuntimeError("same-run resume did not complete the pending item")

            finalization = NormalizationFinalizer(
                ledger=ledger,
                object_store=store,
            ).finalize(
                plan=plan,
                run_id=second.run_id,
                scope_id=SCOPE_ID,
                pipeline_version=PIPELINE_VERSION,
                config_sha256=CONFIG_SHA,
            )
            created_keys.add(finalization.manifest_object_key)

            state = ledger.reconciliation_state(
                scope_id=SCOPE_ID,
                run_id=second.run_id,
            )
            created_keys.update(state.artifact_storage_keys.values())

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select count(*)::int
                    from corpus.normalization_run_items
                    where scope_id=%s and run_id=%s
                    """,
                    (SCOPE_ID, second.run_id),
                )
                item_count = int(cursor.fetchone()[0])

                cursor.execute(
                    """
                    select count(*)::int
                    from corpus.normalization_manifests
                    where scope_id=%s and run_id=%s
                    """,
                    (SCOPE_ID, second.run_id),
                )
                manifest_count = int(cursor.fetchone()[0])

                cursor.execute(
                    """
                    select count(*)::int
                    from corpus.derived_artifacts d
                    join corpus.artifact_derivations a
                      on a.scope_id=d.scope_id
                     and a.derived_artifact_id=d.id
                    where a.scope_id=%s
                      and a.source_artifact_id=%s
                      and d.artifact_kind='docling-json'
                    """,
                    (SCOPE_ID, source_artifact_id),
                )
                structural_count = int(cursor.fetchone()[0])

            checks = {
                "fault_object_survived_crash": True,
                "retryable_returned_to_pending": True,
                "same_run_id_resumed": second.run_id == first.run_id,
                "exactly_one_run_item": item_count == 1,
                "exactly_one_structural_artifact": structural_count == 1,
                "exactly_one_manifest": manifest_count == 1,
                "finalizer_succeeded": finalization.status == "succeeded",
                "run_reconciled": (
                    ledger.summarize_run(
                        scope_id=SCOPE_ID,
                        run_id=second.run_id,
                    ).status
                    == "succeeded"
                ),
            }
            payload: dict[str, Any] = {
                "schema_version": 1,
                "run_id": second.run_id,
                "source_sha256": source_sha,
                "injected_fault": "after_s3_put_before_db_registration",
                "first_execution": {
                    "normalized": first.normalized,
                    "failed": first.failed,
                    "retryable_pending": first.retryable_pending,
                },
                "second_execution": {
                    "normalized": second.normalized,
                    "failed": second.failed,
                    "retryable_pending": second.retryable_pending,
                },
                "finalization_status": finalization.status,
                "checks": checks,
                "passed": all(checks.values()),
            }

        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["passed"] else 2
    finally:
        if "fault_store" in locals():
            created_keys.update(fault_store.written_keys)
        _delete_keys(store, created_keys)


if __name__ == "__main__":
    raise SystemExit(main())
