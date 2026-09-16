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
        "INSERT INTO corpus.courts(code,name,jurisdiction) "
        "VALUES (%s,%s,'DO') RETURNING id",
        (f"DO-V2-{suffix}", f"Tribunal V2 {suffix}"),
    )
    return _one(cursor)


def _decision(cursor: psycopg.Cursor[Any], court_id: Any) -> Any:
    cursor.execute(
        "INSERT INTO corpus.judicial_decisions(court_id) VALUES (%s) RETURNING id",
        (court_id,),
    )
    return _one(cursor)


def _proposition(cursor: psycopg.Cursor[Any], text: str) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_propositions(
            proposition_type, canonical_text, assertion_kind, verification_status
        ) VALUES ('holding', %s, 'derived_from_primary_text', 'candidate')
        RETURNING id
        """,
        (text,),
    )
    return _one(cursor)


def test_proposition_may_have_multiple_same_type_subjects_and_identity_is_immutable(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        first = _decision(cursor, court)
        second = _decision(cursor, court)
        proposition = _proposition(cursor, "Dos decisiones sostienen la misma regla")
        cursor.execute(
            """
            INSERT INTO corpus.legal_proposition_subjects(
                proposition_id, subject_type, judicial_decision_id, ordinal
            ) VALUES
                (%s, 'judicial_decision', %s, 1),
                (%s, 'judicial_decision', %s, 2)
            """,
            (proposition, first, proposition, second),
        )
        cursor.execute(
            "SELECT count(*) FROM corpus.legal_proposition_subjects "
            "WHERE proposition_id=%s",
            (proposition,),
        )
        assert cursor.fetchone() == (2,)

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                "UPDATE corpus.legal_propositions "
                "SET canonical_text='reescritura' WHERE id=%s",
                (proposition,),
            )


def test_decision_supports_multiple_matters_and_multiple_equal_proceedings(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        matters: list[Any] = []
        for label in ("Civil", "Constitucional"):
            code = f"matter_{uuid4().hex[:10]}"
            cursor.execute(
                "INSERT INTO corpus.legal_matter_concepts(code,name) "
                "VALUES (%s,%s) RETURNING id",
                (code, label),
            )
            matters.append(_one(cursor))
        for ordinal, matter in enumerate(matters, start=1):
            cursor.execute(
                """
                INSERT INTO corpus.decision_legal_matters(
                    decision_id, legal_matter_concept_id, relation_type, ordinal,
                    verification_status, verification_method
                ) VALUES (%s,%s,'addresses',%s,'verified','human_review')
                """,
                (decision, matter, ordinal),
            )
        cursor.execute(
            "SELECT count(*) FROM corpus.decision_legal_matters WHERE decision_id=%s",
            (decision,),
        )
        assert cursor.fetchone() == (2,)

        proceedings: list[Any] = []
        for title in ("Expediente acumulado A", "Expediente acumulado B"):
            cursor.execute(
                "INSERT INTO corpus.legal_proceedings(canonical_title) "
                "VALUES (%s) RETURNING id",
                (title,),
            )
            proceedings.append(_one(cursor))
        for proceeding in proceedings:
            cursor.execute(
                """
                INSERT INTO corpus.proceeding_decisions(
                    proceeding_id, case_id, relation_type, is_primary,
                    verification_status, verification_method
                ) VALUES (%s,%s,'decision_in_proceeding',true,'verified',
                          'official_metadata')
                """,
                (proceeding, decision),
            )
        cursor.execute(
            "SELECT count(*) FROM corpus.proceeding_decisions "
            "WHERE case_id=%s AND is_primary",
            (decision,),
        )
        assert cursor.fetchone() == (2,)


def test_opinions_have_multiple_authors_and_one_judge_has_multiple_stances(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        officers: list[Any] = []
        for name in ("Magistrada A", "Magistrado B"):
            cursor.execute(
                "INSERT INTO corpus.judicial_officers(display_name,identity_status) "
                "VALUES (%s,'canonical') RETURNING id",
                (name,),
            )
            officer = _one(cursor)
            officers.append(officer)
            cursor.execute(
                """
                INSERT INTO corpus.decision_panel_members(
                    case_id, officer_id, role_raw, panel_role,
                    verification_status, verification_method
                ) VALUES (%s,%s,'Miembro','member','verified','primary_text')
                """,
                (decision, officer),
            )

        cursor.execute(
            """
            INSERT INTO corpus.judicial_opinions(
                case_id, opinion_type, verification_status, verification_method
            ) VALUES (%s,'separate','verified','primary_text') RETURNING id
            """,
            (decision,),
        )
        opinion = _one(cursor)
        for ordinal, officer in enumerate(officers, start=1):
            cursor.execute(
                """
                INSERT INTO corpus.judicial_opinion_authors(
                    opinion_id, case_id, officer_id, authorship_role, ordinal
                ) VALUES (%s,%s,%s,'coauthor',%s)
                """,
                (opinion, decision, officer, ordinal),
            )
        cursor.execute(
            "SELECT count(*) FROM corpus.judicial_opinion_authors WHERE opinion_id=%s",
            (opinion,),
        )
        assert cursor.fetchone() == (2,)

        cursor.execute(
            """
            INSERT INTO corpus.decision_votes(
                case_id, officer_id, vote_type, verification_status, verification_method
            ) VALUES (%s,%s,'concurring','verified','primary_text') RETURNING id
            """,
            (decision, officers[0]),
        )
        vote = _one(cursor)
        proposition = _proposition(cursor, "Disiente solo respecto de esta cuestión")
        cursor.execute(
            """
            INSERT INTO corpus.judicial_vote_stances(
                vote_id, case_id, officer_id, stance_type, scope_type,
                opinion_id, verification_status, verification_method
            ) VALUES (%s,%s,%s,'joins','opinion',%s,'verified','primary_text')
            """,
            (vote, decision, officers[0], opinion),
        )
        cursor.execute(
            """
            INSERT INTO corpus.judicial_vote_stances(
                vote_id, case_id, officer_id, stance_type, scope_type,
                proposition_id, verification_status, verification_method
            ) VALUES (%s,%s,%s,'dissents_in_part','proposition',%s,
                      'verified','primary_text')
            """,
            (vote, decision, officers[0], proposition),
        )
        cursor.execute(
            "SELECT count(*) FROM corpus.judicial_vote_stances WHERE vote_id=%s",
            (vote,),
        )
        assert cursor.fetchone() == (2,)


def test_norm_identity_is_contextual_not_just_proposition_text(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        proposition = _proposition(cursor, "La misma formulación puede tener distinto alcance")
        jurisdiction_codes: list[str] = []
        for _ in range(2):
            code = f"jur_{uuid4().hex[:10]}"
            cursor.execute(
                "INSERT INTO corpus.jurisdictions(code,name) VALUES (%s,%s)",
                (code, code),
            )
            jurisdiction_codes.append(code)

        assertion_ids: list[Any] = []
        for code in jurisdiction_codes:
            cursor.execute(
                """
                INSERT INTO corpus.legal_norm_assertions(
                    proposition_id, jurisdiction_code, norm_kind, derivation_kind,
                    known_from, verification_status, verification_method
                ) VALUES (
                    %s,%s,'rule','human_legal_analysis','2026-01-01Z',
                    'candidate','human_review'
                ) RETURNING id
                """,
                (proposition, code),
            )
            assertion_ids.append(_one(cursor))
        cursor.execute(
            """
            SELECT count(DISTINCT norm_claim_id)
            FROM corpus.legal_norm_assertions WHERE id = ANY(%s)
            """,
            (assertion_ids,),
        )
        assert cursor.fetchone() == (2,)

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_norm_assertions(
                    proposition_id, jurisdiction_code, norm_kind, derivation_kind,
                    known_from, verification_status, verification_method
                ) VALUES (
                    %s,%s,'rule','human_legal_analysis','2026-02-01Z',
                    'candidate','human_review'
                )
                """,
                (proposition, jurisdiction_codes[0]),
            )


