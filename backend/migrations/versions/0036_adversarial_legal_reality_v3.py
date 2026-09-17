"""Adversarial Legal Reality V3.

Revision ID: 0036_legal_reality_v3
Revises: 0035_extensible_judicial
Create Date: 2026-09-16

Implements the pre-ingestion adversarial review: explicit proceeding ancestry,
cross-instance claim lineage, extensible adjudicative/event concepts, and a
separate normalized disposition-action layer.
"""

from alembic import op

revision = "0036_legal_reality_v3"
down_revision = "0035_extensible_judicial"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"
STATUS = "'candidate','verified','conflicting','rejected','superseded'"


def upgrade() -> None:
    _procedural_graph()
    _claim_graph()
    _adjudicative_act_types()
    _judicial_event_types()
    _disposition_actions()
    _narrow_controversy_membership()


def _concept_table(name: str) -> None:
    op.execute(f"""
        CREATE TABLE corpus.{name} (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            description text,
            jurisdiction_code text REFERENCES corpus.jurisdictions(code),
            broader_concept_id uuid REFERENCES corpus.{name}(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CHECK (btrim(name) <> ''),
            CHECK (broader_concept_id IS NULL OR broader_concept_id <> id)
        )
    """)


def _procedural_graph() -> None:
    _concept_table("proceeding_relation_concepts")
    op.execute("ALTER TABLE corpus.proceeding_relation_concepts ADD COLUMN is_symmetric boolean NOT NULL DEFAULT false")
    op.execute("""
        INSERT INTO corpus.proceeding_relation_concepts(code,name,is_symmetric) VALUES
        ('appeal_of','Appeal of',false), ('cassation_of','Cassation of',false),
        ('review_of','Review of',false), ('constitutional_review_of','Constitutional review of',false),
        ('incident_to','Incident to',false), ('remand_from','Remand from',false),
        ('continuation_of','Continuation of',false), ('enforcement_of','Enforcement of',false),
        ('reopened_from','Reopened from',false), ('consolidated_with','Consolidated with',true),
        ('severed_from','Severed from',false), ('transferred_from','Transferred from',false),
        ('related_to','Related to',true)
    """)
    op.execute(f"""
        CREATE TABLE corpus.proceeding_relations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            source_proceeding_id uuid NOT NULL,
            target_proceeding_id uuid NOT NULL,
            relation_concept_id uuid NOT NULL REFERENCES corpus.proceeding_relation_concepts(id),
            raw_relation text,
            valid_from date, valid_to date,
            known_from timestamptz NOT NULL DEFAULT now(), known_to timestamptz,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            evidence_note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (source_proceeding_id <> target_proceeding_id),
            CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CHECK (known_to IS NULL OR known_to > known_from),
            CHECK (verification_status IN ({STATUS})),
            FOREIGN KEY (scope_id,source_proceeding_id) REFERENCES corpus.legal_proceedings(scope_id,id) ON DELETE CASCADE,
            FOREIGN KEY (scope_id,target_proceeding_id) REFERENCES corpus.legal_proceedings(scope_id,id) ON DELETE CASCADE,
            UNIQUE NULLS NOT DISTINCT (source_proceeding_id,target_proceeding_id,relation_concept_id,known_from)
        )
    """)
    op.execute("CREATE INDEX proceeding_relations_source_idx ON corpus.proceeding_relations(scope_id,source_proceeding_id,relation_concept_id,known_from DESC)")
    op.execute("CREATE INDEX proceeding_relations_target_idx ON corpus.proceeding_relations(scope_id,target_proceeding_id,relation_concept_id,known_from DESC)")
    op.execute("CREATE UNIQUE INDEX proceeding_relations_current_idx ON corpus.proceeding_relations(source_proceeding_id,target_proceeding_id,relation_concept_id) WHERE known_to IS NULL AND verification_status NOT IN ('rejected','superseded')")
    op.execute("COMMENT ON TABLE corpus.proceeding_relations IS 'Canonical directed graph of procedural history. controversy_proceedings is litigation-family membership, not ancestry.'")


