from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AnalysisObservationRecord:
    id: UUID
    observation_key: str
    subject_type: str
    case_id: UUID | None
    proceeding_id: UUID | None
    legal_document_id: UUID | None
    observation_type: str
    payload: dict[str, Any]
    evidence: list[Any]
    producer_type: str
    producer_name: str
    model_name: str | None
    model_version: str | None
    analysis_run_id: str | None
    schema_hint: str | None
    confidence: float | None
    status: str
    review_notes: str | None
    promoted_to_schema: str | None
    created_at: datetime
    reviewed_at: datetime | None
