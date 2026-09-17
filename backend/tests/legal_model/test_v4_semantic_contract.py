from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.invariant]


def _one(cursor: psycopg.Cursor[Any]) -> Any:
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def _concept(cursor: psycopg.Cursor[Any], scheme: str, code: str) -> Any:
    cursor.execute(
        """
        SELECT id FROM corpus.legal_concepts
        WHERE scheme_code=%s AND jurisdiction_code IS NULL AND code=%s
        """,
        (scheme, code),
    )
    return _one(cursor)


def _court(cursor: psycopg.Cursor[Any]) -> Any:
    suffix = uuid4().hex[:10]
    cursor.execute(
        "INSERT INTO corpus.courts(code,name,jurisdiction) VALUES (%s,%s,'DO') RETURNING id",
        (f"DO-V4-{suffix}", f"Tribunal V4 {suffix}"),
    )
    return _one(cursor)


def _decision(cursor: psycopg.Cursor[Any], court_id: Any) -> Any:
    cursor.execute(
        "INSERT INTO corpus.judicial_decisions(court_id) VALUES (%s) RETURNING id",
        (court_id,),
    )
    return _one(cursor)


def _legal_document(cursor: psycopg.Cursor[Any], title: str) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_documents(document_type,title)
        VALUES ('judicial_decision',%s) RETURNING id
        """,
        (title,),
    )
    return _one(cursor)


def _artifact_page(cursor: psycopg.Cursor[Any]) -> Any:
    suffix = uuid4().hex
    cursor.execute(
        """
        INSERT INTO corpus.source_artifacts(sha256,mime_type,byte_size,page_count)
        VALUES (%s,'application/pdf',1,1) RETURNING id
        """,
        (suffix + suffix,),
    )
    artifact_id = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.artifact_pages(
            artifact_id,page_number,extracted_text,extraction_status,extraction_method
        ) VALUES (%s,1,'evidence','native_text','native_text') RETURNING id
        """,
        (artifact_id,),
    )
    return _one(cursor)


def _proceeding(cursor: psycopg.Cursor[Any], title: str) -> Any:
    cursor.execute(
        "INSERT INTO corpus.legal_proceedings(canonical_title) VALUES (%s) RETURNING id",
        (title,),
    )
    return _one(cursor)


def _link_decision_to_proceeding(
    cursor: psycopg.Cursor[Any], proceeding_id: Any, decision_id: Any
) -> None:
    cursor.execute(
        """
        INSERT INTO corpus.proceeding_decisions(
            proceeding_id,case_id,verification_status,verification_method
        ) VALUES (%s,%s,'verified','primary_text')
        """,
        (proceeding_id, decision_id),
    )


def _party_role(cursor: psycopg.Cursor[Any], proceeding_id: Any, name: str) -> Any:
    cursor.execute(
        "INSERT INTO corpus.participants(display_name) VALUES (%s) RETURNING id",
        (name,),
    )
    participant_id = _one(cursor)
    cursor.execute("SELECT id FROM corpus.procedural_role_concepts WHERE code='appellant'")
    role_concept_id = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.proceeding_party_roles(
            proceeding_id,participant_id,role_concept_id,party_side,
            verification_status,verification_method
        ) VALUES (%s,%s,%s,'claimant','verified','primary_text') RETURNING id
        """,
        (proceeding_id, participant_id, role_concept_id),
    )
    return _one(cursor)


def _disposition(cursor: psycopg.Cursor[Any], decision_id: Any) -> Any:
    cursor.execute("SELECT id FROM corpus.disposition_concepts WHERE code='other'")
    concept_id = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.judicial_decision_dispositions(
            case_id,ordinal,disposition_concept_id,raw_text,
            extraction_method,verification_status
        ) VALUES (%s,1,%s,'FALLA','primary_text','verified') RETURNING id
        """,
        (decision_id, concept_id),
    )
    return _one(cursor)


