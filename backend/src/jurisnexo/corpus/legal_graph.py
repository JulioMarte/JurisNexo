from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

import psycopg

RelationType = Literal[
    "cites",
    "references",
    "interprets",
    "applies",
    "declines_to_apply",
    "follows",
    "distinguishes",
    "overrules",
    "authorized_by",
    "implements",
    "amends",
    "repeals",
    "partially_repeals",
    "supersedes",
    "conflicts_with",
    "consistent_with",
    "requires",
    "satisfies",
    "exempts_from",
]

AssertionMethod = Literal[
    "explicit_primary_text",
    "official_metadata",
    "deterministic_reference",
    "llm_extracted",
    "human_verified",
]

RequirementSourceRole = Literal[
    "establishes",
    "defines",
    "amends",
    "repeals",
    "creates_exception",
    "interprets",
    "satisfies",
    "evidences",
]


@dataclass(frozen=True, slots=True)
class ProvisionInput:
    document_id: UUID
    provision_type: str
    label: str | None = None
    normalized_label: str | None = None
    parent_provision_id: UUID | None = None
    ordinal: int | None = None
    heading: str | None = None
    text: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None


@dataclass(frozen=True, slots=True)
class RelationObservationInput:
    source_document_id: UUID
    relation_type: RelationType
    method_name: str
    assertion_method: AssertionMethod
    source_provision_id: UUID | None = None
    target_document_id: UUID | None = None
    target_provision_id: UUID | None = None
    raw_target_citation: str | None = None
    ingestion_job_id: UUID | None = None
    confidence: float | None = None
    evidence_artifact_page_id: UUID | None = None
    evidence_excerpt: str | None = None
    evidence_char_start: int | None = None
    evidence_char_end: int | None = None


@dataclass(frozen=True, slots=True)
class LegalRelationRecord:
    id: UUID
    source_document_id: UUID
    source_provision_id: UUID | None
    relation_type: str
    target_document_id: UUID
    target_provision_id: UUID | None
    status: str
    verification_method: str


@dataclass(frozen=True, slots=True)
class RequirementInput:
    jurisdiction_code: str
    requirement_type: str
    canonical_text: str
    scope_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    status: str = "active"
    effective_from: date | None = None
    effective_to: date | None = None


