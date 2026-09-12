from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import psycopg
import pytest

from jurisnexo.corpus.access import (
    CanonicalAuditState,
    CanonicalCommitAuthorization,
    CorpusAuthorizationError,
    CorpusPrincipal,
    CorpusScope,
)
from jurisnexo.corpus.canonical_commit import (
    CanonicalCaseCommitRequest,
    CanonicalCommitError,
    CanonicalSourcePageBinding,
    StructureAuditState,
    commit_canonical_case,
)
from jurisnexo.ingestion.decision_reconstruction import (
    DecisionBoundary,
    DecisionPageSpan,
    SourceFaithfulDecision,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

ORG_A = UUID("00000000-0000-0000-0000-0000000000ca")
ORG_B = UUID("00000000-0000-0000-0000-0000000000cb")
SUBJECT = UUID("00000000-0000-0000-0000-0000000000cc")


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn


def _insert_scope(cursor: psycopg.Cursor[Any], organization_id: UUID) -> UUID:
    cursor.execute(
        """
        insert into corpus.scopes (visibility, organization_id)
        values ('private', %s)
        returning id
        """,
        (organization_id,),
    )
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _insert_court(cursor: psycopg.Cursor[Any], code: str) -> UUID:
    cursor.execute(
        """
        insert into corpus.courts (code, name, jurisdiction)
        values (%s, %s, 'República Dominicana')
        returning id
        """,
        (code, f"{code} court"),
    )
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _insert_artifact(
    cursor: psycopg.Cursor[Any],
    *,
    scope_id: UUID,
    sha_char: str,
    pages: tuple[tuple[int, str], ...],
) -> tuple[UUID, tuple[UUID, ...]]:
    cursor.execute(
        """
        insert into corpus.source_artifacts (
            sha256, mime_type, byte_size, scope_id
        )
        values (%s, 'application/pdf', 100, %s)
        returning id
        """,
        (sha_char * 64, scope_id),
    )
    artifact = cursor.fetchone()
    assert artifact is not None

    page_ids: list[UUID] = []
    for page_number, text in pages:
        cursor.execute(
            """
            insert into corpus.artifact_pages (
                artifact_id, page_number, extracted_text, extraction_status
            )
            values (%s, %s, %s, 'native_text')
            returning id
            """,
            (artifact[0], page_number, text),
        )
        page = cursor.fetchone()
        assert page is not None
        page_ids.append(page[0])
    return artifact[0], tuple(page_ids)


def _decision(*, second_text: str = "Segunda página") -> SourceFaithfulDecision:
    first_text = "Primera página"
    pages = [
        DecisionPageSpan(
            view_page=7,
            printed_page=183,
            source_reference="artifact-page-10",
            text=first_text,
            char_end=len(first_text),
            readability="readable",
        ),
        DecisionPageSpan(
            view_page=8,
            printed_page=184,
            source_reference="artifact-page-12",
            text=second_text,
            char_end=len(second_text),
            readability="readable",
        ),
    ]
    return SourceFaithfulDecision(
        boundary=DecisionBoundary(start_view_page=7, end_view_page=8),
        pages=pages,
        ordered_text=f"{first_text}\n\n{second_text}",
    )


def _principal(*, organization_id: UUID = ORG_A) -> CorpusPrincipal:
    return CorpusPrincipal(
        subject_id=SUBJECT,
        organization_ids=frozenset({organization_id}),
    )


def _request(
    *,
    organization_id: UUID,
    artifact_id: UUID,
    page_ids: tuple[UUID, UUID],
    court_id: UUID,
    extraction_state: CanonicalAuditState = "VERIFIED",
    structure_state: StructureAuditState = "APPROVED",
    decision: SourceFaithfulDecision | None = None,
) -> CanonicalCaseCommitRequest:
    return CanonicalCaseCommitRequest(
        authorization=CanonicalCommitAuthorization(
            scope=CorpusScope(visibility="private", organization_id=organization_id),
            extraction_audit_state=extraction_state,
            source_artifact_id=artifact_id,
            approved_artifact_page_ids=page_ids,
        ),
        structure_audit_state=structure_state,
        court_id=court_id,
        decision=_decision() if decision is None else decision,
        page_bindings=(
            CanonicalSourcePageBinding(view_page=7, artifact_page_id=page_ids[0]),
            CanonicalSourcePageBinding(view_page=8, artifact_page_id=page_ids[1]),
        ),
    )


def test_verified_private_commit_is_atomic_and_source_faithful(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        scope_id = _insert_scope(cursor, ORG_A)
        court_id = _insert_court(cursor, "CANONICAL-SUCCESS")
        artifact_id, page_ids = _insert_artifact(
            cursor,
            scope_id=scope_id,
            sha_char="f",
            pages=((10, "Primera página"), (12, "Segunda página")),
        )
        request = _request(
            organization_id=ORG_A,
            artifact_id=artifact_id,
            page_ids=(page_ids[0], page_ids[1]),
            court_id=court_id,
        )

        result = commit_canonical_case(
            connection=connection,
            principal=_principal(),
            request=request,
        )

        assert result.scope_id == scope_id
        assert len(result.case_page_ids) == 2
        assert len(result.passage_ids) == 2

        cursor.execute(
            """
            select scope_id, court_id, identity_status, quality_status
            from corpus.cases
            where id = %s
            """,
            (result.case_id,),
        )
        assert cursor.fetchone() == (
            scope_id,
            court_id,
            "identity_unresolved",
            "unreviewed",
        )

        cursor.execute(
            """
            select start_page, end_page, segmentation_status, scope_id
            from corpus.case_artifact_occurrences
            where id = %s
            """,
            (result.occurrence_id,),
        )
        assert cursor.fetchone() == (10, 12, "verified", scope_id)

        cursor.execute(
            """
            select ordinal_in_case, artifact_page_id, printed_page_label, scope_id
            from corpus.case_pages
            where case_id = %s
            order by ordinal_in_case
            """,
            (result.case_id,),
        )
        assert cursor.fetchall() == [
            (1, page_ids[0], "183", scope_id),
            (2, page_ids[1], "184", scope_id),
        ]

        cursor.execute(
            """
            select page_start, page_end, passage_order, text, section_type
            from corpus.passages
            where case_id = %s
            order by passage_order
            """,
            (result.case_id,),
        )
        assert cursor.fetchall() == [
            (1, 1, 1, "Primera página", "source_page"),
            (2, 2, 2, "Segunda página", "source_page"),
        ]


def test_rejected_extraction_audit_writes_nothing(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        scope_id = _insert_scope(cursor, ORG_A)
        court_id = _insert_court(cursor, "CANONICAL-REJECT-EXTRACTION")
        artifact_id, page_ids = _insert_artifact(
            cursor,
            scope_id=scope_id,
            sha_char="1",
            pages=((1, "Primera página"), (2, "Segunda página")),
        )
        request = _request(
            organization_id=ORG_A,
            artifact_id=artifact_id,
            page_ids=(page_ids[0], page_ids[1]),
            court_id=court_id,
            extraction_state="REJECTED",
        )

        cursor.execute("select count(*) from corpus.cases where court_id = %s", (court_id,))
        assert cursor.fetchone() == (0,)
        with pytest.raises(CorpusAuthorizationError):
            commit_canonical_case(
                connection=connection,
                principal=_principal(),
                request=request,
            )
        cursor.execute("select count(*) from corpus.cases where court_id = %s", (court_id,))
        assert cursor.fetchone() == (0,)


def test_rejected_structure_audit_writes_nothing(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        scope_id = _insert_scope(cursor, ORG_A)
        court_id = _insert_court(cursor, "CANONICAL-REJECT-STRUCTURE")
        artifact_id, page_ids = _insert_artifact(
            cursor,
            scope_id=scope_id,
            sha_char="2",
            pages=((1, "Primera página"), (2, "Segunda página")),
        )
        request = _request(
            organization_id=ORG_A,
            artifact_id=artifact_id,
            page_ids=(page_ids[0], page_ids[1]),
            court_id=court_id,
            structure_state="MORE_INVESTIGATION_REQUIRED",
        )

        with pytest.raises(CanonicalCommitError):
            commit_canonical_case(
                connection=connection,
                principal=_principal(),
                request=request,
            )
        cursor.execute("select count(*) from corpus.cases where court_id = %s", (court_id,))
        assert cursor.fetchone() == (0,)


def test_artifact_page_from_another_artifact_is_rejected_before_case_insert(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        scope_id = _insert_scope(cursor, ORG_A)
        court_id = _insert_court(cursor, "CANONICAL-WRONG-PAGE")
        artifact_id, page_ids = _insert_artifact(
            cursor,
            scope_id=scope_id,
            sha_char="3",
            pages=((1, "Primera página"), (2, "Segunda página")),
        )
        _, other_page_ids = _insert_artifact(
            cursor,
            scope_id=scope_id,
            sha_char="4",
            pages=((3, "Segunda página"),),
        )
        request = _request(
            organization_id=ORG_A,
            artifact_id=artifact_id,
            page_ids=(page_ids[0], other_page_ids[0]),
            court_id=court_id,
        )

        with pytest.raises(CanonicalCommitError, match="does not belong"):
            commit_canonical_case(
                connection=connection,
                principal=_principal(),
                request=request,
            )
        cursor.execute("select count(*) from corpus.cases where court_id = %s", (court_id,))
        assert cursor.fetchone() == (0,)


def test_source_text_mismatch_is_rejected_before_case_insert(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        scope_id = _insert_scope(cursor, ORG_A)
        court_id = _insert_court(cursor, "CANONICAL-TEXT-MISMATCH")
        artifact_id, page_ids = _insert_artifact(
            cursor,
            scope_id=scope_id,
            sha_char="5",
            pages=((1, "Primera página"), (2, "Texto durable distinto")),
        )
        request = _request(
            organization_id=ORG_A,
            artifact_id=artifact_id,
            page_ids=(page_ids[0], page_ids[1]),
            court_id=court_id,
        )

        with pytest.raises(CanonicalCommitError, match="does not match"):
            commit_canonical_case(
                connection=connection,
                principal=_principal(),
                request=request,
            )
        cursor.execute("select count(*) from corpus.cases where court_id = %s", (court_id,))
        assert cursor.fetchone() == (0,)


def test_artifact_from_another_scope_is_rejected(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        scope_a = _insert_scope(cursor, ORG_A)
        scope_b = _insert_scope(cursor, ORG_B)
        court_id = _insert_court(cursor, "CANONICAL-WRONG-SCOPE")
        artifact_id, page_ids = _insert_artifact(
            cursor,
            scope_id=scope_b,
            sha_char="6",
            pages=((1, "Primera página"), (2, "Segunda página")),
        )
        request = _request(
            organization_id=ORG_A,
            artifact_id=artifact_id,
            page_ids=(page_ids[0], page_ids[1]),
            court_id=court_id,
        )

        with pytest.raises(CanonicalCommitError, match="authorized scope"):
            commit_canonical_case(
                connection=connection,
                principal=_principal(),
                request=request,
            )
        cursor.execute("select count(*) from corpus.cases where court_id = %s", (court_id,))
        assert cursor.fetchone() == (0,)
        assert scope_a != scope_b
