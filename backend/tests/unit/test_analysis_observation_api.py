from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jurisnexo.modules.corpus.api.router import create_corpus_analysis_router
from jurisnexo.modules.corpus.contracts import AnalysisObservationRecord

pytestmark = pytest.mark.unit


class FakeObservationStore:
    def __init__(self) -> None:
        self.records: dict[UUID, AnalysisObservationRecord] = {}

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
    ) -> AnalysisObservationRecord:
        now = datetime.now(UTC)
        record = AnalysisObservationRecord(
            id=uuid4(),
            observation_key=observation_key,
            subject_type=subject_type,
            case_id=case_id,
            proceeding_id=proceeding_id,
            legal_document_id=legal_document_id,
            observation_type=observation_type,
            payload=payload,
            evidence=evidence,
            producer_type=producer_type,
            producer_name=producer_name,
            model_name=model_name,
            model_version=model_version,
            analysis_run_id=analysis_run_id,
            schema_hint=schema_hint,
            confidence=confidence,
            status="observed",
            review_notes=None,
            promoted_to_schema=None,
            created_at=now,
            reviewed_at=None,
        )
        self.records[record.id] = record
        return record

    def list_observations(
        self,
        *,
        status: str | None,
        subject_type: str | None,
        observation_type: str | None,
        after_id: UUID | None,
        limit: int,
    ) -> tuple[AnalysisObservationRecord, ...]:
        records = sorted(self.records.values(), key=lambda record: record.id.int)
        return tuple(
            record
            for record in records
            if (status is None or record.status == status)
            and (subject_type is None or record.subject_type == subject_type)
            and (observation_type is None or record.observation_type == observation_type)
            and (after_id is None or record.id.int > after_id.int)
        )[:limit]

    def review_observation(
        self,
        *,
        observation_id: UUID,
        status: str,
        review_notes: str | None,
        promoted_to_schema: str | None,
    ) -> AnalysisObservationRecord:
        current = self.records[observation_id]
        updated = AnalysisObservationRecord(
            id=current.id,
            observation_key=current.observation_key,
            subject_type=current.subject_type,
            case_id=current.case_id,
            proceeding_id=current.proceeding_id,
            legal_document_id=current.legal_document_id,
            observation_type=current.observation_type,
            payload=current.payload,
            evidence=current.evidence,
            producer_type=current.producer_type,
            producer_name=current.producer_name,
            model_name=current.model_name,
            model_version=current.model_version,
            analysis_run_id=current.analysis_run_id,
            schema_hint=current.schema_hint,
            confidence=current.confidence,
            status=status,
            review_notes=review_notes,
            promoted_to_schema=promoted_to_schema,
            created_at=current.created_at,
            reviewed_at=datetime.now(UTC),
        )
        self.records[observation_id] = updated
        return updated


def _client(store: FakeObservationStore) -> TestClient:
    app = FastAPI()
    app.include_router(create_corpus_analysis_router(store))
    return TestClient(app)


def test_llm_can_submit_unmodeled_json_and_it_stays_observed() -> None:
    store = FakeObservationStore()
    case_id = uuid4()
    payload = {
        "new_dimension": "burden_shift_sequence",
        "steps": ["initial proof", "burden shift", "rebuttal"],
        "worth_formalizing": True,
    }

    with _client(store) as client:
        response = client.post(
            "/v1/analysis-observations",
            json={
                "subject_type": "case",
                "case_id": str(case_id),
                "observation_type": "unmodeled_legal_pattern",
                "payload": payload,
                "evidence": [{"page": 7, "excerpt": "texto"}],
                "producer_name": "deep-case-analysis",
                "model_name": "test-model",
                "analysis_run_id": "run-42",
                "schema_hint": "candidate:burden_shift_sequence",
                "confidence": 0.78,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "observed"
    assert body["payload"] == payload
    assert body["promoted_to_schema"] is None
    assert len(body["observation_key"]) == 64


def test_promotion_requires_named_canonical_destination() -> None:
    store = FakeObservationStore()
    with _client(store) as client:
        created = client.post(
            "/v1/analysis-observations",
            json={
                "subject_type": "corpus",
                "observation_type": "candidate_taxonomy",
                "payload": {"name": "new_concept"},
                "producer_name": "taxonomy-agent",
            },
        )
        observation_id = created.json()["id"]
        invalid = client.post(
            f"/v1/analysis-observations/{observation_id}:review",
            json={"status": "promoted"},
        )
        valid = client.post(
            f"/v1/analysis-observations/{observation_id}:review",
            json={
                "status": "promoted",
                "review_notes": "Formalized after review",
                "promoted_to_schema": "corpus.legal_matter_concepts",
            },
        )

    assert invalid.status_code == 422
    assert valid.status_code == 200
    assert valid.json()["status"] == "promoted"
    assert valid.json()["promoted_to_schema"] == "corpus.legal_matter_concepts"