def _action(cursor: psycopg.Cursor[Any], disposition_id: Any, effect_code: str) -> Any:
    cursor.execute(
        "SELECT id FROM corpus.disposition_effect_concepts WHERE code=%s",
        (effect_code,),
    )
    effect_id = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.judicial_disposition_actions(
            disposition_id,effect_concept_id,ordinal,
            verification_status,verification_method
        ) VALUES (%s,%s,1,'verified','primary_text') RETURNING id
        """,
        (disposition_id, effect_id),
    )
    return _one(cursor)


def test_shared_concepts_are_jurisdiction_aware_and_hierarchy_rejects_cycles(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.legal_concepts(
                scheme_code,jurisdiction_code,code,name
            ) VALUES ('factual_proposition_kind','DO','allegation','Alegacion dominicana')
            RETURNING id
            """
        )
        assert _one(cursor) is not None

        scheme = f"test_scheme_{uuid4().hex[:8]}"
        cursor.execute(
            "INSERT INTO corpus.concept_schemes(code,name) VALUES (%s,'Test scheme')",
            (scheme,),
        )
        cursor.execute(
            "INSERT INTO corpus.legal_concepts(scheme_code,code,name) VALUES (%s,'a','A') RETURNING id",
            (scheme,),
        )
        a = _one(cursor)
        cursor.execute(
            "INSERT INTO corpus.legal_concepts(scheme_code,code,name) VALUES (%s,'b','B') RETURNING id",
            (scheme,),
        )
        b = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_concept_edges(source_concept_id,relation_type,target_concept_id)
            VALUES (%s,'broader',%s)
            """,
            (a, b),
        )
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_concept_edges(
                    source_concept_id,relation_type,target_concept_id
                ) VALUES (%s,'broader',%s)
                """,
                (b, a),
            )


