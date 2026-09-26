from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.model_providers.contracts import ModelProviderError
from jurisnexo.normalization.jev_quality import JevRoutingPolicy
from jurisnexo.normalization.model_quality import (
    BatchedShadowTextQualityService,
    SelectiveVisualVerificationService,
    ShadowQualityCandidate,
)


@dataclass(frozen=True, slots=True)
class ModelEvidenceCapture:
    quality_observation_ids: tuple[str, ...] = ()
    visual_observation_id: str | None = None
    correction_id: str | None = None


@dataclass(slots=True)
class ShadowModelEvidenceStage:
    """Supported shadow stage that persists JEV/visual evidence through the ledger.

    Code owns persistence and authority. JEV and the visual verifier only produce
    candidate observations; corrections are proposed and never silently accepted.
    Text-quality evaluation runs where normalized text exists; visual verification
    runs only where the page image exists.
    """

    quality_service: BatchedShadowTextQualityService
    visual_service: SelectiveVisualVerificationService | None = None
    routing_policy: JevRoutingPolicy = JevRoutingPolicy()
    document_class: str = "public_judgment"
    is_public: bool = True
    redacted: bool = False

    def capture_text_quality(
        self,
        *,
        scope_id: str,
        run_id: str,
        run_item_id: str,
        artifact_id: str,
        text: str,
        context: dict[str, object],
    ) -> ModelEvidenceCapture:
        candidate = ShadowQualityCandidate(
            run_item_id=run_item_id,
            artifact_id=artifact_id,
            text=text,
            context=dict(context),
            document_class=self.document_class,
            is_public=self.is_public,
            redacted=self.redacted,
        )
        try:
            observation_ids = self.quality_service.evaluate_many(
                scope_id=scope_id,
                run_id=run_id,
                candidates=(candidate,),
            )
        except ModelProviderError as exc:
            self.quality_service.writer.record_observation(
                scope_id=scope_id,
                run_item_id=run_item_id,
                artifact_id=artifact_id,
                observation_kind="text_quality_judge",
                payload={"error": str(exc), "mode": "shadow"},
                status="unresolved",
            )
            return ModelEvidenceCapture()
        return ModelEvidenceCapture(quality_observation_ids=tuple(observation_ids))

    def capture_visual(
        self,
        *,
        scope_id: str,
        run_id: str,
        run_item_id: str,
        artifact_id: str,
        source_observation_id: str,
        image: bytes,
        media_type: str,
        candidate_text: str,
    ) -> ModelEvidenceCapture:
        if self.visual_service is None:
            raise RuntimeError("visual verification service is not configured")
        try:
            observation_id, correction_id = self.visual_service.verify(
                scope_id=scope_id,
                run_id=run_id,
                run_item_id=run_item_id,
                artifact_id=artifact_id,
                source_observation_id=source_observation_id,
                image=image,
                media_type=media_type,
                candidate_text=candidate_text,
                document_class=self.document_class,
                is_public=self.is_public,
                redacted=self.redacted,
            )
        except ModelProviderError as exc:
            self.visual_service.observation_writer.record_observation(
                scope_id=scope_id,
                run_item_id=run_item_id,
                artifact_id=artifact_id,
                observation_kind="visual_verification",
                payload={
                    "error": str(exc),
                    "source_observation_id": source_observation_id,
                    "mode": "selective_visual",
                },
                status="unresolved",
            )
            return ModelEvidenceCapture()
        return ModelEvidenceCapture(
            visual_observation_id=observation_id,
            correction_id=correction_id,
        )
