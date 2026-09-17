from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

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


def _court(cursor: psycopg.Cursor[Any], suffix: str) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.courts (code, name, jurisdiction)
        VALUES (%s, %s, 'República Dominicana')
        RETURNING id
        """,
        (f"DO-TEST-{suffix}", f"Tribunal de prueba {suffix}"),
    )
    return _one(cursor)


def _decision(
    cursor: psycopg.Cursor[Any],
    court_id: Any,
    *,
    scope_id: Any | None = None,
) -> Any:
    if scope_id is None:
        cursor.execute(
            """
            INSERT INTO corpus.judicial_decisions (court_id)
            VALUES (%s) RETURNING id
            """,
            (court_id,),
        )
    else:
        cursor.execute(
            """
            INSERT INTO corpus.judicial_decisions (court_id, scope_id)
            VALUES (%s, %s) RETURNING id
            """,
            (court_id, scope_id),
        )
    return _one(cursor)


def test_proceeding_can_group_multiple_decisions_and_preserve_raw_party_role(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court_id = _court(cursor, uuid4().hex[:8])
        first_decision = _decision(cursor, court_id)
        second_decision = _decision(cursor, court_id)
        cursor.execute(
            """
            INSERT INTO corpus.legal_proceedings (
                originating_court_id, canonical_title, identity_status
            ) VALUES (%s, 'Expediente de prueba', 'canonical')
            RETURNING id
            """,
            (court_id,),
        )
        proceeding_id = _one(cursor)
        for ordinal, decision_id in enumerate(
            (first_decision, second_decision),
            start=1,
        ):
            cursor.execute(
                """
                INSERT INTO corpus.proceeding_decisions (
                    proceeding_id, case_id, procedural_stage, ordinal,
                    is_primary, verification_status, verification_method
                ) VALUES (%s, %s, %s, %s, %s, 'verified', 'contract_test')
                """,
                (
                    proceeding_id,
                    decision_id,
                    "first_instance" if ordinal == 1 else "appeal",
                    ordinal,
                    ordinal == 2,
                ),
            )
        cursor.execute(
            """
            INSERT INTO corpus.participants (
                participant_kind, display_name, normalized_name
            ) VALUES (
                'organization', 'Compañía Ejemplo, S.R.L.',
                'compania ejemplo srl'
            ) RETURNING id
            """
        )
        participant_id = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.proceeding_participants (
                proceeding_id, participant_id, participant_name_raw,
                role_raw, role_normalized, party_side,
                verification_status, verification_method
            ) VALUES (
                %s, %s, 'Compañía Ejemplo, S.R.L.',
                'Parte recurrente', 'recurrente', 'claimant',
                'verified', 'official_metadata'
            )
            """,
            (proceeding_id, participant_id),
        )
        cursor.execute(
            """
            SELECT count(*) FROM corpus.proceeding_decisions
            WHERE proceeding_id = %s
            """,
            (proceeding_id,),
        )
        assert cursor.fetchone() == (2,)
        cursor.execute(
            """
            SELECT participant_name_raw, role_raw, role_normalized
            FROM corpus.proceeding_participants
            WHERE proceeding_id = %s
            """,
            (proceeding_id,),
        )
        assert cursor.fetchone() == (
            "Compañía Ejemplo, S.R.L.",
            "Parte recurrente",
            "recurrente",
        )