def test_verified_legal_issue_requires_evidence_and_can_answer_with_proposition(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_issues(
                    canonical_question,assertion_kind,verification_status,verification_method
                ) VALUES (
                    '¿Es admisible el recurso?',
                    'synthesized_interpretation','verified','llm_extracted'
                )
                """
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

        cursor.execute(
            """
            INSERT INTO corpus.legal_issues(
                canonical_question,assertion_kind,verification_method
            ) VALUES (
                '¿Es admisible el recurso?',
                'derived_from_primary_text','llm_extracted'
            ) RETURNING id
            """
        )
        issue_id = _one(cursor)
        document_id = _legal_document(cursor, "Decision de evidencia V4")
        cursor.execute(
            """
            INSERT INTO corpus.legal_issue_evidence(
                issue_id,source_document_id,exact_excerpt,extraction_method
            ) VALUES (%s,%s,'La cuestion consiste en determinar la admisibilidad.','primary_text')
            """,
            (issue_id, document_id),
        )
        cursor.execute(
            "UPDATE corpus.legal_issues SET verification_status='verified' WHERE id=%s",
            (issue_id,),
        )
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

        cursor.execute(
            """
            INSERT INTO corpus.legal_propositions(
                proposition_type,canonical_text,assertion_kind,verification_status
            ) VALUES (
                'holding','El recurso es inadmisible.',
                'derived_from_primary_text','candidate'
            ) RETURNING id
            """
        )
        proposition_id = _one(cursor)
        answers = _concept(cursor, "legal_issue_relation", "answers")
        cursor.execute(
            """
            INSERT INTO corpus.legal_issue_subjects(
                issue_id,relation_concept_id,subject_type,proposition_id,
                verification_status,verification_method
            ) VALUES (%s,%s,'proposition',%s,'verified','primary_text')
            RETURNING id
            """,
            (issue_id, answers, proposition_id),
        )
        assert _one(cursor) is not None


def test_allegation_finding_and_legal_proposition_are_distinct_identities(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        allegation_kind = _concept(cursor, "factual_proposition_kind", "allegation")
        finding_kind = _concept(cursor, "factual_proposition_kind", "finding")
        text = "La parte no fue notificada."
        cursor.execute(
            """
            INSERT INTO corpus.factual_propositions(
                kind_concept_id,canonical_text,assertion_kind,verification_method
            ) VALUES (%s,%s,'explicit_primary_text','primary_text') RETURNING id
            """,
            (allegation_kind, text),
        )
        allegation_id = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.factual_propositions(
                kind_concept_id,canonical_text,assertion_kind,verification_method
            ) VALUES (%s,%s,'derived_from_primary_text','llm_extracted') RETURNING id
            """,
            (finding_kind, text),
        )
        finding_id = _one(cursor)
        assert allegation_id != finding_id

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_propositions(
                    proposition_type,canonical_text,assertion_kind
                ) VALUES ('material_fact','No notificacion','derived_from_primary_text')
                """
            )


def test_disposition_action_supports_multiple_semantic_argument_roles(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _decision(cursor, court)
        proceeding = _proceeding(cursor, "Expediente de costas V4")
        _link_decision_to_proceeding(cursor, proceeding, decision)
        party_role = _party_role(cursor, proceeding, "Parte condenada V4")
        disposition = _disposition(cursor, decision)
        action = _action(cursor, disposition, "awards_costs_against")
        object_role = _concept(cursor, "disposition_argument_role", "object")
        amount_role = _concept(cursor, "disposition_argument_role", "amount")

        cursor.execute(
            """
            INSERT INTO corpus.judicial_disposition_action_arguments(
                disposition_id,action_id,role_concept_id,object_type,target_party_role_id,
                ordinal,verification_status,verification_method
            ) VALUES (%s,%s,%s,'party_role',%s,1,'verified','primary_text')
            """,
            (disposition, action, object_role, party_role),
        )
        cursor.execute(
            """
            INSERT INTO corpus.judicial_disposition_action_arguments(
                disposition_id,action_id,role_concept_id,object_type,numeric_value,currency_code,
                ordinal,verification_status,verification_method
            ) VALUES (%s,%s,%s,'money',5000000,'DOP',2,'verified','primary_text')
            """,
            (disposition, action, amount_role),
        )
        cursor.execute(
            "SELECT object_type FROM corpus.judicial_disposition_action_arguments "
            "WHERE action_id=%s ORDER BY ordinal",
            (action,),
        )
        assert [row[0] for row in cursor.fetchall()] == ["party_role", "money"]

        with pytest.raises(psycopg.errors.UniqueViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.judicial_disposition_action_arguments(
                    disposition_id,action_id,role_concept_id,object_type,target_party_role_id,
                    ordinal,verification_status,verification_method
                ) VALUES (%s,%s,%s,'party_role',%s,3,'verified','primary_text')
                """,
                (disposition, action, object_role, party_role),
            )

        unrelated = _proceeding(cursor, "Expediente ajeno V4")
        unrelated_role = _party_role(cursor, unrelated, "Parte ajena V4")
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.judicial_disposition_action_arguments(
                    disposition_id,action_id,role_concept_id,object_type,target_party_role_id,
                    ordinal,verification_status,verification_method
                ) VALUES (%s,%s,%s,'party_role',%s,4,'verified','primary_text')
                """,
                (disposition, action, object_role, unrelated_role),
            )


def test_entity_resolution_preserves_observed_identity_and_requires_evidence(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO corpus.legal_entities(entity_kind,canonical_name) "
            "VALUES ('person','J. Perez') RETURNING id"
        )
        observed = _one(cursor)
        cursor.execute(
            "INSERT INTO corpus.legal_entities(entity_kind,canonical_name,identity_status) "
            "VALUES ('person','Juan Perez Gomez','canonical') RETURNING id"
        )
        canonical = _one(cursor)
        same_as = _concept(cursor, "entity_identity_relation", "same_as")

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.entity_identity_assertions(
                    observed_entity_id,candidate_entity_id,relation_concept_id,
                    verification_status,verification_method
                ) VALUES (%s,%s,%s,'verified','human_legal_analysis')
                """,
                (observed, canonical, same_as),
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

        cursor.execute(
            """
            INSERT INTO corpus.entity_identity_assertions(
                observed_entity_id,candidate_entity_id,relation_concept_id,
                verification_method
            ) VALUES (%s,%s,%s,'human_legal_analysis') RETURNING id
            """,
            (observed, canonical, same_as),
        )
        assertion_id = _one(cursor)
        page_id = _artifact_page(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.entity_identity_assertion_evidence(
                assertion_id,artifact_page_id,evidence_kind,exact_excerpt
            ) VALUES (%s,%s,'manual_review','La fuente identifica a Juan Perez Gomez.')
            """,
            (assertion_id, page_id),
        )
        cursor.execute(
            "UPDATE corpus.entity_identity_assertions "
            "SET verification_status='verified' WHERE id=%s",
            (assertion_id,),
        )
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(
            """
            INSERT INTO corpus.entity_identity_resolutions(
                observed_entity_id,canonical_entity_id,supporting_assertion_id,
                verification_method
            ) VALUES (%s,%s,%s,'human_legal_analysis') RETURNING id
            """,
            (observed, canonical, assertion_id),
        )
        assert _one(cursor) is not None
        cursor.execute("SELECT count(*) FROM corpus.legal_entities WHERE id IN (%s,%s)", (observed, canonical))
        assert _one(cursor) == 2
