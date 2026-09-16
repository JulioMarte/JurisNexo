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
        VALUES (%s, %s, 'República Dominicana') RETURNING id
        """,
        (f"DO-SEM-{suffix}", f"Tribunal semántico {suffix}"),
    )
    return _one(cursor)


def _case(cursor: psycopg.Cursor[Any], court_id: Any) -> Any:
    cursor.execute(
        "INSERT INTO corpus.cases (court_id) VALUES (%s) RETURNING id",
        (court_id,),
    )
    return _one(cursor)


def _instrument(cursor: psycopg.Cursor[Any], title: str) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_instruments (
            instrument_type, canonical_title, identity_status
        ) VALUES ('statute', %s, 'canonical') RETURNING id
        """,
        (title,),
    )
    return _one(cursor)


def _version(
    cursor: psycopg.Cursor[Any],
    instrument_id: Any,
    valid_from: str = "2020-01-01",
) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_instrument_versions (
            instrument_id, version_kind, valid_from,
            version_status, derivation_method
        ) VALUES (%s, 'original', %s, 'verified', 'official_primary_text')
        RETURNING id
        """,
        (instrument_id, valid_from),
    )
    return _one(cursor)


def _provision_version(
    cursor: psycopg.Cursor[Any],
    instrument_id: Any,
    version_id: Any,
) -> tuple[Any, Any]:
    cursor.execute(
        """
        INSERT INTO corpus.legal_provisions (instrument_id, identity_status)
        VALUES (%s, 'canonical') RETURNING id
        """,
        (instrument_id,),
    )
    provision_id = _one(cursor)
    cursor.execute(
        """
        INSERT INTO corpus.legal_provision_versions (
            instrument_id, instrument_version_id, provision_id,
            provision_type, label, normalized_label, content_status
        ) VALUES (
            %s, %s, %s, 'article', 'Artículo 1', 'articulo-1', 'verified'
        ) RETURNING id
        """,
        (instrument_id, version_id, provision_id),
    )
    return provision_id, _one(cursor)


def _proposition(cursor: psycopg.Cursor[Any], kind: str, text: str) -> Any:
    cursor.execute(
        """
        INSERT INTO corpus.legal_propositions (
            proposition_type, canonical_text, assertion_kind, verification_status
        ) VALUES (%s, %s, 'human_authored', 'verified') RETURNING id
        """,
        (kind, text),
    )
    return _one(cursor)


def test_bitemporal_knowledge_preserves_old_system_view(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        instrument = _instrument(cursor, "Ley bitemporal")
        version = _version(cursor, instrument)
        _, provision_version = _provision_version(cursor, instrument, version)
        cursor.execute(
            """
            INSERT INTO corpus.legal_provision_version_knowledge (
                provision_version_id, valid_from, known_from, known_to,
                text, content_status, assertion_method
            ) VALUES
                (%s, '2020-01-01', '2024-01-01Z', '2025-01-01Z',
                 'Texto conocido en 2024.', 'verified', 'official_copy'),
                (%s, '2020-01-01', '2025-01-01Z', NULL,
                 'Texto corregido desde 2025.', 'verified', 'official_correction')
            """,
            (provision_version, provision_version),
        )
        for known_at, expected in (
            ("2024-06-01Z", "Texto conocido en 2024."),
            ("2025-06-01Z", "Texto corregido desde 2025."),
        ):
            cursor.execute(
                """
                SELECT text FROM corpus.legal_provision_version_knowledge
                WHERE provision_version_id = %s
                  AND %s::timestamptz >= known_from
                  AND (known_to IS NULL OR %s::timestamptz < known_to)
                """,
                (provision_version, known_at, known_at),
            )
            assert cursor.fetchone() == (expected,)

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_provision_version_knowledge (
                    provision_version_id, known_from, known_to,
                    text, content_status, assertion_method
                ) VALUES (
                    %s, '2024-06-01Z', '2024-09-01Z',
                    'Solapamiento imposible', 'candidate', 'test'
                )
                """,
                (provision_version,),
            )


