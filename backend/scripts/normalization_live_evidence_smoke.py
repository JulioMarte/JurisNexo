from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg

from jurisnexo.bootstrap.settings import get_normalization_model_settings, get_openrouter_settings
from jurisnexo.model_providers.openrouter_decisions import OpenRouterDecisionProvider
from jurisnexo.normalization.contracts import FormatInspection, NormalizedDocument
from jurisnexo.normalization.decision_batching import DecisionBatchPolicy
from jurisnexo.normalization.executor import NormalizationExecutor
from jurisnexo.normalization.finalizer import NormalizationFinalizer
from jurisnexo.normalization.jev_batch_evaluator import JevBatchQualityEvaluator
from jurisnexo.normalization.model_evidence import ShadowModelEvidenceStage
from jurisnexo.normalization.model_quality import BatchedShadowTextQualityService
from jurisnexo.normalization.planner import NormalizationPlan, NormalizationPlanItem
from jurisnexo.normalization.provider_policy import ProviderPolicy
from jurisnexo.normalization.recovery import CircuitBreaker
from jurisnexo.normalization.repository import PostgresNormalizationLedger

SCOPE_ID = "00000000-0000-0000-0000-000000000001"
PIPELINE_VERSION = "live-evidence-smoke-v1"
CONFIG_SHA = hashlib.sha256(b"live-evidence-smoke-config-v1").hexdigest()
MANIFEST_SHA = hashlib.sha256(b"live-evidence-smoke-manifest-v1").hexdigest()
SOURCE_BYTES = b"%PDF-synthetic-public-normalization-evidence"
SOURCE_SHA = hashlib.sha256(SOURCE_BYTES).hexdigest()
SOURCE_TEXT = (
    "SENTENCIA SCJ-SS-22-1191. En nombre de la Republica Dominicana. "
    "CONSIDERANDO que la transcripcion contiene el numero de sentencia, "
    "la fecha 27/09/2026 y el Articulo 5 de la Ley 13-07. "
    "FALLA: Primero, acoge el recurso. Segundo, ordena la notificacion."
)
OUTPUT = Path(
    os.environ.get(
        "NORMALIZATION_LIVE_EVIDENCE_OUTPUT",
        ".artifacts/normalization-live-evidence/results.json",
    )
)
MAX_COST_USD = float(
    os.environ.get("NORMALIZATION_LIVE_EVIDENCE_MAX_COST_USD", "0.005")
)


@dataclass
class _MemoryObjectStore:
    objects: dict[str, bytes] = field(default_factory=dict)

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
                "texts": [{"text": SOURCE_TEXT}],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return NormalizedDocument(
            media_type="application/vnd.docling+json",
            payload=payload,
            engine="live-evidence-fixture-normalizer",
            engine_version="1",
            metadata={},
        )


@dataclass
class _SourceReader:
    def read(self, key: str) -> bytes:
        if key != "synthetic/live-evidence.pdf":
            raise KeyError(key)
        return SOURCE_BYTES


def _insert_source(connection: psycopg.Connection[Any]) -> str:
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (scope_id, sha256, mime_type, byte_size)
            values (%s, %s, 'application/pdf', %s)
            on conflict (scope_id, sha256) do update
                set sha256=excluded.sha256
            returning id::text
            """,
            (SCOPE_ID, SOURCE_SHA, len(SOURCE_BYTES)),
        )
        row = cursor.fetchone()
        assert row is not None
        return str(row[0])


def _evidence_snapshot(
    connection: psycopg.Connection[Any],
    *,
    run_id: str,
    source_artifact_id: str,
) -> dict[str, object]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select count(*)::int, coalesce(sum(cost_usd), 0)::text
            from corpus.normalization_model_calls
            where scope_id=%s and run_id=%s
            """,
            (SCOPE_ID, run_id),
        )
        model_row = cursor.fetchone()
        assert model_row is not None

        cursor.execute(
            """
            select count(*)::int,
                   count(*) filter (where model_call_id is not null)::int
            from corpus.normalization_observations o
            join corpus.normalization_run_items i
              on i.scope_id=o.scope_id and i.id=o.run_item_id
            where o.scope_id=%s
              and i.run_id=%s
              and o.observation_kind='text_quality_judge'
            """,
            (SCOPE_ID, run_id),
        )
        observation_row = cursor.fetchone()
        assert observation_row is not None

        cursor.execute(
            """
            select count(*)::int
            from corpus.artifact_derivations structural
            join corpus.artifact_derivations resolved
              on resolved.scope_id=structural.scope_id
             and resolved.parent_derived_artifact_id=structural.derived_artifact_id
            join corpus.derived_artifacts artifact
              on artifact.scope_id=resolved.scope_id
             and artifact.id=resolved.derived_artifact_id
            where structural.scope_id=%s
              and structural.source_artifact_id=%s
              and structural.derivation_type='normalize'
              and resolved.derivation_type='resolve_evidence_text'
              and artifact.artifact_kind='resolved-evidence-text'
            """,
            (SCOPE_ID, source_artifact_id),
        )
        lineage_row = cursor.fetchone()
        assert lineage_row is not None

        cursor.execute(
            """
            select status
            from corpus.normalization_runs
            where scope_id=%s and id=%s
            """,
            (SCOPE_ID, run_id),
        )
        run_row = cursor.fetchone()
        assert run_row is not None

        cursor.execute(
            """
            select count(*)::int
            from corpus.normalization_manifests
            where scope_id=%s and run_id=%s
            """,
            (SCOPE_ID, run_id),
        )
        manifest_row = cursor.fetchone()
        assert manifest_row is not None

    return {
        "model_call_count": int(model_row[0]),
        "observed_cost_usd": float(model_row[1]),
        "quality_observation_count": int(observation_row[0]),
        "quality_observations_with_model_call": int(observation_row[1]),
        "resolved_lineage_count": int(lineage_row[0]),
        "run_status": str(run_row[0]),
        "manifest_count": int(manifest_row[0]),
    }


