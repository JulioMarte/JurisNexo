from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.invariant,
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
        (f"DO-EXT-{suffix}", f"Tribunal extensible {suffix}"),
    )
    return _one(cursor)


def _decision(cursor: psycopg.Cursor[Any], court_id: Any) -> Any:
    cursor.execute(
        "INSERT INTO corpus.judicial_decisions(court_id) VALUES (%s) RETURNING id",
        (court_id,),
    )
    return _one(cursor)


def _proceeding(cursor: psycopg.Cursor[Any], title: str) -> Any:
    cursor.execute(
        "INSERT INTO corpus.legal_proceedings(canonical_title) VALUES (%s) RETURNING id",
        (title,),
    )
    return _one(cursor)


def _link_proceeding(
    cursor: psycopg.Cursor[Any], proceeding_id: Any, decision_id: Any
) -> None:
    cursor.execute(
        """
        INSERT INTO corpus.proceeding_decisions(
            proceeding_id, case_id, relation_type,
            verification_status, verification_method
        ) VALUES (
            %s, %s, 'decision_in_proceeding', 'verified', 'test_fixture'
        )
        """,
        (proceeding_id, decision_id),
    )


def _party_role(cursor: psycopg.Cursor[Any], proceeding_id: Any) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.participants(participant_kind, display_name)
        VALUES ('person', %s) RETURNING id
        """,
        (f"Parte {uuid4().hex[:8]}",),
    )
    participant_id = _one(cursor)
    cursor.execute(
        "SELECT id FROM corpus.procedural_role_concepts WHERE code='appellant'"
    )
    role_concept_id = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.proceeding_party_roles(
            proceeding_id, participant_id, role_concept_id,
            verification_status, verification_method
        ) VALUES (%s,%s,%s,'verified','test_fixture') RETURNING id
        """,
        (proceeding_id, participant_id, role_concept_id),
    )
    return _one(cursor)


def _claim(cursor: psycopg.Cursor[Any], proceeding_id: Any) -> Any:
    cursor.execute(
        "SELECT id FROM corpus.legal_claim_concepts WHERE code='appeal_ground'"
    )
    concept_id = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.legal_claims(
            proceeding_id, claim_concept_id, claim_text,
            verification_status, verification_method
        ) VALUES (%s,%s,%s,'verified','test_fixture') RETURNING id
        """,
        (proceeding_id, concept_id, f"Medio {uuid4().hex[:8]}"),
    )
    return _one(cursor)


def _proposition(cursor: psycopg.Cursor[Any], decision_id: Any) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_propositions(
            proposition_type, canonical_text, assertion_kind, verification_status
        ) VALUES ('conclusion', %s, 'derived_from_primary_text', 'verified')
        RETURNING id
        """,
        (f"Conclusión {uuid4().hex[:8]}",),
    )
    proposition_id = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.legal_proposition_subjects(
            proposition_id, subject_type, judicial_decision_id
        ) VALUES (%s,'judicial_decision',%s)
        """,
        (proposition_id, decision_id),
    )
    return proposition_id


def _disposition(cursor: psycopg.Cursor[Any], decision_id: Any, ordinal: int = 1) -> Any:
    cursor.execute("SELECT id FROM corpus.disposition_concepts WHERE code='other'")
    concept_id = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.judicial_decision_dispositions(
            case_id, ordinal, disposition_concept_id, raw_text,
            extraction_method, verification_status
        ) VALUES (%s,%s,%s,%s,'test_fixture','verified') RETURNING id
        """,
        (decision_id, ordinal, concept_id, f"Dispositivo {ordinal}"),
    )
    return _one(cursor)


