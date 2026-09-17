"""Replace remaining law-owned CHECK vocabularies with extensible concept FKs.

Revision ID: 0040_open_legal_vocabularies
Revises: 0039_remove_v3_legacy
Create Date: 2026-09-17

Legal categories change by jurisdiction and over time. They therefore must not
require DDL changes merely to admit a newly encountered court type, procedural
event, legal treatment, amendment operation, party side, or similar legal-world
classification.

This migration deliberately keeps the existing text code columns as the single
persisted value. Each code becomes a foreign key to an extensible concept table.
That gives JurisNexo concept rows + referential integrity without introducing a
second mirror column or breaking callers that already write stable codes.
"""

from __future__ import annotations

from alembic import op

revision = "0040_open_legal_vocabularies"
down_revision = "0039_remove_v3_legacy"
branch_labels = None
depends_on = None


# (concept table, target table, target column, old CHECK constraint, seed codes)
OPEN_VOCABULARIES: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    (
        "court_alias_kind_concepts",
        "court_aliases",
        "alias_kind",
        "court_aliases_kind_check",
        ("official_name", "abbreviation", "source_label", "historical_name", "other"),
    ),
    (
        "court_function_type_concepts",
        "court_functional_competences",
        "function_type",
        "court_functional_competences_function_check",
        (
            "original",
            "appellate",
            "cassation",
            "constitutional_review",
            "electoral_review",
            "execution",
            "administrative_review",
            "other",
        ),
    ),
    (
        "court_instance_level_concepts",
        "court_functional_competences",
        "instance_level",
        "court_functional_competences_instance_check",
        ("first", "second", "supreme", "special", "not_applicable", "other"),
    ),
    (
        "court_organ_alias_kind_concepts",
        "court_organ_aliases",
        "alias_kind",
        "court_organ_aliases_kind_check",
        ("official_name", "abbreviation", "source_label", "historical_name", "other"),
    ),
    (
        "court_relation_type_concepts",
        "court_relations",
        "relation_type",
        "court_relations_type_check",
        (
            "appeals_to",
            "reviewed_by",
            "administratively_supervised_by",
            "successor_of",
            "other",
        ),
    ),
    (
        "judicial_system_concepts",
        "courts",
        "judicial_system",
        "courts_judicial_system_check",
        (
            "ordinary_judiciary",
            "constitutional_jurisdiction",
            "electoral_jurisdiction",
            "other",
        ),
    ),
    (
        "court_type_concepts",
        "courts",
        "court_type",
        "courts_type_check",
        (
            "constitutional",
            "supreme",
            "appellate",
            "first_instance",
            "peace",
            "specialized",
            "electoral",
            "other",
        ),
    ),
    (
        "decision_matter_relation_concepts",
        "decision_legal_matters",
        "relation_type",
        "decision_legal_matters_relation_type_check",
        ("primary", "addresses", "incidental", "background", "other"),
    ),
    (
        "panel_role_concepts",
        "decision_panel_members",
        "panel_role",
        "decision_panel_members_role_check",
        ("presiding", "rapporteur", "ponente", "member", "other"),
    ),
    (
        "decision_procedure_relation_concepts",
        "decision_procedures",
        "relation_type",
        "decision_procedures_relation_type_check",
        ("primary", "uses", "reviews", "incident", "other"),
    ),
    (
        "judicial_vote_type_concepts",
        "decision_votes",
        "vote_type",
        "decision_votes_type_check",
        (
            "majority",
            "plurality",
            "concurring",
            "dissenting",
            "concurs_in_result",
            "abstained",
            "not_participating",
        ),
    ),
    (
        "judicial_officer_position_type_concepts",
        "judicial_officer_positions",
        "position_type",
        "judicial_officer_positions_type_check",
        ("judge", "chief_judge", "president", "vice_president", "substitute", "emeritus", "other"),
    ),
    (
        "judicial_authorship_role_concepts",
        "judicial_opinion_authors",
        "authorship_role",
        "judicial_opinion_authors_authorship_role_check",
        ("author", "coauthor", "ponente", "redactor", "signatory", "legacy_primary_author", "other"),
    ),
    (
        "judicial_opinion_join_type_concepts",
        "judicial_opinion_joiners",
        "join_type",
        "judicial_opinion_joiners_type_check",
        ("joins_all", "joins_part", "concurs_in_result", "dissents_in_part"),
    ),
    (
        "legal_amendment_effect_type_concepts",
        "legal_amendment_effects",
        "effect_type",
        "legal_amendment_effects_type_check",
        (
            "amends",
            "inserts",
            "replaces",
            "renumbers",
            "repeals",
            "partially_repeals",
            "suspends",
            "reinstates",
            "corrects",
            "other",
        ),
    ),
    (
        "legal_amendment_operation_type_concepts",
        "legal_amendment_operations",
        "operation_type",
        "legal_amendment_operations_type_check",
        ("insert", "delete", "replace", "move", "renumber", "whole_provision_replace"),
    ),
    (
        "legal_authority_type_concepts",
        "legal_authorities",
        "authority_type",
        "legal_authorities_type_check",
        (
            "legislature",
            "executive",
            "ministry",
            "regulator",
            "municipality",
            "court",
            "constitutional_body",
            "international_body",
            "other",
        ),
    ),
    (
        "legal_controversy_status_concepts",
        "legal_controversies",
        "status",
        "legal_controversies_status_check",
        ("unknown", "active", "closed", "dormant", "archived"),
    ),
    (
        "provision_type_concepts",
        "legal_document_provisions",
        "provision_type",
        "legal_document_provisions_type_check",
        (
            "title",
            "book",
            "chapter",
            "section",
            "article",
            "paragraph",
            "clause",
            "subclause",
            "item",
            "annex",
            "preamble",
            "other",
        ),
    ),
    (
        "legal_document_type_concepts",
        "legal_documents",
        "document_type",
        "legal_documents_type_check",
        (
            "judicial_decision",
            "constitution",
            "statute",
            "decree",
            "regulation",
            "administrative_resolution",
            "circular",
            "gazette",
            "treaty",
            "opinion",
            "order",
            "other",
        ),
    ),
    (
        "instrument_authority_role_concepts",
        "legal_instrument_authority_roles",
        "authority_role",
        "legal_instrument_authority_roles_role_check",
        (
            "enacted_by",
            "promulgated_by",
            "issued_by",
            "published_by",
            "administered_by",
            "enforced_by",
            "delegated_by",
            "other",
        ),
    ),
    (
        "legal_instrument_event_type_concepts",
        "legal_instrument_events",
        "event_type",
        "legal_instrument_events_type_check",
        (
            "adopted",
            "enacted",
            "promulgated",
            "published",
            "effective",
            "amended",
            "corrected",
            "suspended",
            "reinstated",
            "repealed",
            "expired",
            "other",
        ),
    ),
    (
        "instrument_document_role_concepts",
        "legal_instrument_version_documents",
        "document_role",
        "legal_instrument_version_documents_role_check",
        (
            "official_text",
            "official_publication",
            "consolidated_text",
            "corrected_text",
            "historical_copy",
            "editorial_text",
            "other",
        ),
    ),
    (
        "instrument_version_kind_concepts",
        "legal_instrument_versions",
        "version_kind",
        "legal_instrument_versions_kind_check",
        (
            "original",
            "amended",
            "official_consolidation",
            "editorial_consolidation",
            "corrected",
            "historical_snapshot",
            "other",
        ),
    ),
    (
        "legal_instrument_type_concepts",
        "legal_instruments",
        "instrument_type",
        "legal_instruments_type_check",
        (
            "constitution",
            "code",
            "statute",
            "decree",
            "regulation",
            "administrative_resolution",
            "circular",
            "treaty",
            "ordinance",
            "rule",
            "other",
        ),
    ),
    (
        "matter_taxonomy_relation_concepts",
        "legal_matter_concept_edges",
        "relation_type",
        "legal_matter_concept_edges_relation_check",
        ("broader", "part_of", "related"),
    ),
    (
        "legal_norm_source_role_concepts",
        "legal_norm_sources",
        "source_role",
        "legal_norm_sources_role_check",
        (
            "establishes",
            "defines",
            "amends",
            "repeals",
            "creates_exception",
            "interprets",
            "satisfies",
            "evidences",
        ),
    ),
    (
        "legal_proceeding_status_concepts",
        "legal_proceedings",
        "status",
        "legal_proceedings_status_check",
        ("unknown", "pending", "closed", "stayed", "archived"),
    ),
    (
        "legal_proposition_evidence_role_concepts",
        "legal_proposition_evidence",
        "evidence_role",
        "legal_proposition_evidence_role_check",
        ("supports", "qualifies", "contradicts", "context"),
    ),
    (
        "legal_proposition_relation_concepts",
        "legal_proposition_relations",
        "relation_type",
        "legal_proposition_relations_type_check",
        (
            "answers",
            "supports",
            "opposes",
            "qualifies",
            "limits",
            "creates_exception_to",
            "depends_on",
            "derived_from",
            "applies_to",
            "distinguishes_from",
            "supersedes",
            "contradicts",
        ),
    ),
    (
        "legal_provision_lineage_type_concepts",
        "legal_provision_lineage",
        "lineage_type",
        "legal_provision_lineage_type_check",
        (
            "continues_as",
            "renumbered_as",
            "split_into",
            "merged_into",
            "replaced_by",
            "transferred_to",
            "derived_from",
        ),
    ),
    (
        "provision_source_role_concepts",
        "legal_provision_version_sources",
        "source_role",
        "legal_provision_version_sources_role_check",
        (
            "primary_text",
            "official_consolidation",
            "editorial_consolidation",
            "correction",
            "historical_copy",
            "other",
        ),
    ),
    (
        "legal_relation_type_concepts",
        "legal_relation_identities",
        "relation_type",
        "legal_relation_identities_type_check",
        (
            "cites",
            "references",
            "authorized_by",
            "implements",
            "amends",
            "repeals",
            "partially_repeals",
            "supersedes",
            "requires",
            "satisfies",
            "exempts_from",
        ),
    ),
    (
        "legal_relation_observation_type_concepts",
        "legal_relation_observations",
        "relation_type",
        "legal_relation_observations_type_check",
        (
            "cites",
            "references",
            "interprets",
            "applies",
            "declines_to_apply",
            "follows",
            "distinguishes",
            "overrules",
            "authorized_by",
            "implements",
            "amends",
            "repeals",
            "partially_repeals",
            "supersedes",
            "conflicts_with",
            "consistent_with",
            "requires",
            "satisfies",
            "exempts_from",
        ),
    ),
    (
        "legal_tag_type_concepts",
        "legal_tags",
        "tag_type",
        "legal_tags_type_check",
        ("topic", "doctrine", "practice_area", "industry", "procedure", "institution", "other"),
    ),
    (
        "legal_treatment_type_concepts",
        "legal_treatment_assertions",
        "treatment_type",
        "legal_treatment_assertions_type_check",
        (
            "cites",
            "references",
            "interprets",
            "applies",
            "declines_to_apply",
            "follows",
            "distinguishes",
            "limits",
            "questions",
            "criticizes",
            "overrules",
            "abrogates",
            "conflicts_with",
            "consistent_with",
        ),
    ),
    (
        "representation_type_concepts",
        "party_representations",
        "representation_type",
        "party_representations_type_check",
        (
            "counsel",
            "lead_counsel",
            "public_defender",
            "attorney_in_fact",
            "government_counsel",
            "guardian_ad_litem",
            "self_represented",
            "other",
        ),
    ),
    (
        "procedural_decision_relation_type_concepts",
        "procedural_decision_relation_observations",
        "relation_type",
        "procedural_relation_observations_type_check",
        (
            "reviews",
            "affirms",
            "reverses",
            "vacates",
            "modifies",
            "remands",
            "cassates",
            "partially_cassates",
            "orders_new_trial",
            "enforces",
            "other",
        ),
    ),
    (
        "procedural_decision_relation_type_concepts",
        "procedural_decision_relations",
        "relation_type",
        "procedural_decision_relations_type_check",
        (
            "reviews",
            "affirms",
            "reverses",
            "vacates",
            "modifies",
            "remands",
            "cassates",
            "partially_cassates",
            "orders_new_trial",
            "enforces",
            "other",
        ),
    ),
    (
        "procedural_event_type_concepts",
        "procedural_events",
        "event_type",
        "procedural_events_type_check",
        (
            "filing",
            "service",
            "hearing",
            "motion",
            "appeal",
            "cassation_filing",
            "constitutional_review_filing",
            "evidence_submission",
            "opinion_submission",
            "interlocutory_order",
            "decision_issued",
            "remand",
            "settlement",
            "withdrawal",
            "stay",
            "execution",
            "transfer",
            "other",
        ),
    ),
    (
        "party_side_concepts",
        "procedural_role_concepts",
        "default_party_side",
        "procedural_role_concepts_side_check",
        ("claimant", "respondent", "neutral", "state", "other"),
    ),
    (
        "procedure_taxonomy_relation_concepts",
        "procedure_concept_edges",
        "relation_type",
        "procedure_concept_edges_relation_check",
        ("broader", "part_of", "related"),
    ),
    (
        "proceeding_decision_relation_concepts",
        "proceeding_decisions",
        "relation_type",
        "proceeding_decisions_relation_check",
        (
            "decision_in_proceeding",
            "reviews_proceeding",
            "consolidates_proceeding",
            "arises_from_proceeding",
        ),
    ),
    (
        "proceeding_identifier_type_concepts",
        "proceeding_identifiers",
        "identifier_type",
        "proceeding_identifiers_type_check",
        ("expediente_number", "docket_number", "legacy_docket_number", "source_specific_id", "other"),
    ),
    (
        "party_side_concepts",
        "proceeding_participants",
        "party_side",
        "proceeding_participants_side_check",
        ("claimant", "respondent", "neutral", "other"),
    ),
    (
        "party_side_concepts",
        "proceeding_party_roles",
        "party_side",
        "proceeding_party_roles_side_check",
        ("claimant", "respondent", "neutral", "state", "other"),
    ),
    (
        "territorial_unit_type_concepts",
        "territorial_units",
        "unit_type",
        "territorial_units_type_check",
        ("country", "province", "municipality", "district", "judicial_district", "region", "other"),
    ),
    (
        "case_identifier_type_concepts",
        "case_identifiers",
        "identifier_type",
        "case_identifiers_type_check",
        ("decision_number", "docket_number", "legacy_docket_number", "source_specific_id", "other"),
    ),
)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _concept_name(code: str) -> str:
    return code.replace("_", " ").strip().title()