def _claim_graph() -> None:
    _concept_table("claim_relation_concepts")
    op.execute("""
        INSERT INTO corpus.claim_relation_concepts(code,name) VALUES
        ('challenges','Challenges'), ('reviews','Reviews'), ('derives_from','Derives from'),
        ('renews','Renews'), ('abandons','Abandons'), ('moots','Moots'),
        ('narrows','Narrows'), ('expands','Expands'), ('duplicates','Duplicates'),
        ('responds_to','Responds to'), ('related_to','Related to')
    """)
    op.execute(f"""
        CREATE TABLE corpus.claim_relations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            source_claim_id uuid NOT NULL,
            target_claim_id uuid NOT NULL,
            relation_concept_id uuid NOT NULL REFERENCES corpus.claim_relation_concepts(id),
            raw_relation text,
            valid_from date, valid_to date,
            known_from timestamptz NOT NULL DEFAULT now(), known_to timestamptz,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            evidence_note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (source_claim_id <> target_claim_id),
            CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CHECK (known_to IS NULL OR known_to > known_from),
            CHECK (verification_status IN ({STATUS})),
            FOREIGN KEY (scope_id,source_claim_id) REFERENCES corpus.legal_claims(scope_id,id) ON DELETE CASCADE,
            FOREIGN KEY (scope_id,target_claim_id) REFERENCES corpus.legal_claims(scope_id,id) ON DELETE CASCADE,
            UNIQUE NULLS NOT DISTINCT (source_claim_id,target_claim_id,relation_concept_id,known_from)
        )
    """)
    op.execute("CREATE INDEX claim_relations_source_idx ON corpus.claim_relations(scope_id,source_claim_id,relation_concept_id,known_from DESC)")
    op.execute("CREATE INDEX claim_relations_target_idx ON corpus.claim_relations(scope_id,target_claim_id,relation_concept_id,known_from DESC)")
    op.execute("COMMENT ON TABLE corpus.claim_relations IS 'Cross-proceeding claim lineage. parent_claim_id remains intra-proceeding hierarchy only.'")


def _adjudicative_act_types() -> None:
    _concept_table("adjudicative_act_type_concepts")
    op.execute("""
        INSERT INTO corpus.adjudicative_act_type_concepts(code,name) VALUES
        ('decision','Judicial decision / unspecified act'), ('judgment','Judgment / sentencia'),
        ('interlocutory_judgment','Interlocutory judgment'), ('order','Order / auto'),
        ('resolution','Resolution'), ('decree','Decree / providencia'),
        ('advisory_opinion','Advisory opinion'), ('other','Other adjudicative act')
    """)
    op.execute("ALTER TABLE corpus.judicial_decisions ADD COLUMN act_type_concept_id uuid")
    op.execute("UPDATE corpus.judicial_decisions SET act_type_concept_id=(SELECT id FROM corpus.adjudicative_act_type_concepts WHERE code='decision')")
    op.execute("ALTER TABLE corpus.judicial_decisions ALTER COLUMN act_type_concept_id SET NOT NULL")
    op.execute("ALTER TABLE corpus.judicial_decisions ADD CONSTRAINT judicial_decisions_act_type_fkey FOREIGN KEY (act_type_concept_id) REFERENCES corpus.adjudicative_act_type_concepts(id)")
    op.execute("CREATE INDEX judicial_decisions_act_type_idx ON corpus.judicial_decisions(act_type_concept_id,decision_date DESC)")


