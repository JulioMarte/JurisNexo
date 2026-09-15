from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def _first(cursor: psycopg.Cursor[Any]) -> Any:
    row = cursor.fetchone()
    assert row is not None
    return row[0]


def test_judicial_intelligence_tables_exist(connection: psycopg.Connection[Any]) -> None:
    expected = {
        "legal_matters",
        "procedure_types",
        "judicial_proceedings",
        "judicial_proceeding_identifiers",
        "judicial_proceeding_participants",
        "case_proceedings",
        "judicial_decision_relation_observations",
        "judicial_decision_relations",
        "case_dispositions",
        "judicial_officers",
        "case_judicial_officers",
        "source_document_canonical_resolutions",
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select table_name
            from information_schema.tables
            where table_schema = 'corpus'
            """
        )
        actual = {row[0] for row in cursor.fetchall()}
    assert expected <= actual


def test_one_proceeding_can_link_multiple_decisions_and_keep_raw_parties(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.courts (code, name, jurisdiction, court_level)
            values ('SCHEMA-SCJ', 'SCJ schema test', 'República Dominicana', 'supreme')
            returning id
            """
        )
        court_id = _first(cursor)
        cursor.execute(
            """
            insert into corpus.judicial_proceedings (originating_court_id, identity_status)
            values (%s, 'canonical')
            returning id
            """,
            (court_id,),
        )
        proceeding_id = _first(cursor)
        cursor.execute(
            """
            insert into corpus.judicial_proceeding_identifiers (
                proceeding_id, identifier_type, raw_value, normalized_value, is_primary
            ) values (%s, 'expediente_number', 'Exp. 001-020-2020', '001-020-2020', true)
            """,
            (proceeding_id,),
        )
        cursor.execute(
            """
            insert into corpus.judicial_proceeding_participants (
                proceeding_id, participant_name_raw, participant_name_normalized,
                participant_kind, role_raw, role_normalized, party_side,
                verification_method, verification_status
            ) values (
                %s,
                'Compañía de Electricidad de Puerto Plata, S. A. (CEPP).',
                'compania de electricidad de puerto plata sa',
                'organization',
                'Recurrente',
                'recurrente',
                'claimant',
                'official_metadata',
                'verified'
            )
            """,
            (proceeding_id,),
        )
        cursor.execute(
            """
            insert into corpus.cases (court_id, decision_number, decision_date, decision_date_status)
            values
                (%s, 'NUM. 6', date '2020-01-29', 'verified_official_metadata'),
                (%s, 'SCJ-TEST-APPEAL', date '2021-02-01', 'verified_official_metadata')
            returning id
            """,
            (court_id, court_id),
        )
        case_ids = [row[0] for row in cursor.fetchall()]
        for index, case_id in enumerate(case_ids):
            cursor.execute(
                """
                insert into corpus.case_proceedings (
                    case_id, proceeding_id, relation_type, is_primary,
                    verification_status, verification_method
                ) values (%s, %s, 'decision_in_proceeding', %s, 'verified', 'official_metadata')
                """,
                (case_id, proceeding_id, index == 0),
            )
        cursor.execute(
            "select count(*) from corpus.case_proceedings where proceeding_id = %s",
            (proceeding_id,),
        )
        assert cursor.fetchone() == (2,)
        cursor.execute(
            """
            select participant_name_raw, role_raw, role_normalized
            from corpus.judicial_proceeding_participants
            where proceeding_id = %s
            """,
            (proceeding_id,),
        )
        assert cursor.fetchone() == (
            "Compañía de Electricidad de Puerto Plata, S. A. (CEPP).",
            "Recurrente",
            "recurrente",
        )


