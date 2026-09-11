"""Quarantine the unused legacy public Data API surface.

Revision ID: 0008_quarantine_legacy_public
Revises: 0007_resolution_ledger
Create Date: 2026-09-11

The current JurisNexo architecture does not use the legacy `public` tables or
RPCs as a browser-facing API. Production inventory confirmed that those legacy
tables are empty (except Alembic metadata), so this migration removes client
role access without destructively dropping the old objects.

The legacy objects do not exist in a clean JurisNexo PostgreSQL database. Every
operation is therefore conditional so migrations remain portable in CI and new
environments.
"""

from alembic import op

revision = "0008_quarantine_legacy_public"
down_revision = "0007_resolution_ledger"
branch_labels = None
depends_on = None


LEGACY_TABLES = (
    "chunks",
    "citations",
    "conversations",
    "document_structure",
    "embedding_models",
    "external_legal_sources",
    "feedback_events",
    "ingestion_jobs",
    "legal_articles",
    "legal_codes",
    "messages",
    "parser_versions",
    "raw_pages",
    "search_sessions",
    "semantic_links",
    "source_aliases",
    "source_tags",
    "sources",
    "tags",
    "user_profiles",
    "workspace_members",
    "workspaces",
)

LEGACY_FUNCTIONS = (
    ("correct_ocr_text", "uuid,text,uuid"),
    ("get_chunks_for_argument", "uuid,text"),
    ("get_chunks_with_context", "uuid[]"),
    ("get_current_workspace_ids", ""),
    ("get_relevant_chunks", "vector,double precision,integer"),
    ("get_relevant_context_chunks", "vector,double precision,integer"),
    ("search", "vector,uuid[],text,integer,integer"),
)


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    table_array = ", ".join(_quote_literal(name) for name in LEGACY_TABLES)
    function_rows = ", ".join(
        f"({_quote_literal(name)}, {_quote_literal(arguments)})"
        for name, arguments in LEGACY_FUNCTIONS
    )

    op.execute(
        f"""
        DO $hardening$
        DECLARE
            object_name text;
            role_name text;
            function_name text;
            function_args text;
            function_oid oid;
        BEGIN
            -- The legacy prototype granted every table privilege to browser
            -- roles. JurisNexo now routes application access through FastAPI
            -- and scoped database roles, so these grants are unnecessary.
            FOREACH object_name IN ARRAY ARRAY[{table_array}] LOOP
                IF to_regclass(format('public.%I', object_name)) IS NOT NULL THEN
                    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', object_name);

                    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                            EXECUTE format(
                                'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM %I',
                                object_name,
                                role_name
                            );
                        END IF;
                    END LOOP;
                END IF;
            END LOOP;

            -- Alembic metadata must never be visible to browser roles either.
            IF to_regclass('public.alembic_version') IS NOT NULL THEN
                ALTER TABLE public.alembic_version ENABLE ROW LEVEL SECURITY;
                FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                        EXECUTE format(
                            'REVOKE ALL PRIVILEGES ON TABLE public.alembic_version FROM %I',
                            role_name
                        );
                    END IF;
                END LOOP;
            END IF;

            -- PostgreSQL grants EXECUTE on functions to PUBLIC by default.
            -- Revoke both inherited PUBLIC access and explicit Supabase client
            -- roles. Keep the functions physically present for rollback and
            -- forensic reference until the legacy prototype is retired.
            FOR function_name, function_args IN
                SELECT * FROM (VALUES {function_rows}) AS f(name, args)
            LOOP
                function_oid := to_regprocedure(
                    format('public.%I(%s)', function_name, function_args)
                );
                IF function_oid IS NOT NULL THEN
                    EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC', function_oid::regprocedure);
                    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                            EXECUTE format(
                                'REVOKE EXECUTE ON FUNCTION %s FROM %I',
                                function_oid::regprocedure,
                                role_name
                            );
                        END IF;
                    END LOOP;

                    -- The legacy functions use unqualified public/extension
                    -- objects. Pin the lookup path instead of leaving it caller
                    -- mutable; this removes the search_path privilege-escalation
                    -- class without rewriting legacy function bodies.
                    EXECUTE format(
                        'ALTER FUNCTION %s SET search_path = public, extensions, pg_temp',
                        function_oid::regprocedure
                    );
                END IF;
            END LOOP;
        END
        $hardening$;
        """
    )

    op.execute(
        """
        COMMENT ON SCHEMA public IS
        'Legacy JurisNexo prototype objects may remain here for compatibility/forensics, but browser roles are quarantined. New product data belongs in explicit private schemas such as corpus.'
        """
    )


def downgrade() -> None:
    # Security hardening intentionally has no automatic downgrade. Restoring the
    # old broad anon/authenticated grants would recreate a known exposure. Any
    # rollback must be an explicit, reviewed migration with the minimum grants
    # required by the caller being restored.
    pass
