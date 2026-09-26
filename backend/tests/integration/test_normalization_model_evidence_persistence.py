from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import psycopg
import pytest

from jurisnexo.model_providers.contracts import (
    JsonObject,
    ModelUsage,
    StructuredGenerationResult,
)
from jurisnexo.model_providers.decisions import (
    DecisionQuestion,
    DecisionResult,
    DecisionUsage,
)
from jurisnexo.normalization.contracts import (
    FormatInspection,
    NormalizedDocument,
)
from jurisnexo.normalization.decision_batching import DecisionBatchPolicy
from jurisnexo.normalization.executor import NormalizationExecutor
from jurisnexo.normalization.jev_batch_evaluator import JevBatchQualityEvaluator
from jurisnexo.normalization.model_evidence import ShadowModelEvidenceStage
from jurisnexo.normalization.model_quality import (
    BatchedShadowTextQualityService,
    SelectiveVisualVerificationService,
)
from jurisnexo.normalization.planner import (
    NormalizationPlan,
    NormalizationPlanItem,
)
from jurisnexo.normalization.provider_policy import ProviderPolicy
from jurisnexo.normalization.recovery import CircuitBreaker
from jurisnexo.normalization.repository import PostgresNormalizationLedger

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.provenance,
]

SCOPE_ID = "00000000-0000-0000-0000-000000000001"
PIPELINE_VERSION = "v1"
CONFIG_SHA = "c" * 64
SOURCE_SHA = "a" * 64
MANIFEST_SHA = "d" * 64
SOURCE_TEXT = "SENTENCIA DEL 27 DE SEPTIEMBRE. CONSIDERANDO que procede. FALLA."


@dataclass
class _FakeDecisionProvider:
    calls: int = 0

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-jev"

    def decide(
        self,
        *,
        state_description: str,
        records: tuple[dict[str, str], ...],
        questions: dict[str, DecisionQuestion],
    ) -> DecisionResult:
        del state_description
        self.calls += 1
        answers: dict[str, JsonObject] = {}
        for record in records:
            record_id = record["id"]
            answers[f"{record_id}__transcription_quality"] = {
                "type": "choice",
                "choice": "acceptable",
                "confidence": 0.96,
                "probabilities": {
                    "acceptable": 0.96,
                    "material_error": 0.02,
                    "uncertain": 0.02,
                },
            }
            answers[f"{record_id}__legal_critical_damage"] = {
                "type": "noul",
                "noul": 0.05,
            }
            answers[f"{record_id}__needs_visual_review"] = {
                "type": "noul",
                "noul": 0.05,
            }
        assert set(questions) == set(answers)
        return DecisionResult(
            answers=answers,
            provider="fake",
            model="fake-jev",
            model_version="fake-jev-v1",
            response_id=f"response-{self.calls}",
            usage=DecisionUsage(
                input_tokens=100 * len(records),
                output_tokens=0,
                total_tokens=100 * len(records),
            ),
            cost_usd=0.0001 * len(records),
        )


@dataclass
class _FakeVisualProvider:
    def verify_image_text(
        self,
        *,
        image: bytes,
        media_type: str,
        prompt: str,
        json_schema: JsonObject,
        max_output_tokens: int,
    ) -> StructuredGenerationResult:
        del image, media_type, prompt, json_schema, max_output_tokens
        return StructuredGenerationResult(
            value={
                "matches": False,
                "corrected_text": "SENTENCIA DEL 27 DE SEPTIEMBRE. CONSIDERANDO que procede.",
                "material_differences": ["missing FALLA clause"],
            },
            provider="fake",
            model="fake-visual",
            model_version="fake-visual-v1",
            response_id="visual-response-1",
            usage=ModelUsage(input_tokens=50, output_tokens=10, total_tokens=60),
            cost_usd=0.0002,
        )


@dataclass
class _MemoryObjectStore:
    objects: dict[str, bytes] = field(default_factory=lambda: {})

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
        self.objects[key] = content


@dataclass
class _FakeInspector:
    def inspect(
        self, source: bytes, *, filename: str | None = None
    ) -> FormatInspection:
        del source, filename
        return FormatInspection(
            media_type="application/pdf",
            detected_format="application/pdf",
            metadata={},
        )


@dataclass
class _FakeNormalizer:
    def normalize(
        self,
        source: bytes,
        inspection: FormatInspection,
        *,
        filename: str | None = None,
    ) -> NormalizedDocument:
        del source, inspection, filename
        payload = (
            '{"body":{"children":[{"$ref":"#/texts/0"}]},'
            '"texts":[{"text":"' + SOURCE_TEXT + '"}]}'
        ).encode("utf-8")
        return NormalizedDocument(
            media_type="application/json",
            payload=payload,
            engine="fake-docling",
            engine_version="1.0",
            metadata={},
        )


