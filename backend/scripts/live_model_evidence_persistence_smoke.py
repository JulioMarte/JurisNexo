from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path

import psycopg

from jurisnexo.model_providers.openrouter_decisions import OpenRouterDecisionProvider
from jurisnexo.normalization.decision_batching import DecisionBatchPolicy
from jurisnexo.normalization.jev_batch_evaluator import JevBatchQualityEvaluator
from jurisnexo.normalization.model_quality import (
    BatchedShadowTextQualityService,
    ShadowQualityCandidate,
)
from jurisnexo.normalization.provider_policy import ProviderPolicy
from jurisnexo.normalization.repository import PostgresNormalizationLedger

SCOPE_ID = "00000000-0000-0000-0000-000000000001"
PIPELINE_VERSION = "live-evidence-persistence-v1"
CONFIG_SHA = hashlib.sha256(b"live-evidence-persistence-config-v1").hexdigest()
MANIFEST_SHA = hashlib.sha256(b"live-evidence-persistence-manifest-v1").hexdigest()
TEXT = (
    "SENTENCIA SCJ-SS-22-1191. En nombre de la República Dominicana. "
    "Vistos los artículos 5 y 13 de la Ley 13-07. Considerando que el "
    "texto de esta prueba es sintético y no contiene información privada. "
    "FALLA: Primero, rechaza el recurso. Segundo, ordena la notificación."
)
OUTPUT = Path(
    os.environ.get(
        "LIVE_MODEL_EVIDENCE_OUTPUT",
        ".artifacts/live-model-evidence-persistence",
    )
)
MAX_COST_USD = Decimal(
    os.environ.get("LIVE_MODEL_EVIDENCE_MAX_COST_USD", "0.005")
)


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value


def _api_key() -> str:
    value = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not value:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    return value


def _model() -> str:
    return os.environ.get(
        "JURISNEXO_OPENROUTER_JEV_MODEL",
        "~typesafe/jev-latest",
    ).strip()


def _source_sha() -> str:
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    return hashlib.sha256(
        f"live-model-evidence:{run_id}:{attempt}".encode("utf-8")
    ).hexdigest()


