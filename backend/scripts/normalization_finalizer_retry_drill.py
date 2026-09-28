from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from jurisnexo.acquisition.s3_object_store import S3ObjectStore, build_s3_object_store
from jurisnexo.normalization.finalizer import NormalizationFinalizer
from jurisnexo.normalization.planner import NormalizationPlan, NormalizationPlanItem
from jurisnexo.normalization.repository import PostgresNormalizationLedger, RunSummary

SCOPE_ID = "00000000-0000-0000-0000-000000000001"
PIPELINE_VERSION = "finalizer-retry-drill-v1"
OUTPUT = Path(
    os.environ.get(
        "NORMALIZATION_FINALIZER_RETRY_OUTPUT",
        ".artifacts/normalization-resume-drill/finalizer-retry.json",
    )
)


@dataclass
class _CrashAfterManifestPut:
    base: S3ObjectStore
    injected: bool = False
    manifest_key: str | None = None

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
            self.manifest_key = key
            raise TimeoutError(
                "injected crash after manifest S3 write before DB persistence"
            )


@dataclass
class _CrashAfterManifestPersist:
    base: PostgresNormalizationLedger
    injected: bool = False
    manifest_record_id: str | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)

    def persist_manifest(
        self,
        *,
        scope_id: str,
        run_id: str,
        sha256: str,
        storage_locator: str,
        byte_size: int,
        summary: RunSummary,
    ) -> str:
        record_id = self.base.persist_manifest(
            scope_id=scope_id,
            run_id=run_id,
            sha256=sha256,
            storage_locator=storage_locator,
            byte_size=byte_size,
            summary=summary,
        )
        self.manifest_record_id = record_id
        if not self.injected:
            self.injected = True
            raise TimeoutError(
                "injected crash after DB manifest persistence before run close"
            )
        return record_id


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value


def _run_token() -> str:
    return (
        f"{os.environ.get('GITHUB_RUN_ID', 'local')}-"
        f"{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    )


def _sha(label: str) -> str:
    return hashlib.sha256(f"{_run_token()}:{label}".encode()).hexdigest()


def _put_resolved_fixture(
    store: S3ObjectStore,
    *,
    label: str,
) -> tuple[str, bytes]:
    payload = (
        "SENTENCIA SCJ-SS-22-1191. Articulo 5 de la Ley 13-07. "
        f"Fixture de finalizacion idempotente: {label}."
    ).encode()
    key = (
        "derived/normalization/drills/"
        f"{_run_token()}/finalizer/{label}/resolved.txt"
    )
    store.put(
        key=key,
        content=payload,
        content_type="text/plain; charset=utf-8",
        metadata={
            "sha256": hashlib.sha256(payload).hexdigest(),
            "purpose": "normalization_finalizer_retry_drill",
        },
    )
    return key, payload


def _setup_run(
    connection: psycopg.Connection[Any],
    store: S3ObjectStore,
    *,
    label: str,
) -> tuple[str, str, NormalizationPlan, set[str]]:
    source_sha = _sha(f"{label}:source")
    normalized_sha = _sha(f"{label}:resolved")
    config_sha = _sha(f"{label}:config")
    input_manifest_sha = _sha(f"{label}:input-manifest")
    resolved_key, resolved_payload = _put_resolved_fixture(
        store,
        label=label,
    )
    created_keys = {resolved_key}

    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (scope_id, sha256, mime_type, byte_size)
            values (%s, %s, 'application/pdf', 100)
            returning id::text
            """,
            (SCOPE_ID, source_sha),
        )
        source_row = cursor.fetchone()
        assert source_row is not None
        source_id = str(source_row[0])

        cursor.execute(
            """
            insert into corpus.derived_artifacts
                (scope_id, sha256, artifact_kind, mime_type,
                 byte_size, storage_locator)
            values (
                %s, %s, 'resolved-evidence-text',
                'text/plain; charset=utf-8', %s, %s
            )
            returning id::text
            """,
            (
                SCOPE_ID,
                normalized_sha,
                len(resolved_payload),
                resolved_key,
            ),
        )
        artifact_row = cursor.fetchone()
        assert artifact_row is not None
        artifact_id = str(artifact_row[0])

        cursor.execute(
            """
            insert into corpus.artifact_derivations
                (scope_id, source_artifact_id, derived_artifact_id,
                 derivation_type, engine, pipeline_version, config_sha256)
            values (%s, %s, %s, 'normalize', 'fixture', %s, %s)
            """,
            (
                SCOPE_ID,
                source_id,
                artifact_id,
                PIPELINE_VERSION,
                config_sha,
            ),
        )

        cursor.execute(
            """
            insert into corpus.normalization_runs
                (scope_id, input_manifest_locator, input_manifest_sha256,
                 pipeline_version, config_sha256, selected_count,
                 status, started_at)
            values (
                %s, %s, %s, %s, %s, 1,
                'reconciling', clock_timestamp()
            )
            returning id::text
            """,
            (
                SCOPE_ID,
                f"ci://finalizer-retry/{label}/input.json",
                input_manifest_sha,
                PIPELINE_VERSION,
                config_sha,
            ),
        )
        run_row = cursor.fetchone()
        assert run_row is not None
        run_id = str(run_row[0])

        cursor.execute(
            """
            insert into corpus.normalization_run_items
                (scope_id, run_id, source_artifact_id, status,
                 normalized_artifact_id, started_at, finished_at)
            values (
                %s, %s, %s, 'normalized', %s,
                clock_timestamp(), clock_timestamp()
            )
            returning id::text
            """,
            (SCOPE_ID, run_id, source_id, artifact_id),
        )
        item_row = cursor.fetchone()
        assert item_row is not None

        cursor.execute(
            """
            insert into corpus.normalization_observations
                (scope_id, run_item_id, artifact_id,
                 observation_kind, payload, status)
            values (
                %s, %s, %s, 'deterministic_qa',
                '{"risk_flags":[]}'::jsonb, 'accepted'
            )
            """,
            (SCOPE_ID, str(item_row[0]), artifact_id),
        )

    plan = NormalizationPlan(
        manifest_sha256=input_manifest_sha,
        pipeline_version=PIPELINE_VERSION,
        config_sha256=config_sha,
        items=(
            NormalizationPlanItem(
                source_identifier=f"finalizer-retry-{label}",
                source_sha256=source_sha,
                object_key=f"official/{label}.pdf",
                content_type="application/pdf",
                disposition="normalize",
                idempotency_key=_sha(f"{label}:idempotency"),
            ),
        ),
    )
    return run_id, config_sha, plan, created_keys


def _manifest_rows(
    connection: psycopg.Connection[Any],
    *,
    run_id: str,
) -> tuple[tuple[Any, ...], ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select id::text, sha256, storage_locator
            from corpus.normalization_manifests
            where scope_id=%s and run_id=%s
            order by published_at
            """,
            (SCOPE_ID, run_id),
        )
        return tuple(cursor.fetchall())