def _create_concept_table(table: str, codes: tuple[str, ...]) -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS corpus.{table} (
            code text PRIMARY KEY,
            name text NOT NULL,
            description text,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT {table}_code_check CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT {table}_name_nonempty CHECK (btrim(name) <> '')
        )
        """
    )
    values_sql = ", ".join(
        f"({_sql_literal(code)}, {_sql_literal(_concept_name(code))})" for code in codes
    )
    op.execute(
        f"INSERT INTO corpus.{table}(code,name) VALUES {values_sql} "
        "ON CONFLICT (code) DO NOTHING"
    )


def upgrade() -> None:
    created: set[str] = set()
    for concept_table, target_table, column, old_check, codes in OPEN_VOCABULARIES:
        if concept_table not in created:
            _create_concept_table(concept_table, codes)
            created.add(concept_table)
        else:
            values_sql = ", ".join(
                f"({_sql_literal(code)}, {_sql_literal(_concept_name(code))})" for code in codes
            )
            op.execute(
                f"INSERT INTO corpus.{concept_table}(code,name) VALUES {values_sql} "
                "ON CONFLICT (code) DO NOTHING"
            )

        op.execute(f"ALTER TABLE corpus.{target_table} DROP CONSTRAINT IF EXISTS {old_check}")
        fk_name = f"{target_table}_{column}_concept_fkey"
        op.execute(
            f"ALTER TABLE corpus.{target_table} ADD CONSTRAINT {fk_name} "
            f"FOREIGN KEY ({column}) REFERENCES corpus.{concept_table}(code)"
        )
        op.execute(
            f"COMMENT ON COLUMN corpus.{target_table}.{column} IS "
            f"'Extensible legal-domain code; FK to corpus.{concept_table}(code). Adding a legal category requires data, not DDL.'"
        )

    op.execute(
        "COMMENT ON SCHEMA corpus IS "
        "'JurisNexo canonical legal corpus. Law-owned vocabularies use extensible concept rows; CHECK enums are reserved for system/structural mechanics.'"
    )


def downgrade() -> None:
    # The downgrade reconstructs the previous closed vocabularies. It is intended
    # only for schema rollback before data introduces extension codes.
    for concept_table, target_table, column, old_check, codes in reversed(OPEN_VOCABULARIES):
        fk_name = f"{target_table}_{column}_concept_fkey"
        op.execute(f"ALTER TABLE corpus.{target_table} DROP CONSTRAINT IF EXISTS {fk_name}")
        literals = ", ".join(_sql_literal(code) for code in codes)
        op.execute(
            f"ALTER TABLE corpus.{target_table} ADD CONSTRAINT {old_check} "
            f"CHECK ({column} IN ({literals}))"
        )

    for concept_table in reversed(tuple(dict.fromkeys(item[0] for item in OPEN_VOCABULARIES))):
        op.execute(f"DROP TABLE IF EXISTS corpus.{concept_table}")