@dataclass
class _FakeSourceReader:
    def read(self, key: str) -> bytes:
        del key
        return b"PK\x03\x04 official source bytes"


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def test_live_model_evidence_is_persisted_through_supported_path(
    connection: psycopg.Connection[Any],
) -> None:
    store = _MemoryObjectStore()
    decision_provider = _FakeDecisionProvider()
    ledger = PostgresNormalizationLedger(connection)
    policy = ProviderPolicy(provider="fake")
    stage = ShadowModelEvidenceStage(
        quality_service=BatchedShadowTextQualityService(
            evaluator=JevBatchQualityEvaluator(
                provider=decision_provider,
                policy=DecisionBatchPolicy(),
            ),
            writer=ledger,
            provider_policy=policy,
        ),
        visual_service=SelectiveVisualVerificationService(
            provider=_FakeVisualProvider(),
            observation_writer=ledger,
            correction_writer=ledger,
            provider_policy=policy,
        ),
        document_class="public_judgment",
        is_public=True,
        redacted=False,
    )
    executor = NormalizationExecutor(
        inspector=_FakeInspector(),
        normalizer=_FakeNormalizer(),
        source_reader=_FakeSourceReader(),
        derived_store=store,
        ledger=ledger,
        pipeline_version=PIPELINE_VERSION,
        config_sha256=CONFIG_SHA,
        circuit_breaker=CircuitBreaker(),
        model_evidence=stage,
    )
    plan = NormalizationPlan(
        manifest_sha256=MANIFEST_SHA,
        pipeline_version=PIPELINE_VERSION,
        config_sha256=CONFIG_SHA,
        items=(
            NormalizationPlanItem(
                source_identifier="principales-fixture",
                source_sha256=SOURCE_SHA,
                object_key="official/source.pdf",
                content_type="application/pdf",
                disposition="normalize",
                idempotency_key="e" * 64,
            ),
        ),
    )

    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts
                (scope_id, sha256, mime_type, byte_size)
            values (%s, %s, 'application/pdf', 5)
            returning id::text
            """,
            (SCOPE_ID, SOURCE_SHA),
        )
        source_row = cursor.fetchone()
        assert source_row is not None
        source_artifact_id = str(source_row[0])

        result = executor.execute(
            plan=plan,
            scope_id=SCOPE_ID,
            manifest_locator="s3://fixture/normalization-plan.json",
        )
        assert result.normalized == 1
        assert result.failed == 0

        cursor.execute(
            """
            select id::text
            from corpus.normalization_run_items
            where scope_id=%s and source_artifact_id=%s
            """,
            (SCOPE_ID, source_artifact_id),
        )
        item_row = cursor.fetchone()
        assert item_row is not None
        item_id = str(item_row[0])

        cursor.execute(
            """
            select id::text, artifact_id::text
            from corpus.normalization_observations
            where scope_id=%s and run_item_id=%s
              and observation_kind='text_quality_judge'
            """,
            (SCOPE_ID, item_id),
        )
        quality_row = cursor.fetchone()
        assert quality_row is not None
        quality_observation_id, quality_artifact_id = (
            str(quality_row[0]),
            str(quality_row[1]),
        )

        cursor.execute(
            """
            select status, model_call_id is not null,
                   payload->>'mode', payload->>'recommended_action'
            from corpus.normalization_observations
            where id=%s
            """,
            (quality_observation_id,),
        )
        quality_state = cursor.fetchone()
        assert quality_state is not None
        assert quality_state[0] == "candidate"
        assert quality_state[1] is True
        assert quality_state[2] == "shadow"
        assert quality_state[3] is not None

        visual_capture = stage.capture_visual(
            scope_id=SCOPE_ID,
            run_id=result.run_id,
            run_item_id=item_id,
            artifact_id=quality_artifact_id,
            source_observation_id=quality_observation_id,
            image=b"page-image",
            media_type="image/png",
            candidate_text=SOURCE_TEXT,
        )
        assert visual_capture.visual_observation_id is not None
        assert visual_capture.correction_id is not None

        cursor.execute(
            """
            select observation_kind, status, model_call_id is not null
            from corpus.normalization_observations
            where id=%s
            """,
            (visual_capture.visual_observation_id,),
        )
        visual_state = cursor.fetchone()
        assert visual_state == ("visual_verification", "candidate", True)

        cursor.execute(
            """
            select observation_id::text, verifier_observation_id::text,
                   status, replacement_text
            from corpus.normalization_corrections
            where id=%s
            """,
            (visual_capture.correction_id,),
        )
        correction_row = cursor.fetchone()
        assert correction_row is not None
        assert correction_row[0] == quality_observation_id
        assert correction_row[1] == visual_capture.visual_observation_id
        assert correction_row[2] == "proposed"
        assert correction_row[3]

        cursor.execute(
            """
            select count(*)
            from corpus.normalization_corrections
            where scope_id=%s and observation_id=%s and status='accepted'
            """,
            (SCOPE_ID, quality_observation_id),
        )
        accepted_row = cursor.fetchone()
        assert accepted_row == (0,)

        cursor.execute(
            """
            select purpose, count(*)
            from corpus.normalization_model_calls
            where scope_id=%s
            group by purpose
            order by purpose
            """,
            (SCOPE_ID,),
        )
        purposes = dict(cursor.fetchall())
        assert purposes["text_quality_judge"] >= 1
        assert purposes["visual_verification"] >= 1