def test_procedural_observation_does_not_become_canonical_relation(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court_id = _court(cursor, uuid4().hex[:8])
        source_decision = _decision(cursor, court_id)
        target_decision = _decision(cursor, court_id)
        key = hashlib.sha256(
            f"{source_decision}:{target_decision}:reviews".encode()
        ).hexdigest()
        cursor.execute(
            """
            INSERT INTO corpus.procedural_decision_relation_observations (
                observation_key, source_case_id, relation_type, target_case_id,
                assertion_method, method_name, confidence
            ) VALUES (
                %s, %s, 'reviews', %s,
                'llm_extracted', 'agent-v1', 0.81
            )
            """,
            (key, source_decision, target_decision),
        )
        cursor.execute(
            """
            SELECT count(*)
            FROM corpus.procedural_decision_relations
            WHERE source_case_id = %s AND target_case_id = %s
            """,
            (source_decision, target_decision),
        )
        assert cursor.fetchone() == (0,)


def test_disposition_preserves_exact_source_text_and_normalization_is_separate(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court_id = _court(cursor, uuid4().hex[:8])
        decision_id = _decision(cursor, court_id)
        raw_text = "PRIMERO: CASA PARCIALMENTE la sentencia impugnada."
        cursor.execute(
            """
            SELECT id FROM corpus.disposition_concepts
            WHERE code = 'partially_cassated'
            """
        )
        concept_id = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_decision_dispositions (
                case_id, ordinal, disposition_concept_id,
                raw_text, normalized_text,
                extraction_method, verification_status
            ) VALUES (
                %s, 1, %s, %s, %s, 'llm_agent', 'candidate'
            ) RETURNING raw_text, normalized_text
            """,
            (
                decision_id,
                concept_id,
                raw_text,
                "casa parcialmente la sentencia",
            ),
        )
        assert cursor.fetchone() == (
            raw_text,
            "casa parcialmente la sentencia",
        )


def test_normalized_matter_relation_does_not_overwrite_source_matter(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court_id = _court(cursor, uuid4().hex[:8])
        cursor.execute(
            """
            INSERT INTO corpus.legal_matter_concepts (code, name)
            VALUES (%s, 'Laboral')
            RETURNING id
            """,
            (f"labor_{uuid4().hex[:8]}",),
        )
        concept_id = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_decisions (court_id, matter)
            VALUES (%s, 'Materia Laboral / Recurso de Casación')
            RETURNING id, matter
            """,
            (court_id,),
        )
        decision_id, raw_matter = cursor.fetchone() or (None, None)
        assert raw_matter == "Materia Laboral / Recurso de Casación"
        cursor.execute(
            """
            INSERT INTO corpus.decision_legal_matters(
                decision_id,legal_matter_concept_id,relation_type,
                verification_status,verification_method
            ) VALUES (%s,%s,'addresses','verified','human_review')
            RETURNING legal_matter_concept_id
            """,
            (decision_id, concept_id),
        )
        assert cursor.fetchone() == (concept_id,)
        cursor.execute(
            "SELECT matter FROM corpus.judicial_decisions WHERE id=%s",
            (decision_id,),
        )
        assert cursor.fetchone() == ("Materia Laboral / Recurso de Casación",)


def test_analysis_observation_accepts_unknown_json_without_promoting_it(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court_id = _court(cursor, uuid4().hex[:8])
        decision_id = _decision(cursor, court_id)
        payload = {
            "unexpected_pattern": (
                "La sala exige una secuencia probatoria no modelada todavía"
            ),
            "candidate_dimension": "burden_shift_sequence",
            "steps": ["alegación", "prueba inicial", "desplazamiento de carga"],
        }
        evidence = [
            {
                "case_page_id": str(uuid4()),
                "excerpt": "fragmento observado",
            }
        ]
        key = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        cursor.execute(
            """
            INSERT INTO corpus.analysis_observations (
                observation_key, subject_type, case_id, observation_type,
                payload, evidence, producer_type, producer_name,
                model_name, analysis_run_id, schema_hint, confidence
            ) VALUES (
                %s, 'case', %s, 'unmodeled_legal_pattern',
                %s, %s, 'llm_agent', 'deep-case-analysis',
                'test-model', 'run-123',
                'candidate:burden_shift_sequence', 0.73
            )
            RETURNING status, payload, promoted_to_schema
            """,
            (key, decision_id, Jsonb(payload), Jsonb(evidence)),
        )
        result = cursor.fetchone() or (None, None, None)
        status, stored_payload, promoted_to = result
        assert status == "observed"
        assert stored_payload == payload
        assert promoted_to is None


def test_analysis_observation_rejects_non_object_payload(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        key = hashlib.sha256(uuid4().bytes).hexdigest()
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                INSERT INTO corpus.analysis_observations (
                    observation_key, subject_type, observation_type,
                    payload, producer_name
                ) VALUES (
                    %s, 'corpus', 'bad_payload', %s, 'contract-test'
                )
                """,
                (key, Jsonb(["not", "an", "object"])),
            )


def test_cross_scope_case_to_proceeding_link_is_rejected(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court_id = _court(cursor, uuid4().hex[:8])
        organization_id = uuid4()
        cursor.execute(
            """
            INSERT INTO corpus.scopes (visibility, organization_id)
            VALUES ('private', %s)
            RETURNING id
            """,
            (organization_id,),
        )
        private_scope = _one(cursor)
        private_decision = _decision(
            cursor,
            court_id,
            scope_id=private_scope,
        )
        cursor.execute(
            """
            INSERT INTO corpus.legal_proceedings (canonical_title)
            VALUES ('Público') RETURNING id
            """
        )
        public_proceeding = _one(cursor)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                INSERT INTO corpus.proceeding_decisions (
                    scope_id, proceeding_id, case_id,
                    verification_status, verification_method
                ) VALUES (
                    %s, %s, %s, 'candidate', 'contract_test'
                )
                """,
                (private_scope, public_proceeding, private_decision),
            )


def test_proceeding_identifier_is_idempotent_when_source_registry_is_null(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.legal_proceedings (canonical_title)
            VALUES ('Expediente') RETURNING id
            """
        )
        proceeding_id = _one(cursor)
        statement = """
            INSERT INTO corpus.proceeding_identifiers (
                proceeding_id, identifier_type, raw_value, normalized_value
            ) VALUES (%s, 'expediente_number', 'EXP. 123', 'exp123')
        """
        cursor.execute(statement, (proceeding_id,))
        with pytest.raises(psycopg.errors.UniqueViolation):
            cursor.execute(statement, (proceeding_id,))
