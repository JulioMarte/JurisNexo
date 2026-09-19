"""Replace one-dimensional disposition targets with typed action arguments.

Revision ID: 0044_action_arguments
Revises: 0043_issues_facts
Create Date: 2026-09-17

A dispositive action may have an object, obligor, beneficiary, destination,
amount, condition and other arguments. The old target model forced every
effect into exactly one target type and could not faithfully represent orders
such as payment or remand. Existing targets migrate losslessly as the action's
`object` argument before the compatibility surface is removed.
"""

from alembic import op

revision = "0044_action_arguments"
down_revision = "0043_issues_facts"
branch_labels = None
depends_on = None

PUBLIC_SCOPE_ID = "00000000-0000-0000-0000-000000000001"
STATUS = "'candidate','verified','conflicting','rejected','superseded'"
OBJECT_TYPES = (
    "'claim','party_role','proceeding','decision','proposition','provision',"
    "'court','court_organ','text','number','money','date','duration','percentage'"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE corpus.judicial_disposition_action_arguments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            scope_id uuid NOT NULL DEFAULT '{PUBLIC_SCOPE_ID}'::uuid,
            disposition_id uuid NOT NULL,
            action_id uuid NOT NULL,
            role_scheme_code text NOT NULL DEFAULT 'disposition_argument_role',
            role_concept_id uuid NOT NULL,
            object_type text NOT NULL,
            target_claim_id uuid,
            target_party_role_id uuid,
            target_proceeding_id uuid,
            target_decision_id uuid,
            target_proposition_id uuid,
            target_provision_id uuid,
            target_court_id uuid,
            target_court_organ_id uuid,
            text_value text,
            numeric_value numeric,
            currency_code character(3),
            date_value date,
            duration_value numeric,
            duration_unit text,
            percentage_value numeric,
            raw_argument_text text,
            ordinal integer NOT NULL,
            verification_status text NOT NULL DEFAULT 'candidate',
            verification_method text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT disposition_arguments_role_scheme_check
                CHECK (role_scheme_code='disposition_argument_role'),
            CONSTRAINT disposition_arguments_role_fkey
                FOREIGN KEY (role_scheme_code,role_concept_id)
                REFERENCES corpus.legal_concepts(scheme_code,id),
            CONSTRAINT disposition_arguments_object_type_check
                CHECK (object_type IN ({OBJECT_TYPES})),
            CONSTRAINT disposition_arguments_ordinal_check CHECK (ordinal > 0),
            CONSTRAINT disposition_arguments_status_check
                CHECK (verification_status IN ({STATUS})),
            CONSTRAINT disposition_arguments_currency_check
                CHECK (currency_code IS NULL OR currency_code ~ '^[A-Z]{{3}}$'),
            CONSTRAINT disposition_arguments_duration_check CHECK (
                (duration_value IS NULL AND duration_unit IS NULL)
                OR (duration_value IS NOT NULL AND duration_value > 0
                    AND btrim(coalesce(duration_unit,'')) <> '')
            ),
            CONSTRAINT disposition_arguments_shape_check CHECK (
                (object_type='claim' AND target_claim_id IS NOT NULL
                    AND num_nonnulls(target_party_role_id,target_proceeding_id,target_decision_id,
                        target_proposition_id,target_provision_id,target_court_id,target_court_organ_id,
                        text_value,numeric_value,currency_code,date_value,duration_value,duration_unit,
                        percentage_value)=0)
                OR
                (object_type='party_role' AND target_party_role_id IS NOT NULL
                    AND num_nonnulls(target_claim_id,target_proceeding_id,target_decision_id,
                        target_proposition_id,target_provision_id,target_court_id,target_court_organ_id,
                        text_value,numeric_value,currency_code,date_value,duration_value,duration_unit,
                        percentage_value)=0)
                OR
                (object_type='proceeding' AND target_proceeding_id IS NOT NULL
                    AND num_nonnulls(target_claim_id,target_party_role_id,target_decision_id,
                        target_proposition_id,target_provision_id,target_court_id,target_court_organ_id,
                        text_value,numeric_value,currency_code,date_value,duration_value,duration_unit,
                        percentage_value)=0)
                OR
                (object_type='decision' AND target_decision_id IS NOT NULL
                    AND num_nonnulls(target_claim_id,target_party_role_id,target_proceeding_id,
                        target_proposition_id,target_provision_id,target_court_id,target_court_organ_id,
                        text_value,numeric_value,currency_code,date_value,duration_value,duration_unit,
                        percentage_value)=0)
                OR
                (object_type='proposition' AND target_proposition_id IS NOT NULL
                    AND num_nonnulls(target_claim_id,target_party_role_id,target_proceeding_id,
                        target_decision_id,target_provision_id,target_court_id,target_court_organ_id,
                        text_value,numeric_value,currency_code,date_value,duration_value,duration_unit,
                        percentage_value)=0)
                OR
                (object_type='provision' AND target_provision_id IS NOT NULL
                    AND num_nonnulls(target_claim_id,target_party_role_id,target_proceeding_id,
                        target_decision_id,target_proposition_id,target_court_id,target_court_organ_id,
                        text_value,numeric_value,currency_code,date_value,duration_value,duration_unit,
                        percentage_value)=0)
                OR
                (object_type='court' AND target_court_id IS NOT NULL
                    AND num_nonnulls(target_claim_id,target_party_role_id,target_proceeding_id,
                        target_decision_id,target_proposition_id,target_provision_id,target_court_organ_id,
                        text_value,numeric_value,currency_code,date_value,duration_value,duration_unit,
                        percentage_value)=0)
                OR
                (object_type='court_organ' AND target_court_organ_id IS NOT NULL
                    AND num_nonnulls(target_claim_id,target_party_role_id,target_proceeding_id,
                        target_decision_id,target_proposition_id,target_provision_id,target_court_id,
                        text_value,numeric_value,currency_code,date_value,duration_value,duration_unit,
                        percentage_value)=0)
                OR
                (object_type='text' AND btrim(coalesce(text_value,'')) <> ''
                    AND num_nonnulls(target_claim_id,target_party_role_id,target_proceeding_id,
                        target_decision_id,target_proposition_id,target_provision_id,target_court_id,
                        target_court_organ_id,numeric_value,currency_code,date_value,duration_value,
                        duration_unit,percentage_value)=0)
                OR
                (object_type='number' AND numeric_value IS NOT NULL
                    AND num_nonnulls(target_claim_id,target_party_role_id,target_proceeding_id,
                        target_decision_id,target_proposition_id,target_provision_id,target_court_id,
                        target_court_organ_id,text_value,currency_code,date_value,duration_value,
                        duration_unit,percentage_value)=0)
                OR
                (object_type='money' AND numeric_value IS NOT NULL AND currency_code IS NOT NULL
                    AND num_nonnulls(target_claim_id,target_party_role_id,target_proceeding_id,
                        target_decision_id,target_proposition_id,target_provision_id,target_court_id,
                        target_court_organ_id,text_value,date_value,duration_value,duration_unit,
                        percentage_value)=0)
                OR
                (object_type='date' AND date_value IS NOT NULL
                    AND num_nonnulls(target_claim_id,target_party_role_id,target_proceeding_id,
                        target_decision_id,target_proposition_id,target_provision_id,target_court_id,
                        target_court_organ_id,text_value,numeric_value,currency_code,duration_value,
                        duration_unit,percentage_value)=0)
                OR
                (object_type='duration' AND duration_value IS NOT NULL AND duration_unit IS NOT NULL
                    AND num_nonnulls(target_claim_id,target_party_role_id,target_proceeding_id,
                        target_decision_id,target_proposition_id,target_provision_id,target_court_id,
                        target_court_organ_id,text_value,numeric_value,currency_code,date_value,
                        percentage_value)=0)
                OR
                (object_type='percentage' AND percentage_value IS NOT NULL
                    AND num_nonnulls(target_claim_id,target_party_role_id,target_proceeding_id,
                        target_decision_id,target_proposition_id,target_provision_id,target_court_id,
                        target_court_organ_id,text_value,numeric_value,currency_code,date_value,
                        duration_value,duration_unit)=0)
            ),
            CONSTRAINT disposition_arguments_action_fkey
                FOREIGN KEY (scope_id,disposition_id,action_id)
                REFERENCES corpus.judicial_disposition_actions(scope_id,disposition_id,id)
                ON DELETE CASCADE,
            CONSTRAINT disposition_arguments_claim_fkey
                FOREIGN KEY (scope_id,target_claim_id)
                REFERENCES corpus.legal_claims(scope_id,id),
            CONSTRAINT disposition_arguments_party_role_fkey
                FOREIGN KEY (scope_id,target_party_role_id)
                REFERENCES corpus.proceeding_party_roles(scope_id,id),
            CONSTRAINT disposition_arguments_proceeding_fkey
                FOREIGN KEY (scope_id,target_proceeding_id)
                REFERENCES corpus.legal_proceedings(scope_id,id),
            CONSTRAINT disposition_arguments_decision_fkey
                FOREIGN KEY (scope_id,target_decision_id)
                REFERENCES corpus.judicial_decisions(scope_id,id),
            CONSTRAINT disposition_arguments_proposition_fkey
                FOREIGN KEY (scope_id,target_proposition_id)
                REFERENCES corpus.legal_propositions(scope_id,id),
            CONSTRAINT disposition_arguments_provision_fkey
                FOREIGN KEY (scope_id,target_provision_id)
                REFERENCES corpus.legal_provisions(scope_id,id),
            CONSTRAINT disposition_arguments_court_fkey
                FOREIGN KEY (target_court_id) REFERENCES corpus.courts(id),
            CONSTRAINT disposition_arguments_court_organ_fkey
                FOREIGN KEY (target_court_organ_id) REFERENCES corpus.court_organs(id),
            CONSTRAINT disposition_arguments_action_ordinal_key
                UNIQUE (action_id,ordinal)
        )
        """
    )
    op.execute(
        "CREATE INDEX disposition_arguments_action_idx "
        "ON corpus.judicial_disposition_action_arguments(scope_id,action_id,ordinal)"
    )

    op.execute(
        f"""
        CREATE TABLE corpus.disposition_effect_argument_rules (
            effect_concept_id uuid NOT NULL REFERENCES corpus.disposition_effect_concepts(id)
                ON DELETE CASCADE,
            role_scheme_code text NOT NULL DEFAULT 'disposition_argument_role',
            role_concept_id uuid NOT NULL,
            object_type text NOT NULL,
            required boolean NOT NULL DEFAULT false,
            max_count integer,
            note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT disposition_effect_argument_rules_scheme_check
                CHECK (role_scheme_code='disposition_argument_role'),
            CONSTRAINT disposition_effect_argument_rules_role_fkey
                FOREIGN KEY (role_scheme_code,role_concept_id)
                REFERENCES corpus.legal_concepts(scheme_code,id),
            CONSTRAINT disposition_effect_argument_rules_object_type_check
                CHECK (object_type IN ({OBJECT_TYPES})),
            CONSTRAINT disposition_effect_argument_rules_max_count_check
                CHECK (max_count IS NULL OR max_count > 0),
            PRIMARY KEY (effect_concept_id,role_concept_id,object_type)
        )
        """
    )

    op.execute(
        """
        INSERT INTO corpus.judicial_disposition_action_arguments(
            scope_id,disposition_id,action_id,role_concept_id,object_type,
            target_claim_id,target_party_role_id,target_proceeding_id,
            target_decision_id,target_proposition_id,raw_argument_text,ordinal,
            verification_status,verification_method,created_at
        )
        SELECT
            t.scope_id,t.disposition_id,t.action_id,r.id,
            CASE t.target_type WHEN 'party' THEN 'party_role' ELSE t.target_type END,
            t.target_claim_id,t.target_party_role_id,t.target_proceeding_id,
            t.target_decision_id,t.target_proposition_id,t.note,
            row_number() OVER (PARTITION BY t.action_id ORDER BY t.created_at,t.id),
            t.verification_status,t.verification_method,t.created_at
        FROM corpus.disposition_targets t
        JOIN corpus.legal_concepts r
          ON r.scheme_code='disposition_argument_role'
         AND r.jurisdiction_code IS NULL
         AND r.code='object'
        """
    )

    op.execute(
        """
        INSERT INTO corpus.disposition_effect_argument_rules(
            effect_concept_id,role_concept_id,object_type,required,max_count,note
        )
        SELECT e.id,r.id,
            CASE e.target_type WHEN 'party' THEN 'party_role' ELSE e.target_type END,
            true,1,
            'Migrated V3 primary object rule; V4 permits additional typed arguments without assuming every effect has only one semantic participant.'
        FROM corpus.disposition_effect_concepts e
        JOIN corpus.legal_concepts r
          ON r.scheme_code='disposition_argument_role'
         AND r.jurisdiction_code IS NULL
         AND r.code='object'
        """
    )

    op.execute(
        """
        INSERT INTO corpus.disposition_effect_argument_rules(
            effect_concept_id,role_concept_id,object_type,required,max_count,note
        )
        SELECT e.id,r.id,'money',false,1,'Optional normalized monetary amount.'
        FROM corpus.disposition_effect_concepts e
        JOIN corpus.legal_concepts r
          ON r.scheme_code='disposition_argument_role'
         AND r.jurisdiction_code IS NULL
         AND r.code='amount'
        WHERE e.code='awards_costs_against'
        """
    )
    op.execute(
        """
        INSERT INTO corpus.disposition_effect_argument_rules(
            effect_concept_id,role_concept_id,object_type,required,max_count,note
        )
        SELECT e.id,r.id,'court_organ',false,1,'Optional destination court organ on remand.'
        FROM corpus.disposition_effect_concepts e
        JOIN corpus.legal_concepts r
          ON r.scheme_code='disposition_argument_role'
         AND r.jurisdiction_code IS NULL
         AND r.code='destination'
        WHERE e.code='remands'
        """
    )

    op.execute(
        "DROP TRIGGER IF EXISTS disposition_targets_validate_action_effect_type "
        "ON corpus.disposition_targets"
    )
    op.execute("DROP FUNCTION IF EXISTS corpus.validate_disposition_action_target_type()")
    op.execute(
        "DROP TRIGGER IF EXISTS judicial_disposition_actions_validate_effect_change "
        "ON corpus.judicial_disposition_actions"
    )
    op.execute("DROP FUNCTION IF EXISTS corpus.validate_disposition_action_effect_change()")
    op.execute("DROP TABLE corpus.disposition_targets")

    op.execute(
        "ALTER TABLE corpus.disposition_effect_concepts "
        "DROP CONSTRAINT disposition_effect_concepts_parent_same_target_fkey"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_effect_concepts "
        "DROP CONSTRAINT disposition_effect_concepts_target_id_key"
    )
    op.execute(
        "ALTER TABLE corpus.disposition_effect_concepts "
        "DROP CONSTRAINT disposition_effect_concepts_target_type_check"
    )
    op.execute("ALTER TABLE corpus.disposition_effect_concepts DROP COLUMN target_type")

    op.execute(
        """
        COMMENT ON TABLE corpus.judicial_disposition_action_arguments IS
        'Typed semantic arguments of a canonical dispositive action. An action may express several roles (object, obligor, beneficiary, destination, amount, condition, etc.); exact source wording remains on the clause/action and optional raw_argument_text.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.disposition_effect_argument_rules IS
        'Machine-readable baseline grammar for known disposition effects. Rules describe expected roles/object kinds but are not a complete legal reasoning engine; jurisdiction-specific effects may extend them as data.'
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0044 intentionally removes the false one-target-type disposition model"
    )
