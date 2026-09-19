"""Add normalized multi-court registry and hierarchy support.

Revision ID: 0018_multi_court_registry
Revises: 0017_ingestion_control
Create Date: 2026-09-15

JurisNexo must represent decisions from independent constitutional jurisdiction,
the ordinary judiciary, appellate and first-instance courts, peace courts and
specialized tribunals without encoding a false single-tree hierarchy.  This
revision keeps corpus.courts as the canonical decision issuer and adds explicit
classification, aliases, subject jurisdictions and typed court relationships.
"""

from alembic import op

revision = "0018_multi_court_registry"
down_revision = "0017_ingestion_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE corpus.courts
            ADD COLUMN judicial_system text NOT NULL DEFAULT 'other',
            ADD COLUMN court_type text NOT NULL DEFAULT 'other'
        """
    )
    op.execute(
        """
        ALTER TABLE corpus.courts
            ADD CONSTRAINT courts_judicial_system_check CHECK (
                judicial_system IN (
                    'ordinary_judiciary',
                    'constitutional_jurisdiction',
                    'electoral_jurisdiction',
                    'other'
                )
            ),
            ADD CONSTRAINT courts_type_check CHECK (
                court_type IN (
                    'constitutional',
                    'supreme',
                    'appellate',
                    'first_instance',
                    'peace',
                    'specialized',
                    'electoral',
                    'other'
                )
            )
        """
    )
    op.execute(
        "CREATE INDEX courts_system_type_idx "
        "ON corpus.courts (judicial_system, court_type, active_from, active_to)"
    )

    op.execute(
        """
        CREATE TABLE corpus.jurisdictions (
            code text PRIMARY KEY,
            name text NOT NULL,
            description text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT jurisdictions_code_check CHECK (code ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
            CONSTRAINT jurisdictions_name_nonempty CHECK (btrim(name) <> '')
        )
        """
    )

    op.execute(
        """
        CREATE TABLE corpus.court_jurisdictions (
            court_id uuid NOT NULL REFERENCES corpus.courts(id) ON DELETE CASCADE,
            jurisdiction_code text NOT NULL REFERENCES corpus.jurisdictions(code),
            is_primary boolean NOT NULL DEFAULT false,
            active_from date,
            active_to date,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (court_id, jurisdiction_code),
            CONSTRAINT court_jurisdictions_active_range_check CHECK (
                active_to IS NULL OR active_from IS NULL OR active_to >= active_from
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX court_jurisdictions_lookup_idx "
        "ON corpus.court_jurisdictions (jurisdiction_code, court_id)"
    )

    op.execute(
        """
        CREATE TABLE corpus.court_aliases (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            court_id uuid NOT NULL REFERENCES corpus.courts(id) ON DELETE CASCADE,
            alias text NOT NULL,
            normalized_alias text NOT NULL,
            alias_kind text NOT NULL DEFAULT 'source_label',
            source_registry_id uuid REFERENCES corpus.source_registries(id) ON DELETE CASCADE,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT court_aliases_alias_nonempty CHECK (btrim(alias) <> ''),
            CONSTRAINT court_aliases_normalized_nonempty CHECK (btrim(normalized_alias) <> ''),
            CONSTRAINT court_aliases_kind_check CHECK (
                alias_kind IN ('official_name', 'abbreviation', 'source_label', 'historical_name', 'other')
            ),
            CONSTRAINT court_aliases_unique UNIQUE (
                court_id, normalized_alias, alias_kind, source_registry_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX court_aliases_normalized_idx "
        "ON corpus.court_aliases (normalized_alias)"
    )

    op.execute(
        """
        CREATE TABLE corpus.court_organ_aliases (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            court_organ_id uuid NOT NULL REFERENCES corpus.court_organs(id) ON DELETE CASCADE,
            alias text NOT NULL,
            normalized_alias text NOT NULL,
            alias_kind text NOT NULL DEFAULT 'source_label',
            source_registry_id uuid REFERENCES corpus.source_registries(id) ON DELETE CASCADE,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT court_organ_aliases_alias_nonempty CHECK (btrim(alias) <> ''),
            CONSTRAINT court_organ_aliases_normalized_nonempty CHECK (btrim(normalized_alias) <> ''),
            CONSTRAINT court_organ_aliases_kind_check CHECK (
                alias_kind IN ('official_name', 'abbreviation', 'source_label', 'historical_name', 'other')
            ),
            CONSTRAINT court_organ_aliases_unique UNIQUE (
                court_organ_id, normalized_alias, alias_kind, source_registry_id
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX court_organ_aliases_normalized_idx "
        "ON corpus.court_organ_aliases (normalized_alias)"
    )

    op.execute(
        """
        CREATE TABLE corpus.court_relations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            from_court_id uuid NOT NULL REFERENCES corpus.courts(id) ON DELETE CASCADE,
            to_court_id uuid NOT NULL REFERENCES corpus.courts(id) ON DELETE CASCADE,
            relation_type text NOT NULL,
            active_from date,
            active_to date,
            source_note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT court_relations_distinct_check CHECK (from_court_id <> to_court_id),
            CONSTRAINT court_relations_type_check CHECK (
                relation_type IN (
                    'appeals_to',
                    'reviewed_by',
                    'administratively_supervised_by',
                    'successor_of',
                    'other'
                )
            ),
            CONSTRAINT court_relations_active_range_check CHECK (
                active_to IS NULL OR active_from IS NULL OR active_to >= active_from
            ),
            CONSTRAINT court_relations_unique UNIQUE (
                from_court_id, to_court_id, relation_type, active_from
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX court_relations_from_idx "
        "ON corpus.court_relations (from_court_id, relation_type)"
    )
    op.execute(
        "CREATE INDEX court_relations_to_idx "
        "ON corpus.court_relations (to_court_id, relation_type)"
    )

    op.execute(
        """
        COMMENT ON COLUMN corpus.courts.judicial_system IS
        'Independent institutional jurisdiction family. It must not be interpreted as an appeal hierarchy.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.court_relations IS
        'Typed, temporal relationships between courts. Appeal, review and administrative relationships remain explicit instead of being collapsed into parent_court_id.'
        """
    )
    op.execute(
        """
        COMMENT ON TABLE corpus.court_aliases IS
        'Source-facing labels used to resolve heterogeneous portal text to a canonical court without overwriting source metadata.'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corpus.court_relations")
    op.execute("DROP TABLE IF EXISTS corpus.court_organ_aliases")
    op.execute("DROP TABLE IF EXISTS corpus.court_aliases")
    op.execute("DROP TABLE IF EXISTS corpus.court_jurisdictions")
    op.execute("DROP TABLE IF EXISTS corpus.jurisdictions")
    op.execute("DROP INDEX IF EXISTS corpus.courts_system_type_idx")
    op.execute("ALTER TABLE corpus.courts DROP COLUMN IF EXISTS court_type")
    op.execute("ALTER TABLE corpus.courts DROP COLUMN IF EXISTS judicial_system")
