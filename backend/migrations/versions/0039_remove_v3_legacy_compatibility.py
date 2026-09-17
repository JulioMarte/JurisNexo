"""Remove pre-ingestion legal compatibility surfaces and finish open vocabularies.

Revision ID: 0039_remove_v3_legacy
Revises: 0038_cleanup_v3_backfill
Create Date: 2026-09-17

Legal Reality V3 introduced canonical concept identities but deliberately kept
text mirrors and synchronization triggers for compatibility. JurisNexo is
still before mass ingestion, so carrying those duplicate write surfaces into
the long-lived schema would make the physical model less truthful than the
conceptual model.

This migration makes concept FKs and explicit relation tables the only writable
truth for the affected legal categories and removes V2 scalar compatibility
fields after their canonical relations have already been backfilled.
"""

from alembic import op

revision = "0039_remove_v3_legacy"
down_revision = "0038_cleanup_v3_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _open_controversy_membership_vocabulary()
    _remove_renamed_object_compatibility_views()
    _remove_v2_scalar_compatibility()
    _remove_opinion_type_mirror()
    _remove_judicial_stance_mirror()
    _remove_judicial_authority_mirror_and_alias()
    _remove_judicial_event_mirror()
    _remove_disposition_compatibility_surfaces()
    _remove_adjudicative_act_compatibility_default()


def _open_controversy_membership_vocabulary() -> None:
    op.execute("""
        CREATE TABLE corpus.controversy_membership_role_concepts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            description text,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            broader_concept_id uuid REFERENCES corpus.controversy_membership_role_concepts(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CHECK (btrim(name) <> ''),
            CHECK (broader_concept_id IS NULL OR broader_concept_id <> id)
        )
    """)
    op.execute("""
        INSERT INTO corpus.controversy_membership_role_concepts(code,name) VALUES
        ('originating','Originating proceeding'),
        ('review','Review proceeding'),
        ('enforcement','Enforcement proceeding'),
        ('incident','Incidental proceeding'),
        ('related','Related proceeding'),
        ('other','Other litigation-family role')
    """)
    op.execute(
        "ALTER TABLE corpus.controversy_proceedings "
        "ADD COLUMN relation_concept_id uuid"
    )
    op.execute("""
        UPDATE corpus.controversy_proceedings cp
        SET relation_concept_id=c.id
        FROM corpus.controversy_membership_role_concepts c
        WHERE c.code=cp.relation_type
    """)
    op.execute(
        "ALTER TABLE corpus.controversy_proceedings "
        "ALTER COLUMN relation_concept_id SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE corpus.controversy_proceedings "
        "ADD CONSTRAINT controversy_proceedings_relation_concept_fkey "
        "FOREIGN KEY (relation_concept_id) "
        "REFERENCES corpus.controversy_membership_role_concepts(id)"
    )
    op.execute(
        "CREATE INDEX controversy_proceedings_relation_concept_idx "
        "ON corpus.controversy_proceedings(relation_concept_id)"
    )
    op.execute(
        "ALTER TABLE corpus.controversy_proceedings "
        "DROP CONSTRAINT controversy_proceedings_relation_type_check"
    )
    op.execute(
        "ALTER TABLE corpus.controversy_proceedings DROP COLUMN relation_type"
    )
    op.execute("""
        COMMENT ON TABLE corpus.controversy_membership_role_concepts IS
        'Open legal vocabulary for a proceeding role inside a litigation family. Procedural ancestry belongs exclusively in proceeding_relations.'
    """)


def _remove_renamed_object_compatibility_views() -> None:
    # 0026 kept old relation names as views after canonical table renames.
    # Do not rebuild them over V3: that would continue exposing obsolete names
    # to humans, agents and application callers.
    op.execute("DROP VIEW IF EXISTS corpus.cases")
    op.execute("DROP VIEW IF EXISTS corpus.case_dispositions")


def _remove_v2_scalar_compatibility() -> None:
    # 0033 already backfilled these scalar conveniences into their canonical
    # N:N relation tables. Keeping both sides writable would preserve duplicate
    # legal truth indefinitely.
    op.execute(
        "DROP TRIGGER IF EXISTS judicial_decisions_sync_legacy_classification "
        "ON corpus.judicial_decisions"
    )
    op.execute("DROP FUNCTION IF EXISTS corpus.sync_legacy_decision_classification()")
    op.execute(
        "ALTER TABLE corpus.judicial_decisions "
        "DROP COLUMN IF EXISTS legal_matter_concept_id"
    )
    op.execute(
        "ALTER TABLE corpus.judicial_decisions "
        "DROP COLUMN IF EXISTS procedure_concept_id"
    )

    op.execute(
        "DROP TRIGGER IF EXISTS legal_proceedings_sync_legacy_controversy "
        "ON corpus.legal_proceedings"
    )
    op.execute("DROP FUNCTION IF EXISTS corpus.sync_legacy_proceeding_controversy()")
    op.execute(
        "ALTER TABLE corpus.legal_proceedings DROP COLUMN IF EXISTS controversy_id"
    )

    op.execute(
        "DROP TRIGGER IF EXISTS judicial_opinions_sync_legacy_author "
        "ON corpus.judicial_opinions"
    )
    op.execute("DROP FUNCTION IF EXISTS corpus.sync_legacy_opinion_author()")
    op.execute(
        "ALTER TABLE corpus.judicial_opinions DROP COLUMN IF EXISTS author_officer_id"
    )