def main() -> int:
    if MAX_COST_USD <= 0 or MAX_COST_USD > 0.02:
        raise ValueError("live evidence cost cap must be > 0 and <= 0.02")

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")

    openrouter = get_openrouter_settings()
    if openrouter.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    models = get_normalization_model_settings()

    provider = OpenRouterDecisionProvider(
        api_key=openrouter.api_key.get_secret_value(),
        model=models.jev_model,
    )
    store = _MemoryObjectStore()

    with psycopg.connect(database_url, autocommit=True) as connection:
        source_artifact_id = _insert_source(connection)
        ledger = PostgresNormalizationLedger(connection)
        stage = ShadowModelEvidenceStage(
            quality_service=BatchedShadowTextQualityService(
                evaluator=JevBatchQualityEvaluator(
                    provider=provider,
                    policy=DecisionBatchPolicy(),
                ),
                writer=ledger,
                provider_policy=ProviderPolicy(provider="openrouter"),
            ),
            document_class="public_judgment",
            is_public=True,
            redacted=False,
        )
        executor = NormalizationExecutor(
            inspector=_Inspector(),
            normalizer=_Normalizer(),
            source_reader=_SourceReader(),
            derived_store=store,
            ledger=ledger,
            pipeline_version=PIPELINE_VERSION,
            config_sha256=CONFIG_SHA,
            circuit_breaker=CircuitBreaker(threshold=2),
            model_evidence=stage,
        )
        plan = NormalizationPlan(
            manifest_sha256=MANIFEST_SHA,
            pipeline_version=PIPELINE_VERSION,
            config_sha256=CONFIG_SHA,
            items=(
                NormalizationPlanItem(
                    source_identifier="synthetic-live-evidence",
                    source_sha256=SOURCE_SHA,
                    object_key="synthetic/live-evidence.pdf",
                    content_type="application/pdf",
                    disposition="normalize",
                    idempotency_key=hashlib.sha256(
                        b"synthetic-live-evidence-idempotency"
                    ).hexdigest(),
                ),
            ),
        )
        execution = executor.execute(
            plan=plan,
            scope_id=SCOPE_ID,
            manifest_locator="memory://synthetic-live-evidence-manifest",
        )
        if execution.retryable_pending:
            raise RuntimeError("live provider left retryable work pending")
        finalization = NormalizationFinalizer(
            ledger=ledger,
            object_store=store,
        ).finalize(
            plan=plan,
            run_id=execution.run_id,
            scope_id=SCOPE_ID,
            pipeline_version=PIPELINE_VERSION,
            config_sha256=CONFIG_SHA,
        )
        evidence = _evidence_snapshot(
            connection,
            run_id=execution.run_id,
            source_artifact_id=source_artifact_id,
        )

    checks = {
        "model_call_persisted": evidence["model_call_count"] == 1,
        "quality_observation_persisted": evidence["quality_observation_count"] >= 1,
        "observation_linked_to_model_call": (
            evidence["quality_observations_with_model_call"] >= 1
        ),
        "resolved_evidence_has_lineage": evidence["resolved_lineage_count"] >= 1,
        "run_closed": evidence["run_status"] == "succeeded",
        "manifest_persisted": evidence["manifest_count"] == 1,
        "finalizer_succeeded": finalization.status == "succeeded",
        "cost_reported": evidence["observed_cost_usd"] > 0,
        "cost_within_cap": evidence["observed_cost_usd"] <= MAX_COST_USD,
    }
    payload = {
        "schema_version": 1,
        "provider": "openrouter",
        "requested_model": models.jev_model,
        "run_id": execution.run_id,
        "execution": {
            "normalized": execution.normalized,
            "reused": execution.reused,
            "review_required": execution.review_required,
            "failed": execution.failed,
            "retryable_pending": execution.retryable_pending,
        },
        "finalization_status": finalization.status,
        "evidence": evidence,
        "max_cost_usd": MAX_COST_USD,
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


if __name__ == "__main__":
    raise SystemExit(main())
