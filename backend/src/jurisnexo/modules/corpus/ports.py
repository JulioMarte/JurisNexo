from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from jurisnexo.modules.corpus.contracts import AnalysisObservationRecord


class AnalysisObservationStore(Protocol):
    def create_observation(
        self,
        *,
        observation_key: str,
        subject_type: str,
        case_id: UUID | None,
        proceeding_id: UUID | None,
        legal_document_id: UUID | None,
        observation_type: str,
        payload: dict[str, Any],
        evidence: list[Any],
        producer_type: str,
        producer_name: str,
        model_name: str | None,
        model_version: str | None,
        analysis_run_id: str | None,
        schema_hint: str | None,
        confidence: float | None,
    ) -> AnalysisObservationRecord: ...

    def list_observations(
        self,
        *,
        status: str | None,
        subject_type: str | None,
        observation_type: str | None,
        after_id: UUID | None,
        limit: int,
    ) -> tuple[AnalysisObservationRecord, ...]: ...

    def review_observation(
        self,
        *,
        observation_id: UUID,
        status: str,
        review_notes: str | None,
        promoted_to_schema: str | None,
    ) -> AnalysisObservationRecord: ...
