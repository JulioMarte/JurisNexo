from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from jurisnexo.modules.corpus.contracts import AnalysisObservationRecord
from jurisnexo.modules.corpus.ports import AnalysisObservationStore
from jurisnexo.platform.http.errors import ApiError
from jurisnexo.platform.http.middleware import decode_uuid_cursor, encode_uuid_cursor


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisObservationCreate(StrictModel):
    observation_key: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    subject_type: Literal["case", "proceeding", "legal_document", "corpus"]
    case_id: UUID | None = None
    proceeding_id: UUID | None = None
    legal_document_id: UUID | None = None
    observation_type: str = Field(min_length=1, max_length=160)
    payload: dict[str, Any]
    evidence: list[Any] = Field(default_factory=list)
    producer_type: Literal["llm_agent", "deterministic_tool", "human", "other"] = "llm_agent"
    producer_name: str = Field(min_length=1, max_length=200)
    model_name: str | None = Field(default=None, max_length=200)
    model_version: str | None = Field(default=None, max_length=200)
    analysis_run_id: str | None = Field(default=None, max_length=300)
    schema_hint: str | None = Field(default=None, max_length=300)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_subject(self) -> Self:
        subject_ids = {
            "case": self.case_id,
            "proceeding": self.proceeding_id,
            "legal_document": self.legal_document_id,
        }
        populated = sum(value is not None for value in subject_ids.values())
        if self.subject_type == "corpus":
            if populated != 0:
                raise ValueError("corpus observations cannot name a subject id")
            return self
        if populated != 1 or subject_ids[self.subject_type] is None:
            raise ValueError("subject_type must match exactly one subject id")
        return self


class AnalysisObservationReview(StrictModel):
    status: Literal["reviewed", "promoted", "rejected", "superseded"]
    review_notes: str | None = Field(default=None, max_length=4000)
    promoted_to_schema: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_promotion(self) -> Self:
        if self.status == "promoted" and not self.promoted_to_schema:
            raise ValueError("promoted observations require promoted_to_schema")
        if self.status != "promoted" and self.promoted_to_schema is not None:
            raise ValueError("promoted_to_schema is only valid for promoted observations")
        return self


class AnalysisObservationView(StrictModel):
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


class AnalysisObservationPage(StrictModel):
    data: list[AnalysisObservationView]
    next_cursor: str | None = None
    has_more: bool


def _view(record: AnalysisObservationRecord) -> AnalysisObservationView:
    return AnalysisObservationView(
        **{field: getattr(record, field) for field in AnalysisObservationView.model_fields}
    )


def _observation_key(body: AnalysisObservationCreate) -> str:
    if body.observation_key is not None:
        return body.observation_key
    material = {
        "subject_type": body.subject_type,
        "case_id": str(body.case_id) if body.case_id is not None else None,
        "proceeding_id": str(body.proceeding_id) if body.proceeding_id is not None else None,
        "legal_document_id": (
            str(body.legal_document_id) if body.legal_document_id is not None else None
        ),
        "observation_type": body.observation_type,
        "payload": body.payload,
        "producer_name": body.producer_name,
        "model_name": body.model_name,
        "model_version": body.model_version,
        "analysis_run_id": body.analysis_run_id,
    }
    canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def create_corpus_analysis_router(store: AnalysisObservationStore) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["corpus-analysis"])

    @router.post(
        "/analysis-observations",
        response_model=AnalysisObservationView,
        status_code=status.HTTP_201_CREATED,
        summary="Submit a quarantined analysis observation",
    )
    def create_observation(body: AnalysisObservationCreate) -> AnalysisObservationView:
        values = body.model_dump(exclude={"observation_key"})
        try:
            record = store.create_observation(
                observation_key=_observation_key(body),
                **values,
            )
        except ValueError as exc:
            if str(exc) == "analysis_observation_key_exists":
                raise ApiError(
                    status_code=409,
                    code="analysis_observation_conflict",
                    message="An observation with that stable key already exists.",
                    details={"observation_key": _observation_key(body)},
                ) from exc
            raise
        except LookupError as exc:
            raise ApiError(
                status_code=404,
                code="analysis_observation_subject_not_found",
                message="The requested observation subject does not exist in the public corpus.",
                details={"subject_type": body.subject_type},
            ) from exc
        return _view(record)

    @router.get(
        "/analysis-observations",
        response_model=AnalysisObservationPage,
        summary="List analysis observations for review",
    )
    def list_observations(
        observation_status: Literal[
            "observed", "reviewed", "promoted", "rejected", "superseded"
        ]
        | None = Query(default=None, alias="status"),
        subject_type: Literal["case", "proceeding", "legal_document", "corpus"]
        | None = None,
        observation_type: str | None = None,
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> AnalysisObservationPage:
        records = store.list_observations(
            status=observation_status,
            subject_type=subject_type,
            observation_type=observation_type,
            after_id=decode_uuid_cursor(cursor),
            limit=limit + 1,
        )
        has_more = len(records) > limit
        visible = records[:limit]
        next_cursor = None
        if has_more and visible:
            next_cursor = encode_uuid_cursor(visible[-1].id)
        return AnalysisObservationPage(
            data=[_view(record) for record in visible],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    @router.post(
        "/analysis-observations/{observation_id}:review",
        response_model=AnalysisObservationView,
        summary="Review or promote an analysis observation",
    )
    def review_observation(
        observation_id: UUID,
        body: AnalysisObservationReview,
    ) -> AnalysisObservationView:
        try:
            record = store.review_observation(
                observation_id=observation_id,
                **body.model_dump(),
            )
        except LookupError as exc:
            raise ApiError(
                status_code=404,
                code="analysis_observation_not_found",
                message="The analysis observation does not exist.",
                details={"observation_id": str(observation_id)},
            ) from exc
        return _view(record)

    return router