def test_model_relation_observation_does_not_become_verified_relation_automatically(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.courts (code, name, jurisdiction)
            values ('SCHEMA-REL', 'Relation schema test', 'República Dominicana')
            returning id
            """
        )
        court_id = _first(cursor)
        cursor.execute(
            "insert into corpus.cases (court_id) values (%s), (%s) returning id",
            (court_id, court_id),
        )
        source_case, target_case = [row[0] for row in cursor.fetchall()]
        key = hashlib.sha256(f"{source_case}:cassates:{target_case}".encode()).hexdigest()
        cursor.execute(
            """
            insert into corpus.judicial_decision_relation_observations (
                observation_key, source_case_id, relation_type, target_case_id,
                assertion_method, method_name, confidence
            ) values (%s, %s, 'cassates', %s, 'llm_extracted', 'test-model', 0.91)
            """,
            (key, source_case, target_case),
        )
        cursor.execute(
            """
            select count(*)
            from corpus.judicial_decision_relations
            where source_case_id = %s and target_case_id = %s
            """,
            (source_case, target_case),
        )
        assert cursor.fetchone() == (0,)


def test_source_record_can_resolve_to_only_one_verified_canonical_document(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_registries (code, name, institution, authority_class)
            values ('SCHEMA-SOURCE', 'SCJ source schema test', 'SCJ', 'official_primary')
            returning id
            """
        )
        registry_id = _first(cursor)
        payload = {"idExpediente": "schema-1", "fecha": "29/01/2020"}
        payload_json = json.dumps(payload, sort_keys=True)
        payload_sha = hashlib.sha256(payload_json.encode()).hexdigest()
        cursor.execute(
            """
            insert into corpus.source_documents (
                source_registry_id, source_identifier, source_collection,
                document_kind, discovery_url, artifact_availability,
                latest_source_metadata, latest_payload_sha256
            ) values (
                %s, 'schema-1', 'decisions', 'judicial_decision',
                'https://example.test/scj', 'available', %s::jsonb, %s
            ) returning id
            """,
            (registry_id, payload_json, payload_sha),
        )
        source_document_id = _first(cursor)
        cursor.execute(
            """
            insert into corpus.legal_documents (document_type, identity_status)
            values ('judicial_decision', 'canonical'), ('judicial_decision', 'canonical')
            returning id
            """
        )
        legal_document_a, legal_document_b = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            """
            insert into corpus.source_document_canonical_resolutions (
                source_document_id, legal_document_id, resolution_status,
                resolution_method, confidence, matched_on
            ) values (
                %s, %s, 'verified', 'official_identifier_match',
                1.0, '{"expediente": true}'::jsonb
            )
            """,
            (source_document_id, legal_document_a),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            cursor.execute(
                """
                insert into corpus.source_document_canonical_resolutions (
                    source_document_id, legal_document_id, resolution_status,
                    resolution_method, confidence
                ) values (%s, %s, 'verified', 'second_match', 0.99)
                """,
                (source_document_id, legal_document_b),
            )


def test_cross_scope_case_proceeding_link_is_rejected(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.scopes (visibility, organization_id)
            values ('private', gen_random_uuid())
            returning id
            """
        )
        private_scope = _first(cursor)
        cursor.execute(
            """
            insert into corpus.courts (code, name, jurisdiction)
            values ('SCHEMA-SCOPE', 'Scope schema test', 'República Dominicana')
            returning id
            """
        )
        court_id = _first(cursor)
        cursor.execute(
            "insert into corpus.cases (court_id) values (%s) returning id",
            (court_id,),
        )
        public_case = _first(cursor)
        cursor.execute(
            """
            insert into corpus.judicial_proceedings (scope_id, identity_status)
            values (%s, 'canonical')
            returning id
            """,
            (private_scope,),
        )
        private_proceeding = _first(cursor)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                """
                insert into corpus.case_proceedings (
                    case_id, proceeding_id, verification_method
                ) values (%s, %s, 'test')
                """,
                (public_case, private_proceeding),
            )


def test_structured_disposition_keeps_raw_source_text(connection: psycopg.Connection[Any]) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.courts (code, name, jurisdiction)
            values ('SCHEMA-DISP', 'Disposition schema test', 'República Dominicana')
            returning id
            """
        )
        court_id = _first(cursor)
        cursor.execute(
            "insert into corpus.cases (court_id) values (%s) returning id",
            (court_id,),
        )
        case_id = _first(cursor)
        cursor.execute(
            """
            insert into corpus.case_dispositions (
                case_id, ordinal, disposition_type, raw_text,
                extraction_method, verification_status, confidence
            ) values (
                %s, 1, 'cassated',
                'CASA la sentencia impugnada y envía el asunto por ante otra corte.',
                'primary_text_parser', 'verified', 1.0
            ) returning disposition_type, raw_text
            """,
            (case_id,),
        )
        assert cursor.fetchone() == (
            "cassated",
            "CASA la sentencia impugnada y envía el asunto por ante otra corte.",
        )
