from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.provenance,
]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def _one(cursor: psycopg.Cursor[Any]) -> Any:
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _court(cursor: psycopg.Cursor[Any]) -> Any:
    suffix = uuid4().hex[:10]
    cursor.execute(
        """
        INSERT INTO corpus.courts (code, name, jurisdiction)
        VALUES (%s, %s, 'DO') RETURNING id
        """,
        (f"DO-FINAL-{suffix}", f"Tribunal final {suffix}"),
    )
    return _one(cursor)


def _decision(cursor: psycopg.Cursor[Any], court_id: Any) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.judicial_decisions (court_id)
        VALUES (%s) RETURNING id
        """,
        (court_id,),
    )
    return _one(cursor)


def _proposition(
    cursor: psycopg.Cursor[Any],
    decision_id: Any,
    text: str,
) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_propositions (
            proposition_type, canonical_text,
            assertion_kind, verification_status
        ) VALUES (
            'holding', %s, 'derived_from_primary_text', 'verified'
        ) RETURNING id
        """,
        (text,),
    )
    proposition_id = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.legal_proposition_subjects (
            proposition_id, subject_type, judicial_decision_id
        ) VALUES (%s, 'judicial_decision', %s)
        """,
        (proposition_id, decision_id),
    )
    return proposition_id


def _evidence(
    cursor: psycopg.Cursor[Any],
    decision_id: Any,
    proposition_id: Any,
) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_proposition_evidence (
            proposition_id, source_case_id, evidence_role,
            extraction_method, exact_excerpt
        ) VALUES (
            %s, %s, 'supports', 'human_review', 'Fragmento verificado'
        ) RETURNING id
        """,
        (proposition_id, decision_id),
    )
    return _one(cursor)