def _judicial_event_types() -> None:
    _concept_table("judicial_event_type_concepts")
    op.execute("""
        INSERT INTO corpus.judicial_event_type_concepts(code,name) VALUES
        ('issued','Issued'), ('notified','Notified'), ('vacated','Vacated'), ('annulled','Annulled'),
        ('reversed','Reversed'), ('partially_reversed','Partially reversed'), ('enforced','Enforced'),
        ('superseded','Superseded'), ('clarified','Clarified'), ('corrected','Corrected / rectified'),
        ('supplemented','Supplemented'), ('reconsidered','Reconsidered'), ('remitted','Remitted'),
        ('archived','Archived'), ('other','Other judicial event')
    """)
    op.execute("ALTER TABLE corpus.decision_legal_status_events ADD COLUMN event_type_concept_id uuid")
    op.execute("UPDATE corpus.decision_legal_status_events e SET event_type_concept_id=c.id FROM corpus.judicial_event_type_concepts c WHERE c.code=e.status_type")
    op.execute("ALTER TABLE corpus.decision_legal_status_events ALTER COLUMN event_type_concept_id SET NOT NULL")
    op.execute("ALTER TABLE corpus.decision_legal_status_events ADD CONSTRAINT decision_legal_status_events_type_concept_fkey FOREIGN KEY (event_type_concept_id) REFERENCES corpus.judicial_event_type_concepts(id)")
    op.execute("ALTER TABLE corpus.decision_legal_status_events DROP CONSTRAINT decision_legal_status_events_type_check")
    op.execute("""
        CREATE FUNCTION corpus.sync_judicial_event_type_concept() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE concept_code text;
        BEGIN
            IF NEW.event_type_concept_id IS NULL THEN
                SELECT id INTO NEW.event_type_concept_id FROM corpus.judicial_event_type_concepts WHERE code=NEW.status_type;
                IF NEW.event_type_concept_id IS NULL THEN RAISE EXCEPTION 'unknown judicial event concept code: %',NEW.status_type USING ERRCODE='23503'; END IF;
            END IF;
            SELECT code INTO concept_code FROM corpus.judicial_event_type_concepts WHERE id=NEW.event_type_concept_id;
            IF NEW.status_type IS NOT NULL AND NEW.status_type<>concept_code THEN RAISE EXCEPTION 'status_type conflicts with event_type_concept_id' USING ERRCODE='23514'; END IF;
            NEW.status_type:=concept_code; RETURN NEW;
        END $$
    """)
    op.execute("CREATE TRIGGER decision_legal_status_events_sync_type_concept BEFORE INSERT OR UPDATE OF status_type,event_type_concept_id ON corpus.decision_legal_status_events FOR EACH ROW EXECUTE FUNCTION corpus.sync_judicial_event_type_concept()")
    op.execute("COMMENT ON COLUMN corpus.decision_legal_status_events.status_type IS 'Deprecated compatibility mirror; canonical identity is event_type_concept_id.'")