def test_custom_opinion_and_stance_concepts_are_first_class(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)

        cursor.execute(
            """
            INSERT INTO corpus.judicial_opinion_type_concepts(code,name)
            VALUES (%s,%s) RETURNING id
            """,
            (f"jurisdictional_opinion_{uuid4().hex[:8]}", "Jurisdictional opinion"),
        )
        opinion_concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_opinions(
                case_id, opinion_type_concept_id,
                verification_status, verification_method
            ) VALUES (%s,%s,'verified','test_fixture')
            RETURNING opinion_type, opinion_type_concept_id
            """,
            (decision, opinion_concept),
        )
        opinion_row = cursor.fetchone()
        assert opinion_row is not None
        opinion_code, returned_concept = opinion_row
        assert returned_concept == opinion_concept
        assert isinstance(opinion_code, str)
        assert opinion_code.startswith("jurisdictional_opinion_")

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.judicial_opinions(
                    case_id, opinion_type, opinion_type_concept_id,
                    verification_status, verification_method
                ) VALUES (%s,'majority',%s,'verified','test_fixture')
                """,
                (decision, opinion_concept),
            )

        cursor.execute(
            "INSERT INTO corpus.judicial_officers(display_name) "
            "VALUES ('Magistrada extensible') RETURNING id"
        )
        officer = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.decision_panel_members(
                case_id, officer_id, role_raw, panel_role,
                verification_status, verification_method
            ) VALUES (%s,%s,'Miembro','member','verified','test_fixture')
            """,
            (decision, officer),
        )
        cursor.execute(
            """
            INSERT INTO corpus.decision_votes(
                case_id, officer_id, vote_type,
                verification_status, verification_method
            ) VALUES (%s,%s,'concurring','verified','test_fixture') RETURNING id
            """,
            (decision, officer),
        )
        vote = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_stance_concepts(code,name)
            VALUES (%s,%s) RETURNING id
            """,
            (f"formula_reservation_{uuid4().hex[:8]}", "Formula reservation"),
        )
        stance_concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_vote_stances(
                vote_id, case_id, officer_id, stance_concept_id, scope_type,
                verification_status, verification_method
            ) VALUES (%s,%s,%s,%s,'whole_decision','verified','test_fixture')
            RETURNING stance_type, stance_concept_id
            """,
            (vote, decision, officer, stance_concept),
        )
        stance_row = cursor.fetchone()
        assert stance_row is not None
        stance_code, returned_stance = stance_row
        assert returned_stance == stance_concept
        assert isinstance(stance_code, str)
        assert stance_code.startswith("formula_reservation_")


def test_authority_effects_are_extensible_and_legacy_view_remains_compatible(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        custom_code = f"do_constitutional_weight_{uuid4().hex[:8]}"
        cursor.execute(
            """
            INSERT INTO corpus.judicial_authority_effect_concepts(code,name)
            VALUES (%s,%s) RETURNING id
            """,
            (custom_code, "Dominican constitutional authority effect"),
        )
        concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_authority_effect_assertions(
                decision_id, authority_effect_concept_id, court_id, basis,
                verification_status, verification_method
            ) VALUES (%s,%s,%s,'Contextual constitutional effect',
                      'verified','human_legal_review')
            RETURNING authority_effect_code, authority_effect_concept_id
            """,
            (decision, concept, court),
        )
        assert cursor.fetchone() == (custom_code, concept)

        cursor.execute(
            """
            INSERT INTO corpus.precedential_authority_assertions(
                decision_id, authority_type, court_id, basis,
                verification_status, verification_method
            ) VALUES (%s,'persuasive',%s,'Compatibility write',
                      'verified','human_legal_review')
            RETURNING authority_type
            """,
            (decision, court),
        )
        assert cursor.fetchone() == ("persuasive",)

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.judicial_authority_effect_assertions(
                    decision_id, authority_effect_code,
                    authority_effect_concept_id, court_id, basis,
                    verification_status, verification_method
                ) VALUES (%s,'binding',%s,%s,'Contradictory code/concept',
                          'verified','human_legal_review')
                """,
                (decision, concept, court),
            )


def test_disposition_targets_cover_all_first_class_target_identities(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        other_decision = _decision(cursor, court)
        proceeding = _proceeding(cursor, "Procedimiento objetivo")
        _link_proceeding(cursor, proceeding, decision)
        party_role = _party_role(cursor, proceeding)
        claim = _claim(cursor, proceeding)
        proposition = _proposition(cursor, decision)
        disposition = _disposition(cursor, decision)

        rows = [
            ("claim", "claim_id", claim, "resolved_claim"),
            ("party_role", "party_role_id", party_role, "burdened_party"),
            ("proceeding", "proceeding_id", proceeding, "remanded_proceeding"),
            (
                "judicial_decision",
                "judicial_decision_id",
                other_decision,
                "affected_decision",
            ),
            ("proposition", "proposition_id", proposition, "adopted_proposition"),
        ]
        for target_type, column, target_id, target_role in rows:
            query = sql.SQL(
                """
                INSERT INTO corpus.judicial_disposition_targets(
                    disposition_id, target_type, {}, target_role,
                    verification_status, verification_method
                ) VALUES (%s,%s,%s,%s,'verified','human_legal_review')
                """
            ).format(sql.Identifier(column))
            cursor.execute(
                query,
                (disposition, target_type, target_id, target_role),
            )

        cursor.execute(
            """
            SELECT target_type FROM corpus.judicial_disposition_targets
            WHERE disposition_id=%s
            """,
            (disposition,),
        )
        assert {row[0] for row in cursor.fetchall()} == {
            "claim",
            "party_role",
            "proceeding",
            "judicial_decision",
            "proposition",
        }

        unrelated = _proceeding(cursor, "Procedimiento ajeno")
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.judicial_disposition_targets(
                    disposition_id, target_type, proceeding_id, target_role,
                    verification_status, verification_method
                ) VALUES (%s,'proceeding',%s,'affected','verified','test')
                """,
                (disposition, unrelated),
            )