def relation_observation_key(observation: RelationObservationInput) -> str:
    """Create a stable idempotency key from semantically relevant observation fields."""

    payload = {
        "source_document_id": str(observation.source_document_id),
        "source_provision_id": (
            str(observation.source_provision_id) if observation.source_provision_id else None
        ),
        "relation_type": observation.relation_type,
        "target_document_id": (
            str(observation.target_document_id) if observation.target_document_id else None
        ),
        "target_provision_id": (
            str(observation.target_provision_id) if observation.target_provision_id else None
        ),
        "raw_target_citation": observation.raw_target_citation,
        "assertion_method": observation.assertion_method,
        "method_name": observation.method_name,
        "evidence_artifact_page_id": (
            str(observation.evidence_artifact_page_id)
            if observation.evidence_artifact_page_id
            else None
        ),
        "evidence_char_start": observation.evidence_char_start,
        "evidence_char_end": observation.evidence_char_end,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class PostgresLegalGraphRepository:
    """Deterministic persistence boundary for provisions, relations, and requirements.

    Agents may propose observations through a narrow application tool, but canonical
    relations are promoted separately so model output is never canonical merely by
    being emitted.
    """

    connection: psycopg.Connection[Any]

    def upsert_provision(self, provision: ProvisionInput) -> UUID:
        if provision.normalized_label is None:
            return self._insert_unlabelled_provision(provision)

        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.legal_document_provisions (
                    document_id, parent_provision_id, provision_type, label,
                    normalized_label, ordinal, heading, text, effective_from, effective_to
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (document_id, normalized_label)
                    where normalized_label is not null
                do update set
                    parent_provision_id = excluded.parent_provision_id,
                    provision_type = excluded.provision_type,
                    label = excluded.label,
                    ordinal = excluded.ordinal,
                    heading = excluded.heading,
                    text = excluded.text,
                    effective_from = excluded.effective_from,
                    effective_to = excluded.effective_to,
                    updated_at = now()
                returning id
                """,
                (
                    provision.document_id,
                    provision.parent_provision_id,
                    provision.provision_type,
                    provision.label,
                    provision.normalized_label,
                    provision.ordinal,
                    provision.heading,
                    provision.text,
                    provision.effective_from,
                    provision.effective_to,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("provision upsert did not return an identifier")
            return row[0]

    def _insert_unlabelled_provision(self, provision: ProvisionInput) -> UUID:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.legal_document_provisions (
                    document_id, parent_provision_id, provision_type, label,
                    ordinal, heading, text, effective_from, effective_to
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning id
                """,
                (
                    provision.document_id,
                    provision.parent_provision_id,
                    provision.provision_type,
                    provision.label,
                    provision.ordinal,
                    provision.heading,
                    provision.text,
                    provision.effective_from,
                    provision.effective_to,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("provision insert did not return an identifier")
            return row[0]

    def record_relation_observation(self, observation: RelationObservationInput) -> UUID:
        key = relation_observation_key(observation)
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.legal_relation_observations (
                    ingestion_job_id, observation_key,
                    source_document_id, source_provision_id, relation_type,
                    target_document_id, target_provision_id, raw_target_citation,
                    assertion_method, method_name, confidence,
                    evidence_artifact_page_id, evidence_excerpt,
                    evidence_char_start, evidence_char_end
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (observation_key) do update set
                    confidence = excluded.confidence,
                    evidence_excerpt = coalesce(
                        excluded.evidence_excerpt,
                        corpus.legal_relation_observations.evidence_excerpt
                    )
                returning id
                """,
                (
                    observation.ingestion_job_id,
                    key,
                    observation.source_document_id,
                    observation.source_provision_id,
                    observation.relation_type,
                    observation.target_document_id,
                    observation.target_provision_id,
                    observation.raw_target_citation,
                    observation.assertion_method,
                    observation.method_name,
                    observation.confidence,
                    observation.evidence_artifact_page_id,
                    observation.evidence_excerpt,
                    observation.evidence_char_start,
                    observation.evidence_char_end,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("relation observation upsert did not return an identifier")
            return row[0]

    def promote_relation(self, observation_id: UUID, *, verification_method: str) -> UUID:
        """Promote a resolved observation to a canonical relation and preserve evidence."""

        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                select source_document_id, source_provision_id, relation_type,
                       target_document_id, target_provision_id,
                       evidence_artifact_page_id, evidence_excerpt,
                       evidence_char_start, evidence_char_end,
                       assertion_method, status
                from corpus.legal_relation_observations
                where id = %s
                for update
                """,
                (observation_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError(f"unknown relation observation: {observation_id}")
            (
                source_document_id,
                source_provision_id,
                relation_type,
                target_document_id,
                target_provision_id,
                evidence_page_id,
                evidence_excerpt,
                evidence_char_start,
                evidence_char_end,
                assertion_method,
                observation_status,
            ) = row
            if target_document_id is None:
                raise ValueError("cannot promote an unresolved target citation")
            if observation_status in {"rejected", "superseded"}:
                raise ValueError(f"cannot promote observation in state {observation_status}")

            cursor.execute(
                """
                insert into corpus.legal_relations (
                    source_document_id, source_provision_id, relation_type,
                    target_document_id, target_provision_id,
                    verification_method, promoted_from_observation_id
                )
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict do nothing
                returning id
                """,
                (
                    source_document_id,
                    source_provision_id,
                    relation_type,
                    target_document_id,
                    target_provision_id,
                    verification_method,
                    observation_id,
                ),
            )
            inserted = cursor.fetchone()
            if inserted is not None:
                relation_id: UUID = inserted[0]
            else:
                cursor.execute(
                    """
                    select id
                    from corpus.legal_relations
                    where source_document_id = %s
                      and source_provision_id is not distinct from %s
                      and relation_type = %s
                      and target_document_id = %s
                      and target_provision_id is not distinct from %s
                    """,
                    (
                        source_document_id,
                        source_provision_id,
                        relation_type,
                        target_document_id,
                        target_provision_id,
                    ),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise RuntimeError("relation conflict occurred but canonical row was not found")
                relation_id = existing[0]

            cursor.execute(
                "update corpus.legal_relation_observations set status = 'accepted' where id = %s",
                (observation_id,),
            )
            if evidence_page_id is not None:
                evidence_kind = {
                    "official_metadata": "official_metadata",
                    "deterministic_reference": "deterministic_match",
                    "human_verified": "manual_review",
                }.get(assertion_method, "primary_text")
                cursor.execute(
                    """
                    insert into corpus.legal_relation_evidence (
                        relation_id, observation_id, artifact_page_id, evidence_kind,
                        evidence_excerpt, evidence_char_start, evidence_char_end
                    )
                    select %s, %s, %s, %s, %s, %s, %s
                    where not exists (
                        select 1 from corpus.legal_relation_evidence
                        where relation_id = %s and observation_id = %s
                    )
                    """,
                    (
                        relation_id,
                        observation_id,
                        evidence_page_id,
                        evidence_kind,
                        evidence_excerpt,
                        evidence_char_start,
                        evidence_char_end,
                        relation_id,
                        observation_id,
                    ),
                )
            return relation_id

    def create_requirement(self, requirement: RequirementInput) -> UUID:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.legal_requirements (
                    scope_id, jurisdiction_code, requirement_type, canonical_text,
                    status, effective_from, effective_to
                )
                values (%s, %s, %s, %s, %s, %s, %s)
                returning id
                """,
                (
                    requirement.scope_id,
                    requirement.jurisdiction_code,
                    requirement.requirement_type,
                    requirement.canonical_text,
                    requirement.status,
                    requirement.effective_from,
                    requirement.effective_to,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("requirement insert did not return an identifier")
            return row[0]

    def attach_requirement_source(
        self,
        *,
        requirement_id: UUID,
        document_id: UUID,
        source_role: RequirementSourceRole,
        verification_method: str,
        provision_id: UUID | None = None,
        verification_status: str = "candidate",
        evidence_artifact_page_id: UUID | None = None,
        evidence_excerpt: str | None = None,
    ) -> UUID:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.legal_requirement_sources (
                    requirement_id, document_id, provision_id, source_role,
                    verification_status, verification_method,
                    evidence_artifact_page_id, evidence_excerpt
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                returning id
                """,
                (
                    requirement_id,
                    document_id,
                    provision_id,
                    source_role,
                    verification_status,
                    verification_method,
                    evidence_artifact_page_id,
                    evidence_excerpt,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("requirement source insert did not return an identifier")
            return row[0]

    def relations_for_document(self, document_id: UUID) -> tuple[LegalRelationRecord, ...]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select id, source_document_id, source_provision_id, relation_type,
                       target_document_id, target_provision_id, status, verification_method
                from corpus.legal_relations
                where source_document_id = %s or target_document_id = %s
                order by created_at, id
                """,
                (document_id, document_id),
            )
            return tuple(LegalRelationRecord(*row) for row in cursor.fetchall())