def _run_status(
    connection: psycopg.Connection[Any],
    *,
    run_id: str,
) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select status
            from corpus.normalization_runs
            where scope_id=%s and id=%s
            """,
            (SCOPE_ID, run_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("normalization run disappeared")
        return str(row[0])


def _manifest_keys(store: S3ObjectStore, *, run_id: str) -> tuple[str, ...]:
    response = store.client.list_objects_v2(
        Bucket=store.config.bucket,
        Prefix=f"_manifests/normalization/{run_id}/",
    )
    return tuple(
        sorted(
            str(item["Key"])
            for item in response.get("Contents", [])
        )
    )


def _delete_keys(store: S3ObjectStore, keys: set[str]) -> None:
    for key in sorted(keys):
        store.client.delete_object(
            Bucket=store.config.bucket,
            Key=key,
        )
        if store.exists(key):
            raise RuntimeError(f"test object cleanup failed for {key}")


def _scenario_after_storage(
    connection: psycopg.Connection[Any],
    store: S3ObjectStore,
) -> dict[str, object]:
    run_id, config_sha, plan, created_keys = _setup_run(
        connection,
        store,
        label="after-storage-before-db",
    )
    ledger = PostgresNormalizationLedger(connection)
    fault_store = _CrashAfterManifestPut(store)
    try:
        try:
            NormalizationFinalizer(
                ledger=ledger,
                object_store=fault_store,
            ).finalize(
                plan=plan,
                run_id=run_id,
                scope_id=SCOPE_ID,
                pipeline_version=PIPELINE_VERSION,
                config_sha256=config_sha,
            )
        except TimeoutError:
            pass
        else:
            raise RuntimeError("manifest-storage fault was not injected")

        if fault_store.manifest_key is None:
            raise RuntimeError("manifest storage fault did not capture object key")
        created_keys.add(fault_store.manifest_key)
        keys_after_crash = _manifest_keys(store, run_id=run_id)
        rows_after_crash = _manifest_rows(connection, run_id=run_id)
        status_after_crash = _run_status(connection, run_id=run_id)

        retry = NormalizationFinalizer(
            ledger=ledger,
            object_store=store,
        ).finalize(
            plan=plan,
            run_id=run_id,
            scope_id=SCOPE_ID,
            pipeline_version=PIPELINE_VERSION,
            config_sha256=config_sha,
        )
        final_keys = _manifest_keys(store, run_id=run_id)
        final_rows = _manifest_rows(connection, run_id=run_id)

        checks = {
            "one_manifest_object_after_crash": len(keys_after_crash) == 1,
            "zero_manifest_rows_after_crash": len(rows_after_crash) == 0,
            "run_stayed_reconciling_after_crash": (
                status_after_crash == "reconciling"
            ),
            "retry_reused_same_manifest_key": (
                retry.manifest_object_key == fault_store.manifest_key
            ),
            "one_manifest_object_after_retry": len(final_keys) == 1,
            "one_manifest_row_after_retry": len(final_rows) == 1,
            "retry_closed_run": _run_status(connection, run_id=run_id) == "succeeded",
        }
        return {
            "run_id": run_id,
            "checks": checks,
            "passed": all(checks.values()),
            "manifest_key": fault_store.manifest_key,
            "manifest_sha256": retry.manifest_sha256,
        }
    finally:
        created_keys.update(_manifest_keys(store, run_id=run_id))
        _delete_keys(store, created_keys)


def _scenario_after_db_persist(
    connection: psycopg.Connection[Any],
    store: S3ObjectStore,
) -> dict[str, object]:
    run_id, config_sha, plan, created_keys = _setup_run(
        connection,
        store,
        label="after-db-before-close",
    )
    ledger = PostgresNormalizationLedger(connection)
    fault_ledger = _CrashAfterManifestPersist(ledger)
    try:
        try:
            NormalizationFinalizer(
                ledger=fault_ledger,
                object_store=store,
            ).finalize(
                plan=plan,
                run_id=run_id,
                scope_id=SCOPE_ID,
                pipeline_version=PIPELINE_VERSION,
                config_sha256=config_sha,
            )
        except TimeoutError:
            pass
        else:
            raise RuntimeError("manifest-DB fault was not injected")

        rows_after_crash = _manifest_rows(connection, run_id=run_id)
        keys_after_crash = _manifest_keys(store, run_id=run_id)
        created_keys.update(keys_after_crash)
        status_after_crash = _run_status(connection, run_id=run_id)

        retry = NormalizationFinalizer(
            ledger=ledger,
            object_store=store,
        ).finalize(
            plan=plan,
            run_id=run_id,
            scope_id=SCOPE_ID,
            pipeline_version=PIPELINE_VERSION,
            config_sha256=config_sha,
        )
        final_rows = _manifest_rows(connection, run_id=run_id)
        final_keys = _manifest_keys(store, run_id=run_id)

        checks = {
            "one_manifest_row_after_crash": len(rows_after_crash) == 1,
            "one_manifest_object_after_crash": len(keys_after_crash) == 1,
            "run_stayed_reconciling_after_crash": (
                status_after_crash == "reconciling"
            ),
            "retry_reused_manifest_row": (
                fault_ledger.manifest_record_id == retry.manifest_record_id
            ),
            "one_manifest_row_after_retry": len(final_rows) == 1,
            "one_manifest_object_after_retry": len(final_keys) == 1,
            "retry_closed_run": _run_status(connection, run_id=run_id) == "succeeded",
        }
        return {
            "run_id": run_id,
            "checks": checks,
            "passed": all(checks.values()),
            "manifest_record_id": retry.manifest_record_id,
            "manifest_sha256": retry.manifest_sha256,
        }
    finally:
        created_keys.update(_manifest_keys(store, run_id=run_id))
        _delete_keys(store, created_keys)


def main() -> int:
    store = build_s3_object_store()
    with psycopg.connect(_database_url(), autocommit=True) as connection:
        after_storage = _scenario_after_storage(connection, store)
        after_db = _scenario_after_db_persist(connection, store)

    payload = {
        "schema_version": 1,
        "scenarios": {
            "after_manifest_storage_before_db": after_storage,
            "after_manifest_db_before_run_close": after_db,
        },
        "passed": bool(after_storage["passed"] and after_db["passed"]),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