def _insert_source(connection: psycopg.Connection[object], source_sha: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (scope_id, sha256, mime_type, byte_size)
            values (%s, %s, 'application/pdf', %s)
            returning id::text
            """,
            (SCOPE_ID, source_sha, len(TEXT.encode("utf-8"))),
        )
        row = cursor.fetchone()
        assert row is not None
        return str(row[0])


def _persist_fixture_artifacts(
    ledger: PostgresNormalizationLedger,
    *,
    source_artifact_id: str,
    run_item_id: str,
) -> tuple[str, str]:
    structural_payload = json.dumps(
        {"texts": [{"text": TEXT}]},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    structural_sha = hashlib.sha256(structural_payload).hexdigest()
    structural_id = ledger.register_derived_artifact(
        scope_id=SCOPE_ID,
        source_artifact_id=source_artifact_id,
        sha256=structural_sha,
        artifact_kind="docling-json",
        mime_type="application/json",
        byte_size=len(structural_payload),
        storage_locator=f"ci://live-evidence/{structural_sha}.json",
        engine="synthetic-fixture",
        engine_version="1",
        pipeline_version=PIPELINE_VERSION,
        config_sha256=CONFIG_SHA,
        parameters={"purpose": "live_model_evidence_persistence"},
    )

    resolved_payload = TEXT.encode("utf-8")
    resolved_sha = hashlib.sha256(resolved_payload).hexdigest()
    resolved_id = ledger.register_child_derived_artifact(
        scope_id=SCOPE_ID,
        parent_artifact_id=structural_id,
        sha256=resolved_sha,
        artifact_kind="resolved-evidence-text",
        mime_type="text/plain; charset=utf-8",
        byte_size=len(resolved_payload),
        storage_locator=f"ci://live-evidence/{resolved_sha}.txt",
        engine="jurisnexo-resolver",
        engine_version=None,
        pipeline_version=PIPELINE_VERSION,
        config_sha256=CONFIG_SHA,
        derivation_type="resolve_evidence_text",
        parameters={"policy": "synthetic-live-persistence-proof"},
    )
    ledger.record_observation(
        scope_id=SCOPE_ID,
        run_item_id=run_item_id,
        artifact_id=structural_id,
        observation_kind="deterministic_qa",
        payload={"risk_flags": [], "synthetic_fixture": True},
        status="accepted",
    )
    return structural_id, resolved_id


def main() -> int:
    if MAX_COST_USD <= 0 or MAX_COST_USD > Decimal("0.01"):
        raise ValueError("LIVE_MODEL_EVIDENCE_MAX_COST_USD must be > 0 and <= 0.01")

    database_url = _database_url()
    provider = OpenRouterDecisionProvider(
        api_key=_api_key(),
        model=_model(),
    )
    source_sha = _source_sha()

    with psycopg.connect(database_url, autocommit=True) as connection:
        source_artifact_id = _insert_source(connection, source_sha)
        ledger = PostgresNormalizationLedger(connection)
        run_id = ledger.create_run(
            scope_id=SCOPE_ID,
            manifest_locator="ci://live-evidence/manifest.json",
            manifest_sha256=MANIFEST_SHA,
            pipeline_version=PIPELINE_VERSION,
            config_sha256=CONFIG_SHA,
            selected_count=1,
        )
        item_id = ledger.ensure_item(
            scope_id=SCOPE_ID,
            run_id=run_id,
            source_artifact_id=source_artifact_id,
        )
        ledger.mark_running(scope_id=SCOPE_ID, item_id=item_id)
        structural_id, resolved_id = _persist_fixture_artifacts(
            ledger,
            source_artifact_id=source_artifact_id,
            run_item_id=item_id,
        )

        service = BatchedShadowTextQualityService(
            evaluator=JevBatchQualityEvaluator(
                provider=provider,
                policy=DecisionBatchPolicy(),
            ),
            writer=ledger,
            provider_policy=ProviderPolicy(
                provider="openrouter",
                allow_private_documents=False,
            ),
        )
        observation_ids = service.evaluate_many(
            scope_id=SCOPE_ID,
            run_id=run_id,
            candidates=(
                ShadowQualityCandidate(
                    run_item_id=item_id,
                    artifact_id=resolved_id,
                    text=TEXT,
                    context={"source": "synthetic_ci_fixture"},
                    document_class="public_judgment",
                    is_public=True,
                    redacted=False,
                ),
            ),
        )
        if len(observation_ids) != 1:
            raise RuntimeError("expected one durable JEV quality observation")
        ledger.mark_normalized(
            scope_id=SCOPE_ID,
            item_id=item_id,
            normalized_artifact_id=resolved_id,
        )
        ledger.mark_reconciling(scope_id=SCOPE_ID, run_id=run_id)

    with psycopg.connect(database_url, autocommit=True) as verification:
        with verification.cursor() as cursor:
            cursor.execute(
                """
                select provider, model, cost_usd, response_id,
                       input_tokens, total_tokens
                from corpus.normalization_model_calls
                where scope_id=%s and run_id=%s
                  and purpose='text_quality_judge'
                order by created_at desc
                limit 1
                """,
                (SCOPE_ID, run_id),
            )
            model_call = cursor.fetchone()
            if model_call is None:
                raise RuntimeError("live model call was not persisted")
            cost = Decimal(str(model_call[2] or 0))
            if cost > MAX_COST_USD:
                raise RuntimeError(
                    f"live model evidence cost USD {cost} exceeded cap USD {MAX_COST_USD}"
                )

            cursor.execute(
                """
                select o.id::text, o.status, o.model_call_id::text,
                       o.artifact_id::text, o.payload->>'mode',
                       o.payload->>'recommended_action'
                from corpus.normalization_observations o
                where o.scope_id=%s and o.run_item_id=%s
                  and o.observation_kind='text_quality_judge'
                """,
                (SCOPE_ID, item_id),
            )
            observation = cursor.fetchone()
            if observation is None:
                raise RuntimeError("live model observation was not persisted")
            if observation[1] != "candidate" or observation[2] is None:
                raise RuntimeError("live model observation lost model-call lineage")
            if str(observation[3]) != resolved_id:
                raise RuntimeError("live observation is not attached to resolved evidence")

            cursor.execute(
                """
                select count(*)
                from corpus.artifact_derivations
                where scope_id=%s
                  and parent_derived_artifact_id=%s
                  and derived_artifact_id=%s
                  and derivation_type='resolve_evidence_text'
                """,
                (SCOPE_ID, structural_id, resolved_id),
            )
            lineage_row = cursor.fetchone()
            assert lineage_row is not None
            if int(lineage_row[0]) != 1:
                raise RuntimeError("resolved evidence lineage was not persisted")

            immutable = False
            try:
                cursor.execute(
                    """
                    update corpus.normalization_observations
                    set status='accepted'
                    where id=%s
                    """,
                    (observation[0],),
                )
            except psycopg.Error:
                immutable = True
            if not immutable:
                raise RuntimeError("normalization observation unexpectedly mutable")

            report = {
                "run_id": run_id,
                "source_sha256": source_sha,
                "structural_artifact_id": structural_id,
                "resolved_artifact_id": resolved_id,
                "observation_id": str(observation[0]),
                "provider": str(model_call[0]),
                "model": str(model_call[1]),
                "response_id": str(model_call[3] or ""),
                "input_tokens": model_call[4],
                "total_tokens": model_call[5],
                "cost_usd": float(cost),
                "mode": str(observation[4] or ""),
                "recommended_action": str(observation[5] or ""),
                "durable_after_reconnect": True,
                "lineage_persisted": True,
                "observation_immutable": True,
                "runtime_policy": "shadow",
            }

    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
