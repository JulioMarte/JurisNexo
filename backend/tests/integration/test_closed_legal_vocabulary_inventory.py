from __future__ import annotations

import os
import re
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


# These are law-owned categorical columns opened by revision 0040. The durable
# contract is their physical shape (extensible FK-backed code), not a particular
# historical CHECK-constraint name.
LAW_OWNED_COLUMNS = {
    ("case_identifiers", "identifier_type"),
    ("court_aliases", "alias_kind"),
    ("court_functional_competences", "function_type"),
    ("court_functional_competences", "instance_level"),
    ("court_organ_aliases", "alias_kind"),
    ("court_relations", "relation_type"),
    ("courts", "judicial_system"),
    ("courts", "court_type"),
    ("decision_legal_matters", "relation_type"),
    ("decision_panel_members", "panel_role"),
    ("decision_procedures", "relation_type"),
    ("decision_votes", "vote_type"),
    ("judicial_officer_positions", "position_type"),
    ("judicial_opinion_authors", "authorship_role"),
    ("judicial_opinion_joiners", "join_type"),
    ("legal_amendment_effects", "effect_type"),
    ("legal_amendment_operations", "operation_type"),
    ("legal_authorities", "authority_type"),
    ("legal_controversies", "status"),
    ("legal_document_provisions", "provision_type"),
    ("legal_provision_versions", "provision_type"),
    ("legal_documents", "document_type"),
    ("legal_instrument_authority_roles", "authority_role"),
    ("legal_instrument_events", "event_type"),
    ("legal_instrument_version_documents", "document_role"),
    ("legal_instrument_versions", "version_kind"),
    ("legal_instruments", "instrument_type"),
    ("legal_matter_concept_edges", "relation_type"),
    ("legal_norm_sources", "source_role"),
    ("legal_proceedings", "status"),
    ("legal_proposition_evidence", "evidence_role"),
    ("legal_proposition_relations", "relation_type"),
    ("legal_provision_lineage", "lineage_type"),
    ("legal_provision_version_sources", "source_role"),
    ("legal_relation_identities", "relation_type"),
    ("legal_relation_observations", "relation_type"),
    ("legal_tags", "tag_type"),
    ("legal_treatment_assertions", "treatment_type"),
    ("party_representations", "representation_type"),
    ("procedural_decision_relation_observations", "relation_type"),
    ("procedural_decision_relations", "relation_type"),
    ("procedural_events", "event_type"),
    ("procedural_role_concepts", "default_party_side"),
    ("procedure_concept_edges", "relation_type"),
    ("proceeding_decisions", "relation_type"),
    ("proceeding_identifiers", "identifier_type"),
    ("proceeding_participants", "party_side"),
    ("proceeding_party_roles", "party_side"),
    ("territorial_units", "unit_type"),
}


# Retain the historical-name check as a readable diagnostic, but it is no
# longer the only protection: the tests below inspect column/FK/check shape.
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


def test_historical_law_owned_enum_constraints_are_absent(
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
        "Historical law-owned CHECK enums must not return: "
        f"{sorted(remaining)}"
    )


def test_every_open_law_owned_code_is_fk_backed(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select src.relname, a.attname
            from pg_constraint con
            join pg_class src on src.oid = con.conrelid
            join pg_namespace ns on ns.oid = src.relnamespace
            cross join lateral unnest(con.conkey) as key(attnum)
            join pg_attribute a on a.attrelid = src.oid and a.attnum = key.attnum
            join pg_class dst on dst.oid = con.confrelid
            join pg_namespace dns on dns.oid = dst.relnamespace
            where ns.nspname = 'corpus'
              and dns.nspname = 'corpus'
              and con.contype = 'f'
            """
        )
        fk_backed = {(table_name, column_name) for table_name, column_name in cursor.fetchall()}

    missing = LAW_OWNED_COLUMNS - fk_backed
    assert missing == set(), (
        "Every law-owned canonical code must be referentially backed by an extensible "
        f"registry; missing FK columns: {sorted(missing)}"
    )


def test_open_law_owned_columns_are_not_reclosed_under_new_constraint_names(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select c.relname, con.conname, pg_get_constraintdef(con.oid)
            from pg_constraint con
            join pg_class c on c.oid = con.conrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'corpus' and con.contype = 'c'
            order by c.relname, con.conname
            """
        )
        checks = cursor.fetchall()

    closed_enums: list[tuple[str, str, str]] = []
    for table_name, constraint_name, definition in checks:
        columns = {column for table, column in LAW_OWNED_COLUMNS if table == table_name}
        normalized = " ".join(definition.lower().split())
        for column in columns:
            # PostgreSQL renders `col IN (...)` as `col = ANY (ARRAY[...])`.
            # Only reject a CHECK whose predicate is itself the closed vocabulary;
            # compound semantic/context checks referring to registered codes remain valid.
            enum_pattern = re.compile(
                rf"^check \(\(?\(?{re.escape(column.lower())}\)?(?:)::[a-z ]+)?\s*=\s*any\s*\(array\["
            )
            if enum_pattern.search(normalized):
                closed_enums.append((table_name, constraint_name, definition))

    assert closed_enums == [], (
        "Law-owned vocabularies cannot be reclosed by renaming the CHECK constraint. "
        f"Closed enum predicates found: {closed_enums}"
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
