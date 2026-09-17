from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.invariant]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


# These constraints encoded law-owned categories directly in DDL. System-owned
# workflow states, provenance statuses, and structural union discriminators are
# intentionally not listed here and may remain CHECK-backed.
FORBIDDEN_LEGAL_VOCABULARY_CHECKS = {
    "case_identifiers_type_check",
    "court_aliases_kind_check",
    "court_functional_competences_function_check",
    "court_functional_competences_instance_check",
    "court_organ_aliases_kind_check",
    "court_relations_type_check",
    "courts_judicial_system_check",
    "courts_type_check",
    "decision_legal_matters_relation_type_check",
    "decision_panel_members_role_check",
    "decision_procedures_relation_type_check",
    "decision_votes_type_check",
    "judicial_officer_positions_type_check",
    "judicial_opinion_authors_authorship_role_check",
    "judicial_opinion_joiners_type_check",
    "legal_amendment_effects_type_check",
    "legal_amendment_operations_type_check",
    "legal_authorities_type_check",
    "legal_controversies_status_check",
    "legal_document_provisions_type_check",
    "legal_documents_type_check",
    "legal_instrument_authority_roles_role_check",
    "legal_instrument_events_type_check",
    "legal_instrument_version_documents_role_check",
    "legal_instrument_versions_kind_check",
    "legal_instruments_type_check",
    "legal_matter_concept_edges_relation_check",
    "legal_norm_sources_role_check",
    "legal_proceedings_status_check",
    "legal_proposition_evidence_role_check",
    "legal_proposition_relations_type_check",
    "legal_provision_lineage_type_check",
    "legal_provision_version_sources_role_check",
    "legal_provision_versions_type_check",
    "legal_relation_identities_type_check",
    "legal_relation_observations_type_check",
    "legal_tags_type_check",
    "legal_treatment_assertions_type_check",
    "party_representations_type_check",
    "procedural_relation_observations_type_check",
    "procedural_decision_relations_type_check",
    "procedural_events_type_check",
    "procedural_role_concepts_side_check",
    "procedure_concept_edges_relation_check",
    "proceeding_decisions_relation_check",
    "proceeding_identifiers_type_check",
    "proceeding_participants_side_check",
    "proceeding_party_roles_side_check",
    "territorial_units_type_check",
}


def test_law_owned_vocabularies_are_not_closed_by_check_constraints(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select con.conname
            from pg_constraint con
            join pg_class c on c.oid = con.conrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'corpus'
              and con.contype = 'c'
              and con.conname = any(%s)
            order by con.conname
            """,
            (sorted(FORBIDDEN_LEGAL_VOCABULARY_CHECKS),),
        )
        remaining = {row[0] for row in cursor.fetchall()}

    assert remaining == set(), (
        "Law-owned legal vocabularies must be extensible concept rows referenced by FK, "
        f"not CHECK enums. Remaining closed vocabularies: {sorted(remaining)}"
    )


def test_representative_legal_vocabulary_can_be_extended_without_ddl(
    connection: psycopg.Connection[Any],
) -> None:
    suffix = uuid4().hex[:10]
    court_type = f"custom_{suffix}"
    court_code = f"DO-OPEN-{suffix.upper()}"

    with connection.transaction(force_rollback=True), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.court_type_concepts(code, name, description)
            values (%s, %s, 'contract-test extension')
            """,
            (court_type, f"Custom {suffix}"),
        )
        cursor.execute(
            """
            insert into corpus.courts(
                code, name, jurisdiction, judicial_system, court_type
            ) values (
                %s, 'Tribunal de vocabulario extensible', 'República Dominicana',
                'ordinary_judiciary', %s
            )
            returning court_type
            """,
            (court_code, court_type),
        )
        assert cursor.fetchone() == (court_type,)


def test_unknown_legal_code_is_rejected_by_concept_fk(
    connection: psycopg.Connection[Any],
) -> None:
    suffix = uuid4().hex[:10]
    with (
        connection.transaction(force_rollback=True),
        connection.cursor() as cursor,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        cursor.execute(
            """
            insert into corpus.courts(
                code, name, jurisdiction, judicial_system, court_type
            ) values (
                %s, 'Tribunal con concepto inexistente', 'República Dominicana',
                'ordinary_judiciary', 'not_registered'
            )
            """,
            (f"DO-MISSING-{suffix.upper()}",),
        )
