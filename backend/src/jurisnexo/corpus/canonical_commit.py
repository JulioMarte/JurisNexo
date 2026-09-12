from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

import psycopg
from pydantic import BaseModel, ConfigDict, Field, model_validator

from jurisnexo.corpus.access import (
    CanonicalCommitAuthorization,
    CorpusPrincipal,
    CorpusScope,
    authorize_canonical_commit,
)
from jurisnexo.ingestion.decision_reconstruction import SourceFaithfulDecision

PUBLIC_SCOPE_ID = UUID("00000000-0000-0000-0000-000000000001")
StructureAuditState = Literal[
    "APPROVED",
    "APPROVED_WITH_AMENDMENTS",
    "MORE_INVESTIGATION_REQUIRED",
    "REJECTED",
    "SOURCE_QUALITY_BLOCKED",
]
_ALLOW_STRUCTURE_STATES = {"APPROVED", "APPROVED_WITH_AMENDMENTS"}


class CanonicalCommitError(ValueError):
    """Raised when deterministic canonical persistence requirements are not met."""


class CanonicalSourcePageBinding(BaseModel):
    """Bridge one bounded document-view page to its durable source artifact page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    view_page: int = Field(ge=1)
    artifact_page_id: UUID


class CanonicalCaseCommitRequest(BaseModel):
    """Provider-neutral input for committing one audited, source-faithful decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authorization: CanonicalCommitAuthorization
    structure_audit_state: StructureAuditState
    court_id: UUID
    decision: SourceFaithfulDecision
    page_bindings: tuple[CanonicalSourcePageBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source_bindings(self) -> CanonicalCaseCommitRequest:
        expected_view_pages = [page.view_page for page in self.decision.pages]
        bound_view_pages = [binding.view_page for binding in self.page_bindings]
        if bound_view_pages != expected_view_pages:
            raise ValueError(
                "page_bindings must cover the source-faithful decision exactly and in order"
            )

        bound_page_ids = [binding.artifact_page_id for binding in self.page_bindings]
        if len(set(bound_page_ids)) != len(bound_page_ids):
            raise ValueError("page_bindings must not reuse an artifact page")

        approved_page_ids = list(self.authorization.approved_artifact_page_ids)
        if len(set(approved_page_ids)) != len(approved_page_ids):
            raise ValueError("approved_artifact_page_ids must not contain duplicates")
        if set(bound_page_ids) != set(approved_page_ids):
            raise ValueError(
                "page_bindings must match approved_artifact_page_ids exactly"
            )
        return self


class CanonicalCaseCommitResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_id: UUID
    case_id: UUID
    occurrence_id: UUID
    case_page_ids: tuple[UUID, ...]
    passage_ids: tuple[UUID, ...]


def _resolve_scope_id(cursor: psycopg.Cursor[Any], scope: CorpusScope) -> UUID:
    if scope.visibility == "public":
        cursor.execute(
            "select id from corpus.scopes where id = %s and visibility = 'public'",
            (PUBLIC_SCOPE_ID,),
        )
    else:
        cursor.execute(
            """
            select id
            from corpus.scopes
            where visibility = 'private' and organization_id = %s
            """,
            (scope.organization_id,),
        )
    row = cursor.fetchone()
    if row is None:
        raise CanonicalCommitError("authorized corpus scope is not provisioned")
    return row[0]


def _require_court(cursor: psycopg.Cursor[Any], court_id: UUID) -> None:
    cursor.execute("select 1 from corpus.courts where id = %s", (court_id,))
    if cursor.fetchone() is None:
        raise CanonicalCommitError("court_id does not reference a known court")


def _require_artifact_in_scope(
    cursor: psycopg.Cursor[Any], *, artifact_id: UUID, scope_id: UUID
) -> None:
    cursor.execute(
        """
        select 1
        from corpus.source_artifacts
        where id = %s and scope_id = %s
        """,
        (artifact_id, scope_id),
    )
    if cursor.fetchone() is None:
        raise CanonicalCommitError("source artifact does not belong to the authorized scope")


def _validate_artifact_pages(
    cursor: psycopg.Cursor[Any],
    *,
    artifact_id: UUID,
    decision: SourceFaithfulDecision,
    bindings: tuple[CanonicalSourcePageBinding, ...],
) -> list[int]:
    page_numbers: list[int] = []
    for source_page, binding in zip(decision.pages, bindings, strict=True):
        cursor.execute(
            """
            select page_number, extracted_text
            from corpus.artifact_pages
            where id = %s and artifact_id = %s
            """,
            (binding.artifact_page_id, artifact_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise CanonicalCommitError(
                "approved artifact page does not belong to the source artifact"
            )
        page_number, extracted_text = row
        if extracted_text != source_page.text:
            raise CanonicalCommitError(
                "source-faithful decision text does not match durable artifact page text"
            )
        page_numbers.append(page_number)

    if any(
        right <= left
        for left, right in zip(page_numbers, page_numbers[1:], strict=False)
    ):
        raise CanonicalCommitError(
            "artifact pages must follow strictly increasing physical source order"
        )
    return page_numbers


def _insert_case(
    cursor: psycopg.Cursor[Any], *, court_id: UUID, scope_id: UUID
) -> UUID:
    cursor.execute(
        """
        insert into corpus.cases (court_id, scope_id)
        values (%s, %s)
        returning id
        """,
        (court_id, scope_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise CanonicalCommitError("case insert did not return an identifier")
    return row[0]


def _insert_occurrence(
    cursor: psycopg.Cursor[Any],
    *,
    case_id: UUID,
    artifact_id: UUID,
    scope_id: UUID,
    page_numbers: list[int],
) -> UUID:
    cursor.execute(
        """
        insert into corpus.case_artifact_occurrences (
            case_id, artifact_id, start_page, end_page,
            segmentation_status, segmentation_method, scope_id
        )
        values (%s, %s, %s, %s, 'verified', 'audited-canonical-commit', %s)
        returning id
        """,
        (case_id, artifact_id, page_numbers[0], page_numbers[-1], scope_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise CanonicalCommitError("occurrence insert did not return an identifier")
    return row[0]


def _insert_pages_and_passages(
    cursor: psycopg.Cursor[Any],
    *,
    case_id: UUID,
    artifact_id: UUID,
    scope_id: UUID,
    decision: SourceFaithfulDecision,
    bindings: tuple[CanonicalSourcePageBinding, ...],
) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
    case_page_ids: list[UUID] = []
    passage_ids: list[UUID] = []
    for ordinal, (page, binding) in enumerate(
        zip(decision.pages, bindings, strict=True), start=1
    ):
        printed_page_label = None if page.printed_page is None else str(page.printed_page)
        cursor.execute(
            """
            insert into corpus.case_pages (
                case_id, artifact_id, artifact_page_id, ordinal_in_case,
                printed_page_label, scope_id
            )
            values (%s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                case_id,
                artifact_id,
                binding.artifact_page_id,
                ordinal,
                printed_page_label,
                scope_id,
            ),
        )
        case_page = cursor.fetchone()
        if case_page is None:
            raise CanonicalCommitError("case page insert did not return an identifier")
        case_page_ids.append(case_page[0])

        cursor.execute(
            """
            insert into corpus.passages (
                case_id, page_start, page_end, passage_order, text, section_type
            )
            values (%s, %s, %s, %s, %s, 'source_page')
            returning id
            """,
            (case_id, ordinal, ordinal, ordinal, page.text),
        )
        passage = cursor.fetchone()
        if passage is None:
            raise CanonicalCommitError("passage insert did not return an identifier")
        passage_ids.append(passage[0])

    return tuple(case_page_ids), tuple(passage_ids)


def commit_canonical_case(
    *,
    connection: psycopg.Connection[Any],
    principal: CorpusPrincipal,
    request: CanonicalCaseCommitRequest,
) -> CanonicalCaseCommitResult:
    """Commit one audited decision atomically after deterministic provenance checks."""

    authorize_canonical_commit(principal=principal, request=request.authorization)
    if request.structure_audit_state not in _ALLOW_STRUCTURE_STATES:
        raise CanonicalCommitError(
            "canonical commit requires APPROVED or APPROVED_WITH_AMENDMENTS structure audit"
        )

    with connection.transaction(), connection.cursor() as cursor:
        scope_id = _resolve_scope_id(cursor, request.authorization.scope)
        _require_court(cursor, request.court_id)
        _require_artifact_in_scope(
            cursor,
            artifact_id=request.authorization.source_artifact_id,
            scope_id=scope_id,
        )
        page_numbers = _validate_artifact_pages(
            cursor,
            artifact_id=request.authorization.source_artifact_id,
            decision=request.decision,
            bindings=request.page_bindings,
        )
        case_id = _insert_case(cursor, court_id=request.court_id, scope_id=scope_id)
        occurrence_id = _insert_occurrence(
            cursor,
            case_id=case_id,
            artifact_id=request.authorization.source_artifact_id,
            scope_id=scope_id,
            page_numbers=page_numbers,
        )
        case_page_ids, passage_ids = _insert_pages_and_passages(
            cursor,
            case_id=case_id,
            artifact_id=request.authorization.source_artifact_id,
            scope_id=scope_id,
            decision=request.decision,
            bindings=request.page_bindings,
        )

    return CanonicalCaseCommitResult(
        scope_id=scope_id,
        case_id=case_id,
        occurrence_id=occurrence_id,
        case_page_ids=case_page_ids,
        passage_ids=passage_ids,
    )