def _remove_opinion_type_mirror() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS judicial_opinions_sync_type_concept "
        "ON corpus.judicial_opinions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS corpus.sync_judicial_opinion_type_concept()"
    )
    op.execute(
        "ALTER TABLE corpus.judicial_opinions DROP COLUMN IF EXISTS opinion_type"
    )


def _remove_judicial_stance_mirror() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS judicial_vote_stances_sync_concept "
        "ON corpus.judicial_vote_stances"
    )
    op.execute("DROP FUNCTION IF EXISTS corpus.sync_judicial_stance_concept()")
    op.execute(
        "ALTER TABLE corpus.judicial_vote_stances DROP COLUMN IF EXISTS stance_type"
    )


def _remove_judicial_authority_mirror_and_alias() -> None:
    op.execute("DROP VIEW IF EXISTS corpus.precedential_authority_assertions")
    op.execute(
        "DROP TRIGGER IF EXISTS judicial_authority_assertions_sync_effect_concept "
        "ON corpus.judicial_authority_assertions"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS corpus.sync_judicial_authority_effect_concept()"
    )
    op.execute(
        "ALTER TABLE corpus.judicial_authority_assertions "
        "DROP COLUMN IF EXISTS authority_type"
    )


def _remove_judicial_event_mirror() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS decision_legal_status_events_sync_type_concept "
        "ON corpus.decision_legal_status_events"
    )
    op.execute("DROP FUNCTION IF EXISTS corpus.sync_judicial_event_type_concept()")
    # This overlap guard predates concept identity and therefore must be
    # rewritten before status_type disappears.
    op.execute("""
        CREATE OR REPLACE FUNCTION corpus.reject_decision_status_knowledge_overlap()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(
                concat_ws(':', NEW.case_id, NEW.event_type_concept_id, NEW.occurred_on),
                2805
            ));
            IF EXISTS (
                SELECT 1 FROM corpus.decision_legal_status_events k
                WHERE k.id <> NEW.id
                  AND k.case_id = NEW.case_id
                  AND k.event_type_concept_id = NEW.event_type_concept_id
                  AND k.occurred_on IS NOT DISTINCT FROM NEW.occurred_on
                  AND tstzrange(k.known_from, k.known_to, '[)')
                      && tstzrange(NEW.known_from, NEW.known_to, '[)')
            ) THEN
                RAISE EXCEPTION 'overlapping decision-event knowledge interval'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "ALTER TABLE corpus.decision_legal_status_events "
        "DROP COLUMN IF EXISTS status_type"
    )


def _remove_disposition_compatibility_surfaces() -> None:
    # Both views were introduced only to preserve the pre-0035 claim-only API.
    # Drop them explicitly instead of using CASCADE so any unexpected dependent
    # object still blocks the migration and forces an intentional review.
    op.execute("DROP VIEW IF EXISTS corpus.disposition_claim_effects")
    op.execute("DROP VIEW IF EXISTS corpus.claim_effect_concepts")
    op.execute(
        "DROP FUNCTION IF EXISTS corpus.validate_disposition_claim_membership()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS disposition_targets_prepare_action "
        "ON corpus.disposition_targets"
    )
    op.execute("DROP FUNCTION IF EXISTS corpus.prepare_disposition_target_action()")
    op.execute(
        "ALTER TABLE corpus.disposition_targets "
        "DROP COLUMN IF EXISTS effect_concept_id"
    )
    op.execute("""
        COMMENT ON TABLE corpus.disposition_targets IS
        'Targets of a canonical judicial_disposition_action. The action owns the legal effect; targets do not duplicate it.'
    """)


def _remove_adjudicative_act_compatibility_default() -> None:
    op.execute(
        "ALTER TABLE corpus.judicial_decisions "
        "ALTER COLUMN act_type_concept_id DROP DEFAULT"
    )
    op.execute(
        "ALTER TABLE corpus.judicial_decisions "
        "ALTER COLUMN act_type_concept_id DROP NOT NULL"
    )
    op.execute("DROP FUNCTION IF EXISTS corpus.default_adjudicative_act_type()")
    op.execute("""
        COMMENT ON COLUMN corpus.judicial_decisions.act_type_concept_id IS
        'Canonical juridical act form when known. NULL means not yet classified; no compatibility default fabricates a legal classification.'
    """)


def downgrade() -> None:
    raise RuntimeError(
        "0039 intentionally removes pre-ingestion compatibility write surfaces; "
        "downgrade would recreate duplicate legal truth"
    )