def _disposition_actions() -> None:
    op.execute("ALTER TABLE corpus.judicial_decision_dispositions ADD CONSTRAINT judicial_decision_dispositions_scope_id_id_key UNIQUE (scope_id,id)")
    op.execute(f"""
        CREATE TABLE corpus.judicial_disposition_actions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            disposition_id uuid NOT NULL,
            effect_concept_id uuid NOT NULL REFERENCES corpus.disposition_effect_concepts(id),
            ordinal integer NOT NULL,
            condition_text text,
            raw_action_text text,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (ordinal > 0), CHECK (verification_status IN ({STATUS})),
            FOREIGN KEY (scope_id,disposition_id) REFERENCES corpus.judicial_decision_dispositions(scope_id,id) ON DELETE CASCADE,
            UNIQUE (disposition_id,ordinal), UNIQUE (scope_id,disposition_id,id)
        )
    """)
    op.execute("ALTER TABLE corpus.disposition_targets ADD COLUMN action_id uuid")
    op.execute("""
        INSERT INTO corpus.judicial_disposition_actions(scope_id,disposition_id,effect_concept_id,ordinal,verification_status,verification_method)
        SELECT scope_id,disposition_id,effect_concept_id,row_number() OVER (PARTITION BY disposition_id ORDER BY created_at,id),verification_status,verification_method
        FROM corpus.disposition_targets
    """)
    op.execute("""
        UPDATE corpus.disposition_targets t SET action_id=a.id
        FROM corpus.judicial_disposition_actions a
        WHERE a.scope_id=t.scope_id AND a.disposition_id=t.disposition_id AND a.effect_concept_id=t.effect_concept_id
          AND a.id=(SELECT a2.id FROM corpus.judicial_disposition_actions a2 WHERE a2.scope_id=t.scope_id AND a2.disposition_id=t.disposition_id AND a2.effect_concept_id=t.effect_concept_id ORDER BY a2.ordinal LIMIT 1)
    """)
    op.execute("""
        CREATE FUNCTION corpus.prepare_disposition_target_action() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE action_effect uuid; DECLARE next_ordinal integer;
        BEGIN
            IF NEW.action_id IS NULL THEN
                SELECT coalesce(max(ordinal),0)+1 INTO next_ordinal FROM corpus.judicial_disposition_actions WHERE disposition_id=NEW.disposition_id;
                INSERT INTO corpus.judicial_disposition_actions(scope_id,disposition_id,effect_concept_id,ordinal,verification_status,verification_method)
                VALUES(NEW.scope_id,NEW.disposition_id,NEW.effect_concept_id,next_ordinal,NEW.verification_status,NEW.verification_method) RETURNING id INTO NEW.action_id;
            END IF;
            SELECT effect_concept_id INTO action_effect FROM corpus.judicial_disposition_actions WHERE id=NEW.action_id AND scope_id=NEW.scope_id AND disposition_id=NEW.disposition_id;
            IF action_effect IS NULL THEN RAISE EXCEPTION 'disposition target action does not belong to same clause/scope' USING ERRCODE='23514'; END IF;
            IF NEW.effect_concept_id IS NOT NULL AND NEW.effect_concept_id<>action_effect THEN RAISE EXCEPTION 'effect_concept_id conflicts with canonical disposition action' USING ERRCODE='23514'; END IF;
            NEW.effect_concept_id:=action_effect; RETURN NEW;
        END $$
    """)
    op.execute("CREATE TRIGGER disposition_targets_prepare_action BEFORE INSERT OR UPDATE OF action_id,effect_concept_id,disposition_id,scope_id ON corpus.disposition_targets FOR EACH ROW EXECUTE FUNCTION corpus.prepare_disposition_target_action()")
    op.execute("ALTER TABLE corpus.disposition_targets ALTER COLUMN action_id SET NOT NULL")
    op.execute("ALTER TABLE corpus.disposition_targets ADD CONSTRAINT disposition_targets_action_fkey FOREIGN KEY (scope_id,disposition_id,action_id) REFERENCES corpus.judicial_disposition_actions(scope_id,disposition_id,id) ON DELETE CASCADE")
    op.execute("COMMENT ON TABLE corpus.judicial_disposition_actions IS 'Canonical actions expressed by a textual disposition clause; one clause may have many actions and one action may have many targets.'")
    op.execute("COMMENT ON COLUMN corpus.disposition_targets.effect_concept_id IS 'Deprecated compatibility mirror of the canonical action effect.'")


def _narrow_controversy_membership() -> None:
    op.execute("ALTER TABLE corpus.controversy_proceedings DROP CONSTRAINT controversy_proceedings_relation_type_check")
    op.execute("UPDATE corpus.controversy_proceedings SET relation_type='review' WHERE relation_type IN ('appeal','cassation','constitutional_review')")
    op.execute("UPDATE corpus.controversy_proceedings SET relation_type='related' WHERE relation_type IN ('consolidated','severed')")
    op.execute("ALTER TABLE corpus.controversy_proceedings ADD CONSTRAINT controversy_proceedings_relation_type_check CHECK (relation_type IN ('originating','review','enforcement','incident','related','other'))")
    op.execute("COMMENT ON COLUMN corpus.controversy_proceedings.relation_type IS 'Litigation-family membership role only; proceeding ancestry belongs in proceeding_relations.'")


def downgrade() -> None:
    raise RuntimeError('0036 is part of the intentional pre-ingestion legal-reality normalization boundary')