def test_common_entity_identity_and_claim_to_disposition_effect(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.legal_entities(entity_kind,canonical_name,identity_status)
            VALUES ('person','Persona jurídica compartida','canonical') RETURNING id
            """
        )
        entity = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.participants(
                participant_kind, display_name, legal_entity_id
            ) VALUES ('person','Persona jurídica compartida',%s) RETURNING id
            """,
            (entity,),
        )
        participant = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_officers(
                display_name, identity_status, legal_entity_id
            ) VALUES ('Persona jurídica compartida','canonical',%s) RETURNING id
            """,
            (entity,),
        )
        officer = _one(cursor)
        cursor.execute(
            "SELECT legal_entity_id FROM corpus.participants WHERE id=%s",
            (participant,),
        )
        assert cursor.fetchone() == (entity,)
        cursor.execute(
            "SELECT legal_entity_id FROM corpus.judicial_officers WHERE id=%s",
            (officer,),
        )
        assert cursor.fetchone() == (entity,)

        cursor.execute(
            "INSERT INTO corpus.legal_proceedings(canonical_title) "
            "VALUES ('Proceso con pretensión') RETURNING id"
        )
        proceeding = _one(cursor)
        cursor.execute(
            "SELECT id FROM corpus.legal_claim_concepts WHERE code='appeal_ground'"
        )
        claim_concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_claims(
                proceeding_id, claim_concept_id, claim_text,
                verification_status, verification_method
            ) VALUES (%s,%s,'Primer medio de casación','verified','primary_text')
            RETURNING id
            """,
            (proceeding, claim_concept),
        )
        claim = _one(cursor)

        court = _court(cursor)
        decision = _decision(cursor, court)
        cursor.execute(
            """
            INSERT INTO corpus.proceeding_decisions(
                proceeding_id, case_id, verification_status, verification_method
            ) VALUES (%s,%s,'verified','official_metadata')
            """,
            (proceeding, decision),
        )
        cursor.execute(
            "SELECT id FROM corpus.disposition_concepts WHERE code='denied'"
        )
        disposition_concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_decision_dispositions(
                case_id, ordinal, disposition_concept_id, raw_text,
                extraction_method, verification_status
            ) VALUES (%s,1,%s,'RECHAZA el primer medio','human','verified') RETURNING id
            """,
            (decision, disposition_concept),
        )
        disposition = _one(cursor)
        cursor.execute(
            "SELECT id FROM corpus.claim_effect_concepts WHERE code='denied'"
        )
        effect = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.disposition_claim_effects(
                disposition_id, claim_id, effect_concept_id,
                verification_status, verification_method
            ) VALUES (%s,%s,%s,'verified','human_review')
            """,
            (disposition, claim, effect),
        )


def test_decision_states_are_durative_and_bitemporal(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        cursor.execute("SELECT id FROM corpus.decision_state_concepts WHERE code='final'")
        state = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.decision_legal_states(
                decision_id, state_concept_id, valid_from,
                known_from, known_to, verification_status, verification_method
            ) VALUES (
                %s,%s,'2025-01-01','2025-01-10Z','2025-03-01Z',
                'verified','official_metadata'
            )
            """,
            (decision, state),
        )
        cursor.execute(
            """
            INSERT INTO corpus.decision_legal_states(
                decision_id, state_concept_id, valid_from,
                known_from, verification_status, verification_method
            ) VALUES (
                %s,%s,'2025-01-15','2025-03-01Z','verified','official_correction'
            )
            """,
            (decision, state),
        )
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.decision_legal_states(
                    decision_id, state_concept_id, known_from, known_to,
                    verification_status, verification_method
                ) VALUES (%s,%s,'2025-02-01Z','2025-04-01Z','candidate','test')
                """,
                (decision, state),
            )