def test_claim_effect_is_projected_into_general_target_layer(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        proceeding = _proceeding(cursor, "Procedimiento con medio")
        _link_proceeding(cursor, proceeding, decision)
        claim = _claim(cursor, proceeding)
        disposition = _disposition(cursor, decision)
        cursor.execute(
            "SELECT id FROM corpus.claim_effect_concepts WHERE code='denied'"
        )
        effect_concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.disposition_claim_effects(
                disposition_id, claim_id, effect_concept_id,
                verification_status, verification_method
            ) VALUES (%s,%s,%s,'verified','primary_text') RETURNING id
            """,
            (disposition, claim, effect_concept),
        )
        effect = _one(cursor)
        cursor.execute(
            """
            SELECT claim_id, target_role, source_claim_effect_id
            FROM corpus.judicial_disposition_targets
            WHERE disposition_id=%s AND source_claim_effect_id=%s
            """,
            (disposition, effect),
        )
        assert cursor.fetchone() == (claim, "resolved_claim", effect)


def test_legacy_disposition_target_fields_do_not_create_stale_double_truth(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        old_target = _decision(cursor, court)
        new_target = _decision(cursor, court)
        proceeding = _proceeding(cursor, "Procedimiento legacy target")
        _link_proceeding(cursor, proceeding, decision)
        cursor.execute("SELECT id FROM corpus.disposition_concepts WHERE code='other'")
        concept = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_decision_dispositions(
                case_id, ordinal, disposition_concept_id, raw_text,
                affected_case_id, affected_proceeding_id,
                extraction_method, verification_status
            ) VALUES (%s,1,%s,'Dispositivo legacy',%s,%s,
                      'test_fixture','verified') RETURNING id
            """,
            (decision, concept, old_target, proceeding),
        )
        disposition = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_disposition_targets(
                disposition_id, target_type, judicial_decision_id,
                target_role, verification_status, verification_method
            ) VALUES (%s,'judicial_decision',%s,'reviewed_decision',
                      'verified','human_review')
            """,
            (disposition, old_target),
        )
        cursor.execute(
            """
            UPDATE corpus.judicial_decision_dispositions
            SET affected_case_id=%s
            WHERE id=%s
            """,
            (new_target, disposition),
        )
        cursor.execute(
            """
            SELECT judicial_decision_id, target_role, verification_method
            FROM corpus.judicial_disposition_targets
            WHERE disposition_id=%s AND target_type='judicial_decision'
            ORDER BY target_role
            """,
            (disposition,),
        )
        targets = cursor.fetchall()
        assert (old_target, "reviewed_decision", "human_review") in targets
        assert not any(
            row[0] == old_target
            and row[1] == "affected"
            and row[2].startswith("legacy_affected_field")
            for row in targets
        )
        assert any(
            row[0] == new_target and row[1] == "affected" for row in targets
        )
