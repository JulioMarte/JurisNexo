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
GLOBAL_RELATION_TYPES = frozenset(
    {
        "cites",
        "references",
        "authorized_by",
        "implements",
        "amends",
        "repeals",
        "partially_repeals",
        "supersedes",
        "requires",
        "satisfies",
        "exempts_from",
    }
)
AssertionMethod = Literal[
    "explicit_primary_text",
    "official_metadata",
    "deterministic_reference",
    "llm_extracted",
    "human_verified",
]
NormSourceRole = Literal[
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
    assertion_id: UUID
    relation_identity_id: UUID
    source_document_id: UUID
    source_provision_id: UUID | None
    relation_type: str
    target_document_id: UUID
    target_provision_id: UUID | None
    status: str
    verification_method: str


@dataclass(frozen=True, slots=True)
class LegalNormInput:
    jurisdiction_code: str | None
    norm_kind: str
    statement_text: str
    derivation_kind: Literal[
        "explicit_primary_text",
        "derived_from_sources",
        "synthesized_interpretation",
        "human_legal_analysis",
    ]
    scope_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    valid_from: date | None = None
    valid_to: date | None = None
    assertion_kind: Literal[
        "explicit_primary_text",
        "derived_from_primary_text",
        "synthesized_interpretation",
        "human_authored",
    ] = "synthesized_interpretation"


RequirementInput = LegalNormInput


def _uuid_text(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def relation_observation_key(observation: RelationObservationInput) -> str:
    payload = {
        "source_document_id": str(observation.source_document_id),
        "source_provision_id": _uuid_text(observation.source_provision_id),
        "relation_type": observation.relation_type,
        "target_document_id": _uuid_text(observation.target_document_id),
        "target_provision_id": _uuid_text(observation.target_provision_id),
        "raw_target_citation": observation.raw_target_citation,
        "assertion_method": observation.assertion_method,
        "method_name": observation.method_name,
        "evidence_artifact_page_id": _uuid_text(
            observation.evidence_artifact_page_id
        ),
        "evidence_char_start": observation.evidence_char_start,
        "evidence_char_end": observation.evidence_char_end,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(slots=True)
class PostgresLegalGraphRepository:
    """Deterministic persistence boundary for source structure and legal assertions."""

    connection: psycopg.Connection[Any]

    def upsert_provision(self, provision: ProvisionInput) -> UUID:
        if provision.normalized_label is None:
            return self._insert_unlabelled_provision(provision)
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.legal_document_provisions (
                    document_id, parent_provision_id, provision_type, label,
                    normalized_label, ordinal, heading, text,
                    effective_from, effective_to
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (
                    document_id,
                    (coalesce(
                        parent_provision_id,
                        '00000000-0000-0000-0000-000000000000'::uuid
                    )),
                    normalized_label
                ) where normalized_label is not null
                do update set
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
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
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

    def record_relation_observation(
        self,
        observation: RelationObservationInput,
    ) -> UUID:
        key = relation_observation_key(observation)
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.legal_relation_observations (
                    ingestion_job_id, observation_key, source_document_id,
                    source_provision_id, relation_type, target_document_id,
                    target_provision_id, raw_target_citation, assertion_method,
                    method_name, confidence, evidence_artifact_page_id,
                    evidence_excerpt, evidence_char_start, evidence_char_end
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                raise RuntimeError(
                    "relation observation upsert did not return an identifier"
                )
            return row[0]

    def promote_relation(
        self,
        observation_id: UUID,
        *,
        verification_method: str,
    ) -> UUID:
        """Promote a structural observation into a current assertion."""
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
                raise ValueError(
                    f"cannot promote observation in state {observation_status}"
                )
            if relation_type not in GLOBAL_RELATION_TYPES:
                raise ValueError(
                    f"relation type {relation_type!r} requires issue/proposition "
                    "context; promote it through legal_treatment_assertions instead"
                )

            cursor.execute(
                """
                insert into corpus.legal_relation_identities (
                    source_document_id, source_provision_id, relation_type,
                    target_document_id, target_provision_id
                ) values (%s,%s,%s,%s,%s)
                on conflict do nothing
                returning id
                """,
                (
                    source_document_id,
                    source_provision_id,
                    relation_type,
                    target_document_id,
                    target_provision_id,
                ),
            )
            identity = cursor.fetchone()
            if identity is None:
                cursor.execute(
                    """
                    select id
                    from corpus.legal_relation_identities
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
                identity = cursor.fetchone()
            if identity is None:
                raise RuntimeError("relation identity could not be resolved")
            relation_identity_id = identity[0]

            cursor.execute(
                """
                select id
                from corpus.legal_relation_assertions
                where relation_identity_id = %s and known_to is null
                for update
                """,
                (relation_identity_id,),
            )
            current = cursor.fetchone()
            if current is None:
                cursor.execute(
                    """
                    insert into corpus.legal_relation_assertions (
                        relation_identity_id, status, verification_method,
                        promoted_from_observation_id
                    ) values (%s, 'verified', %s, %s)
                    returning id
                    """,
                    (relation_identity_id, verification_method, observation_id),
                )
                current = cursor.fetchone()
                if current is None:
                    raise RuntimeError(
                        "relation assertion insert did not return an identifier"
                    )
            assertion_id: UUID = current[0]
            cursor.execute(
                """
                update corpus.legal_relation_observations
                set status = 'accepted'
                where id = %s
                """,
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
                    insert into corpus.legal_relation_assertion_evidence (
                        assertion_id, observation_id, artifact_page_id,
                        evidence_kind, evidence_excerpt,
                        evidence_char_start, evidence_char_end
                    )
                    select %s,%s,%s,%s,%s,%s,%s
                    where not exists (
                        select 1
                        from corpus.legal_relation_assertion_evidence
                        where assertion_id = %s and observation_id = %s
                    )
                    """,
                    (
                        assertion_id,
                        observation_id,
                        evidence_page_id,
                        evidence_kind,
                        evidence_excerpt,
                        evidence_char_start,
                        evidence_char_end,
                        assertion_id,
                        observation_id,
                    ),
                )
            return assertion_id

    def create_legal_norm(
        self,
        norm: LegalNormInput,
        *,
        verification_method: str,
    ) -> tuple[UUID, UUID]:
        """Create an analytical norm proposition and its first assertion."""
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.legal_propositions (
                    scope_id, proposition_type, canonical_text,
                    assertion_kind, verification_status
                ) values (%s, 'legal_requirement', %s, %s, 'candidate')
                returning id
                """,
                (norm.scope_id, norm.statement_text, norm.assertion_kind),
            )
            proposition = cursor.fetchone()
            if proposition is None:
                raise RuntimeError(
                    "legal norm proposition insert did not return an identifier"
                )
            proposition_id: UUID = proposition[0]
            cursor.execute(
                """
                insert into corpus.legal_proposition_subjects (
                    proposition_id, scope_id, subject_type
                ) values (%s, %s, 'general_law')
                """,
                (proposition_id, norm.scope_id),
            )
            cursor.execute(
                """
                insert into corpus.legal_norm_assertions (
                    scope_id, proposition_id, jurisdiction_code, norm_kind,
                    derivation_kind, valid_from, valid_to,
                    verification_status, verification_method
                ) values (%s,%s,%s,%s,%s,%s,%s,'candidate',%s)
                returning id
                """,
                (
                    norm.scope_id,
                    proposition_id,
                    norm.jurisdiction_code,
                    norm.norm_kind,
                    norm.derivation_kind,
                    norm.valid_from,
                    norm.valid_to,
                    verification_method,
                ),
            )
            assertion = cursor.fetchone()
            if assertion is None:
                raise RuntimeError(
                    "legal norm assertion insert did not return an identifier"
                )
            return proposition_id, assertion[0]

    def attach_norm_source(
        self,
        *,
        norm_assertion_id: UUID,
        document_id: UUID,
        source_role: NormSourceRole,
        verification_method: str,
        provision_id: UUID | None = None,
        verification_status: str = "candidate",
        evidence_artifact_page_id: UUID | None = None,
        evidence_excerpt: str | None = None,
    ) -> UUID:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.legal_norm_sources (
                    norm_assertion_id, source_document_id,
                    source_document_provision_id, source_role,
                    verification_status, verification_method,
                    evidence_artifact_page_id, evidence_excerpt
                ) values (%s,%s,%s,%s,%s,%s,%s,%s)
                returning id
                """,
                (
                    norm_assertion_id,
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
                raise RuntimeError("legal norm source insert did not return an identifier")
            return row[0]

    def verify_legal_norm(self, norm_assertion_id: UUID, *, reviewer: str) -> None:
        with self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                """
                update corpus.legal_norm_assertions
                set verification_status = 'verified', reviewed_by = %s
                where id = %s
                """,
                (reviewer, norm_assertion_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown legal norm assertion: {norm_assertion_id}")

    def relations_for_document(
        self,
        document_id: UUID,
    ) -> tuple[LegalRelationRecord, ...]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select a.id, i.id, i.source_document_id,
                       i.source_provision_id, i.relation_type,
                       i.target_document_id, i.target_provision_id,
                       a.status, a.verification_method
                from corpus.legal_relation_assertions a
                join corpus.legal_relation_identities i
                  on i.id = a.relation_identity_id
                where a.known_to is null
                  and (
                    i.source_document_id = %s
                    or i.target_document_id = %s
                  )
                order by a.created_at, a.id
                """,
                (document_id, document_id),
            )
            return tuple(LegalRelationRecord(*row) for row in cursor.fetchall())