def test_judicial_decision_is_physical_identity_and_cases_is_only_compat_view(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relname, relkind FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'corpus'
              AND relname IN ('judicial_decisions', 'cases')
            ORDER BY relname
            """
        )
        assert cursor.fetchall() == [
            ("cases", "v"),
            ("judicial_decisions", "r"),
        ]


def test_dispositions_and_party_roles_use_extensible_concepts(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        cursor.execute(
            "SELECT id FROM corpus.disposition_concepts WHERE code = 'cassated'"
        )
        cassated = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_decision_dispositions (
                case_id, ordinal, disposition_concept_id, raw_text,
                extraction_method, verification_status
            ) VALUES (
                %s, 1, %s, 'CASA la sentencia recurrida', 'human', 'verified'
            )
            """,
            (decision, cassated),
        )
        cursor.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='corpus'
              AND table_name='judicial_decision_dispositions'
              AND column_name='disposition_type'
            """
        )
        assert cursor.fetchone() is None

        cursor.execute(
            """
            INSERT INTO corpus.legal_proceedings (canonical_title)
            VALUES ('Proceso') RETURNING id
            """
        )
        proceeding = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.participants (display_name)
            VALUES ('Parte') RETURNING id
            """
        )
        participant = _one(cursor)
        cursor.execute(
            """
            SELECT id FROM corpus.procedural_role_concepts
            WHERE code = 'appellant'
            """
        )
        role_concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.proceeding_party_roles (
                proceeding_id, participant_id, role_concept_id,
                party_side, raw_role, verification_status,
                verification_method
            ) VALUES (
                %s,%s,%s,'claimant','recurrente','verified','primary_text'
            )
            """,
            (proceeding, participant, role_concept),
        )


def test_verified_treatment_requires_source_evidence_and_correct_membership(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        source = _decision(cursor, court)
        target = _decision(cursor, court)
        unrelated = _decision(cursor, court)
        source_prop = _proposition(cursor, source, "Regla de la fuente")
        target_prop = _proposition(cursor, target, "Regla del objetivo")
        wrong_prop = _proposition(cursor, unrelated, "Regla ajena")
        evidence_id = _evidence(cursor, source, source_prop)

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_treatment_assertions (
                    source_case_id, target_case_id, treatment_type,
                    issue_proposition_id, source_proposition_id,
                    target_proposition_id, verification_status,
                    verification_method
                ) VALUES (
                    %s,%s,'distinguishes',%s,%s,%s,
                    'verified','human_legal_review'
                )
                """,
                (source, target, source_prop, source_prop, target_prop),
            )

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_treatment_assertions (
                    source_case_id, target_case_id, treatment_type,
                    issue_proposition_id, source_proposition_id,
                    target_proposition_id, evidence_id,
                    verification_status, verification_method
                ) VALUES (
                    %s,%s,'distinguishes',%s,%s,%s,%s,
                    'verified','human_legal_review'
                )
                """,
                (
                    source,
                    target,
                    source_prop,
                    wrong_prop,
                    target_prop,
                    evidence_id,
                ),
            )

        cursor.execute(
            """
            INSERT INTO corpus.legal_treatment_assertions (
                source_case_id, target_case_id, treatment_type,
                issue_proposition_id, source_proposition_id,
                target_proposition_id, evidence_id,
                verification_status, verification_method
            ) VALUES (
                %s,%s,'distinguishes',%s,%s,%s,%s,
                'verified','human_legal_review'
            )
            """,
            (
                source,
                target,
                source_prop,
                source_prop,
                target_prop,
                evidence_id,
            ),
        )


def test_opinion_joiner_must_be_panel_member(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        officers: list[Any] = []
        for name in ("Jueza autora", "Juez extraño"):
            cursor.execute(
                """
                INSERT INTO corpus.judicial_officers (display_name)
                VALUES (%s) RETURNING id
                """,
                (name,),
            )
            officers.append(_one(cursor))
        author, outsider = officers
        cursor.execute(
            """
            INSERT INTO corpus.decision_panel_members (
                case_id, officer_id, role_raw, panel_role,
                verification_status, verification_method
            ) VALUES (
                %s,%s,'Miembro','member','verified','primary_text'
            )
            """,
            (decision, author),
        )
        cursor.execute(
            """
            INSERT INTO corpus.judicial_opinions (
                case_id, opinion_type, author_officer_id,
                verification_status, verification_method
            ) VALUES (
                %s,'majority',%s,'verified','primary_text'
            ) RETURNING id
            """,
            (decision, author),
        )
        opinion = _one(cursor)
        with pytest.raises(
            psycopg.errors.ForeignKeyViolation
        ), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.judicial_opinion_joiners (
                    opinion_id, case_id, officer_id, join_type
                ) VALUES (%s,%s,%s,'joins_all')
                """,
                (opinion, decision, outsider),
            )


def test_competence_dimensions_are_independent(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        suffix = uuid4().hex[:8]
        cursor.execute(
            """
            INSERT INTO corpus.territorial_units (
                code, name, unit_type
            ) VALUES (%s, 'Santo Domingo', 'province') RETURNING id
            """,
            (f"do_sd_{suffix}",),
        )
        territory = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_matter_concepts (code, name)
            VALUES (%s, 'Civil') RETURNING id
            """,
            (f"civil_{suffix}",),
        )
        matter = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.court_territorial_competences (
                court_id, territorial_unit_id,
                verification_status, verification_method
            ) VALUES (%s,%s,'verified','official_registry')
            """,
            (court, territory),
        )
        cursor.execute(
            """
            INSERT INTO corpus.court_subject_matter_competences (
                court_id, legal_matter_concept_id,
                verification_status, verification_method
            ) VALUES (%s,%s,'verified','official_registry')
            """,
            (court, matter),
        )
        cursor.execute(
            """
            INSERT INTO corpus.court_functional_competences (
                court_id, function_type, instance_level,
                verification_status, verification_method
            ) VALUES (
                %s,'appellate','second','verified','official_registry'
            )
            """,
            (court,),
        )
        cursor.execute(
            """
            SELECT
              (SELECT count(*)
               FROM corpus.court_territorial_competences
               WHERE court_id=%s),
              (SELECT count(*)
               FROM corpus.court_subject_matter_competences
               WHERE court_id=%s),
              (SELECT count(*)
               FROM corpus.court_functional_competences
               WHERE court_id=%s)
            """,
            (court, court, court),
        )
        assert cursor.fetchone() == (1, 1, 1)