def test_taxonomy_supports_multiple_parents_and_rejects_cycles(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        ids: list[Any] = []
        for name in ("Derecho privado", "Derecho económico", "Competencia"):
            cursor.execute(
                """
                INSERT INTO corpus.legal_matter_concepts (code, name)
                VALUES (%s, %s) RETURNING id
                """,
                (f"concept_{uuid4().hex[:10]}", name),
            )
            ids.append(_one(cursor))
        private, economic, competition = ids
        for broader in (private, economic):
            cursor.execute(
                """
                INSERT INTO corpus.legal_matter_concept_edges (
                    narrower_concept_id, broader_concept_id, verification_method
                ) VALUES (%s, %s, 'human_taxonomy')
                """,
                (competition, broader),
            )
        cursor.execute(
            """
            SELECT count(*) FROM corpus.legal_matter_concept_edges
            WHERE narrower_concept_id = %s
            """,
            (competition,),
        )
        assert cursor.fetchone() == (2,)
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_matter_concept_edges (
                    narrower_concept_id, broader_concept_id, verification_method
                ) VALUES (%s, %s, 'cycle-test')
                """,
                (private, competition),
            )


def test_party_role_and_representation_are_distinct(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corpus.legal_proceedings (canonical_title)
            VALUES ('Proceso de prueba') RETURNING id
            """
        )
        proceeding = _one(cursor)
        participants: list[Any] = []
        for kind, name in (
            ("organization", "Empresa recurrente"),
            ("person", "Lic. Defensa"),
        ):
            cursor.execute(
                """
                INSERT INTO corpus.participants (participant_kind, display_name)
                VALUES (%s, %s) RETURNING id
                """,
                (kind, name),
            )
            participants.append(_one(cursor))
        party, lawyer = participants
        cursor.execute(
            """
            INSERT INTO corpus.proceeding_party_roles (
                proceeding_id, participant_id, role_type, party_side, raw_role,
                verification_status, verification_method
            ) VALUES (
                %s, %s, 'appellant', 'claimant', 'Parte recurrente',
                'verified', 'primary_text'
            ) RETURNING id
            """,
            (proceeding, party),
        )
        role = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.party_representations (
                party_role_id, representative_participant_id, representation_type,
                verification_status, verification_method
            ) VALUES (%s, %s, 'counsel', 'verified', 'primary_text')
            RETURNING party_role_id, representative_participant_id
            """,
            (role, lawyer),
        )
        assert cursor.fetchone() == (role, lawyer)


def test_panel_vote_and_separate_opinion_are_not_conflated(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _case(cursor, court)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_officers (display_name, identity_status)
            VALUES ('Jueza Disidente', 'canonical') RETURNING id
            """
        )
        officer = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.decision_panel_members (
                case_id, officer_id, role_raw, panel_role,
                verification_status, verification_method
            ) VALUES (%s, %s, 'Miembro', 'member', 'verified', 'primary_text')
            """,
            (decision, officer),
        )
        cursor.execute(
            """
            INSERT INTO corpus.judicial_opinions (
                case_id, opinion_type, author_officer_id,
                verification_status, verification_method
            ) VALUES (
                %s, 'dissenting', %s, 'verified', 'primary_text'
            ) RETURNING id
            """,
            (decision, officer),
        )
        opinion = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.decision_votes (
                case_id, officer_id, vote_type, opinion_id,
                verification_status, verification_method
            ) VALUES (
                %s, %s, 'dissenting', %s, 'verified', 'primary_text'
            )
            """,
            (decision, officer, opinion),
        )
        cursor.execute(
            """
            SELECT panel_role FROM corpus.decision_panel_members
            WHERE case_id = %s AND officer_id = %s
            """,
            (decision, officer),
        )
        assert cursor.fetchone() == ("member",)
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.decision_panel_members (
                    case_id, officer_id, role_raw, panel_role,
                    verification_status, verification_method
                ) VALUES (
                    %s, %s, 'Disidente', 'dissenting', 'verified', 'primary_text'
                )
                """,
                (_case(cursor, court), officer),
            )


def test_judicial_career_is_temporal(connection: psycopg.Connection[Any]) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        first_court = _court(cursor)
        second_court = _court(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_officers (display_name)
            VALUES ('Magistrado Carrera') RETURNING id
            """
        )
        officer = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.judicial_officer_positions (
                officer_id, court_id, position_type, valid_from, valid_to,
                verification_status, verification_method
            ) VALUES
                (%s, %s, 'judge', '2018-01-01', '2022-12-31',
                 'verified', 'official_roster'),
                (%s, %s, 'judge', '2023-01-01', NULL,
                 'verified', 'official_roster')
            """,
            (officer, first_court, officer, second_court),
        )
        cursor.execute(
            """
            SELECT count(*) FROM corpus.judicial_officer_positions
            WHERE officer_id = %s
            """,
            (officer,),
        )
        assert cursor.fetchone() == (2,)


def test_decision_finality_does_not_mutate_case_record(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        decision = _case(cursor, court)
        cursor.execute("SELECT updated_at FROM corpus.cases WHERE id = %s", (decision,))
        before = cursor.fetchone()
        cursor.execute(
            """
            INSERT INTO corpus.decision_legal_status_events (
                case_id, status_type, occurred_on, date_status,
                verification_status, verification_method
            ) VALUES (
                %s, 'final', '2025-01-15', 'verified_official_metadata',
                'verified', 'official_metadata'
            )
            """,
            (decision,),
        )
        cursor.execute("SELECT updated_at FROM corpus.cases WHERE id = %s", (decision,))
        assert cursor.fetchone() == before


def test_precedential_authority_varies_by_context(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        source_court = _court(cursor)
        other_court = _court(cursor)
        decision = _case(cursor, source_court)
        cursor.execute(
            """
            INSERT INTO corpus.precedential_authority_assertions (
                decision_id, authority_type, court_id, basis,
                verification_status, verification_method
            ) VALUES
                (%s, 'binding', %s, 'Jerarquía aplicable aquí',
                 'verified', 'human_legal_review'),
                (%s, 'persuasive', %s, 'Fuera del ámbito sólo es persuasiva',
                 'verified', 'human_legal_review')
            """,
            (decision, source_court, decision, other_court),
        )
        cursor.execute(
            """
            SELECT authority_type FROM corpus.precedential_authority_assertions
            WHERE decision_id = %s
            """,
            (decision,),
        )
        assert {row[0] for row in cursor.fetchall()} == {"binding", "persuasive"}


def test_substantive_treatment_requires_issue_context(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        court = _court(cursor)
        source = _case(cursor, court)
        target = _case(cursor, court)
        issue = _proposition(cursor, "issue", "¿Cuál es el plazo aplicable?")
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_treatment_assertions (
                    source_case_id, target_case_id, treatment_type,
                    verification_status, verification_method
                ) VALUES (
                    %s, %s, 'distinguishes', 'verified', 'human_legal_review'
                )
                """,
                (source, target),
            )
        cursor.execute(
            """
            INSERT INTO corpus.legal_treatment_assertions (
                source_case_id, target_case_id, treatment_type,
                issue_proposition_id, verification_status, verification_method
            ) VALUES (
                %s, %s, 'distinguishes', %s, 'verified', 'human_legal_review'
            ) RETURNING issue_proposition_id
            """,
            (source, target, issue),
        )
        assert cursor.fetchone() == (issue,)

        documents: list[Any] = []
        for title in ("Decisión fuente", "Decisión objetivo"):
            cursor.execute(
                """
                INSERT INTO corpus.legal_documents (
                    document_type, title, identity_status
                ) VALUES ('judicial_decision', %s, 'canonical') RETURNING id
                """,
                (title,),
            )
            documents.append(_one(cursor))
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_relations (
                    source_document_id, relation_type, target_document_id,
                    verification_method
                ) VALUES (%s, 'distinguishes', %s, 'contract_test')
                """,
                (documents[0], documents[1]),
            )


def test_provision_lineage_can_model_split(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        instrument = _instrument(cursor, "Ley con división de artículo")
        provisions: list[Any] = []
        for _ in range(3):
            cursor.execute(
                """
                INSERT INTO corpus.legal_provisions (instrument_id, identity_status)
                VALUES (%s, 'canonical') RETURNING id
                """,
                (instrument,),
            )
            provisions.append(_one(cursor))
        old, new_a, new_b = provisions
        for target in (new_a, new_b):
            cursor.execute(
                """
                INSERT INTO corpus.legal_provision_lineage (
                    from_provision_id, to_provision_id, lineage_type,
                    effective_on, verification_status, verification_method
                ) VALUES (
                    %s, %s, 'split_into', '2025-01-01',
                    'verified', 'explicit_amendment'
                )
                """,
                (old, target),
            )
        cursor.execute(
            """
            SELECT count(*) FROM corpus.legal_provision_lineage
            WHERE from_provision_id = %s AND lineage_type = 'split_into'
            """,
            (old,),
        )
        assert cursor.fetchone() == (2,)


def test_amendment_operation_rejects_invalid_coordinates(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        instrument = _instrument(cursor, "Ley objetivo")
        version = _version(cursor, instrument)
        provision, provision_version = _provision_version(cursor, instrument, version)
        cursor.execute(
            """
            INSERT INTO corpus.legal_amendment_effects (
                source_instrument_id, target_instrument_id, target_provision_id,
                effect_type, verification_status, verification_method
            ) VALUES (
                %s, %s, %s, 'replaces', 'verified', 'explicit_primary_text'
            ) RETURNING id
            """,
            (instrument, instrument, provision),
        )
        effect = _one(cursor)
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            cursor.execute(
                """
                INSERT INTO corpus.legal_amendment_operations (
                    amendment_effect_id, target_provision_version_id,
                    sequence_number, operation_type, char_start, char_end,
                    verification_method
                ) VALUES (%s, %s, 1, 'replace', 10, 5, 'contract_test')
                """,
                (effect, provision_version),
            )


def test_issuing_authority_has_normalized_identity(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        instrument = _instrument(cursor, "Ley institucional")
        cursor.execute(
            """
            INSERT INTO corpus.legal_authorities (
                authority_type, canonical_name, normalized_name, identity_status
            ) VALUES (
                'legislature', 'Congreso Nacional',
                'congreso nacional', 'canonical'
            ) RETURNING id
            """
        )
        authority = _one(cursor)
        cursor.execute(
            """
            INSERT INTO corpus.legal_instrument_authority_roles (
                instrument_id, authority_id, authority_role,
                verification_status, verification_method
            ) VALUES (%s, %s, 'enacted_by', 'verified', 'official_text')
            RETURNING instrument_id, authority_id, authority_role
            """,
            (instrument, authority),
        )
        assert cursor.fetchone() == (instrument, authority, "enacted_by")
