# JurisNexo — Database bootstrap and multi-court registry

## Purpose

A clean JurisNexo database must not be merely an empty set of tables. After migrations and bootstrap it must contain the stable legal-system reference facts required to ingest judicial decisions consistently across institutions and court levels.

This contract covers two different concerns:

1. schema history is owned by Alembic migrations;
2. stable operational reference data is installed and reconciled by an idempotent database bootstrap.

The bootstrap is not sample/demo data and it is not a replacement for migrations.

## Request Engine pattern adopted

Request Engine treats its accepted PostgreSQL baseline as an auditable artifact: the baseline loader verifies an accepted payload, clean-cluster CI proves that it installs, and later evolution is appended through migrations instead of silently rewriting accepted history.

JurisNexo adopts the parts of that pattern that are appropriate at the current stage:

- clean database reproduction is mandatory in CI;
- schema history is append-only through Alembic revisions;
- bootstrap data is versioned in code and verified after application;
- bootstrap is idempotent and serialized with a PostgreSQL advisory transaction lock;
- CI and local Docker startup run bootstrap after migrations and before the API/tests;
- mutable operator state is not reset by a later bootstrap run.

JurisNexo does **not** yet freeze the entire database into a Request Engine-style immutable giant `0001` baseline. The product/data model is still evolving rapidly, and pretending the schema is already mature enough for a destructive rebaseline would create false stability. A future accepted-baseline process can be introduced once the corpus model has real production data and a deliberate rebaseline audit.

## Canonical startup sequence

```text
PostgreSQL
    -> alembic upgrade head
    -> jurisnexo-db-bootstrap apply
    -> jurisnexo-db-bootstrap verify
    -> API / workers / tests
```

In Docker Compose this is represented explicitly as:

```text
db -> migrate -> bootstrap -> api/test
```

The bootstrap uses `POSTGRES_*` runtime settings. It does not require application code to depend on `DATABASE_URL`.

## Multi-court model

A single `parent_court_id` is intentionally not used to model the Dominican justice system. It would conflate several different legal relationships and would incorrectly imply that the Tribunal Constitucional is simply a child or parent in the ordinary judicial hierarchy.

`corpus.courts` remains the canonical issuer attached to a judicial case and now classifies each court using two independent dimensions:

```text
judicial_system
    ordinary_judiciary
    constitutional_jurisdiction
    electoral_jurisdiction
    other

court_type
    constitutional
    supreme
    appellate
    first_instance
    peace
    specialized
    electoral
    other
```

Subject-matter competence is many-to-many through `corpus.jurisdictions` and `corpus.court_jurisdictions`. This permits a court to have more than one material jurisdiction without encoding an uncontrolled comma-separated string on every case.

Court relationships are explicit and temporal through `corpus.court_relations`:

```text
appeals_to
reviewed_by
administratively_supervised_by
successor_of
other
```

This makes it possible to represent lower courts, appellate courts, the SCJ, the Tribunal Constitucional and later specialized/electoral sources without changing the case table or inventing a false universal hierarchy.

## Source-label resolution

Official portals do not always spell a court or organ exactly the same way. The following tables preserve that distinction:

```text
corpus.court_aliases
corpus.court_organ_aliases
```

An alias maps source-facing text to a canonical court/organ but does not overwrite the original source payload. This is important for provenance and historical labels.

## Bootstrap v1 contents

The first bootstrap installs stable identities for:

- Suprema Corte de Justicia (`DO-SCJ`);
- Tribunal Constitucional (`DO-TC`);
- the SCJ Pleno, Primera Sala, Segunda Sala, Tercera Sala and Salas Reunidas;
- the TC Pleno;
- a jurisdiction taxonomy including ordinary, constitutional, civil/commercial, criminal, labor, land, administrative, juvenile and peace jurisdiction labels;
- official SCJ and TC source registries;
- source-collection control-plane records for SCJ Principales, modern SCJ decisions, judicial bulletins, historical decisions and TC decisions.

The source-collection defaults preserve the acquisition policy previously agreed for the MVP:

```text
SCJ principales-sentencias  enabled       hidden
SCJ decisiones              enabled       hidden
SCJ boletin-judicial        catalog_only  hidden
SCJ sentencias-historicas   catalog_only  hidden
TC  sentencias              catalog_only  hidden
```

`hidden` is intentional. Acquisition eligibility is not equivalent to agent visibility, and catalog discovery is not equivalent to acquisition.

## Mutable versus bootstrap-owned state

The bootstrap owns stable identity/classification facts such as canonical court code, court type, judicial system, source registry identity and initial collection existence.

It does **not** reset operator-controlled acquisition policy or agent visibility on an existing source collection. For example, after an operator pauses `scj/decisiones`, rerunning bootstrap must not silently re-enable it.

This rule is important for production safety:

```text
bootstrap ensures required reference identities exist
operator/API controls mutable runtime policy
```

## Extending to lower courts

Adding a lower court does not require a new schema design. A connector or curated catalog may create a concrete court row, assign one or more jurisdictions, add source aliases and express any verified relationship separately.

Example conceptual shape:

```text
Juzgado de Primera Instancia X
    judicial_system = ordinary_judiciary
    court_type = first_instance
    jurisdictions = [juvenile]

        appeals_to
            -> Corte de Apelación Y

Corte de Apelación Y
    court_type = appellate

        appeals_to / reviewed_by as legally appropriate
            -> higher court
```

The exact legal relationship must come from authoritative metadata. The bootstrap must not infer an appeal path simply from similar names or geographic proximity.

## Verification contract

`jurisnexo-db-bootstrap verify` fails if the schema is not bootstrap-compatible or if a bootstrap-managed stable identity/classification is missing or drifted.

Integration tests additionally prove that:

- SCJ and TC exist as independent judicial systems;
- bootstrap can run repeatedly without duplicating managed data;
- expected SCJ organs and source collections exist;
- a new appellate/first-instance/specialized court can be represented without schema changes;
- invalid court taxonomy values are rejected by PostgreSQL constraints.

This is structural/database evidence. It does not prove that a future connector has correctly identified every Dominican court or every historical appeal relationship; those facts require source-specific evidence and ingestion tests.
