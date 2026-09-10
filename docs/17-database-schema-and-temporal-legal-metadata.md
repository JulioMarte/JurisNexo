# JurisNexo — Database Schema and Temporal Legal Metadata

## 1. Purpose

The database is the first implementation boundary that must become stable enough for ingestion, retrieval, research, reproducibility, and later multi-tenant use.

This document converts the conceptual corpus model into a concrete PostgreSQL design direction for the MVP.

The design is intentionally conservative: primary-source facts are stored in normalized relational fields; uncertain/model-derived facts are stored separately with provenance; embeddings and enrichment are replaceable indexes, not the source of truth.

## 2. Current Supabase state and migration posture

The existing Supabase project contains useful prototype tables such as `sources`, `raw_pages`, `chunks`, `document_structure`, `citations`, `ingestion_jobs`, `parser_versions`, and `embedding_models`.

Those tables demonstrate several useful concepts, but they should not be expanded blindly into the production schema because they currently blur at least three distinct entities:

1. a physical/source artifact (for example a compilation PDF);
2. a logical judicial decision/case contained within that artifact;
3. retrieval units derived from the decision.

For JurisNexo, these concepts must be separate before meaningful ingestion begins.

The preferred approach is to introduce the new schema through versioned migrations and migrate/reuse prototype data only where semantics are unambiguous. The current tables are effectively empty, so preserving an unsuitable schema for compatibility has little value.

## 3. Core data separation

The database must distinguish:

```text
source registry
    -> source artifact (immutable acquired file/version)
        -> artifact pages (physical PDF pages)
            -> case occurrence / segment
                -> canonical case
                    -> case pages / evidence coordinates
                    -> passages
                    -> citations
                    -> legal references
                    -> derived interpretation
```

The key rule is:

> A PDF is not a case, and a retrieval chunk is not a legal source.

The SCJ "Principales Decisiones" publications are compilation artifacts containing multiple decisions. JurisNexo must preserve both the physical artifact and the logical decisions inside it.

## 4. PostgreSQL schema namespaces

The target design should use schemas to make boundaries explicit:

```text
corpus.*
research.*
tenant.*
audit.*
internal.*
```

For the first corpus implementation, `corpus.*` is the priority.

Suggested ownership:

- `corpus`: public legal sources and deterministic/verified corpus data;
- `research`: research jobs, evidence, claims, reports, snapshots;
- `tenant`: organizations, memberships, private uploads and tenant resources;
- `audit`: durable security/audit events;
- `internal`: model runs, parser versions, index generations and operational metadata not exposed as product data.

## 5. Core corpus tables

### `corpus.source_registries`

Represents an approved institution/source channel.

Minimum fields:

- `id uuid primary key`;
- `institution_code text not null`;
- `institution_name text not null`;
- `source_type text not null`;
- `base_url text`;
- `authority_class text not null`;
- `active boolean not null default true`;
- `created_at timestamptz not null`;
- `updated_at timestamptz not null`.

Initial examples include the official Poder Judicial / Suprema Corte de Justicia source.

### `corpus.source_artifacts`

Represents an immutable acquired file or representation.

Minimum fields:

- `id uuid primary key`;
- `source_registry_id uuid not null`;
- `storage_bucket text`;
- `storage_object_key text`;
- `source_url text`;
- `observed_filename text not null`;
- `mime_type text not null`;
- `byte_size bigint`;
- `sha256 text not null`;
- `acquired_at timestamptz not null`;
- `published_at date` when the publication date of the compilation is known;
- `artifact_kind text not null` (`single_decision`, `decision_compilation`, `bulletin`, etc.);
- `page_count integer`;
- `parser_version_id bigint`;
- `quality_status text not null`;
- `supersedes_artifact_id uuid`;
- `metadata jsonb not null default '{}'`.

Constraints/indexes:

- unique or near-unique index on `sha256` for byte-identical artifacts;
- index on `source_registry_id`;
- index on `artifact_kind`;
- index on `published_at`.

The object-store ETag may be recorded as metadata but must not be treated as the canonical content hash.

### `corpus.artifact_pages`

Represents physical pages in the acquired artifact.

Minimum fields:

- `id uuid primary key`;
- `artifact_id uuid not null`;
- `physical_page_number integer not null`;
- `printed_page_label text` when present;
- `native_text text`;
- `ocr_text text`;
- `normalized_text text`;
- `extraction_method text`;
- `ocr_confidence real`;
- `quality_status text not null`;
- `layout jsonb`;
- `created_at timestamptz not null`.

Unique constraint:

- `(artifact_id, physical_page_number)`.

Never overwrite native extraction with OCR/normalized text. They have different evidentiary status.

### `corpus.courts`

Minimum fields:

- `id uuid primary key`;
- `institution_code text not null`;
- `name text not null`;
- `short_name text`;
- `jurisdiction text`;
- `court_level text`;
- `active_from date`;
- `active_to date`.

### `corpus.court_organs`

The SCJ may issue decisions from Primera Sala, Segunda Sala, Tercera Sala, Salas Reunidas, Pleno, or other organs. These should not be uncontrolled free-text values on every case.

Fields:

- `id uuid primary key`;
- `court_id uuid not null`;
- `code text not null`;
- `name text not null`;
- `organ_type text`;
- `active_from date`;
- `active_to date`.

### `corpus.cases`

This is the canonical legal decision identity.

Minimum source-fact fields:

- `id uuid primary key`;
- `court_id uuid not null`;
- `court_organ_id uuid`;
- `decision_number text`;
- `decision_number_normalized text`;
- `docket_number text`;
- `decision_date date`;
- `decision_date_status text not null`;
- `case_title text`;
- `procedure_type text`;
- `matter text`;
- `language text not null default 'es'`;
- `identity_status text not null`;
- `normalization_level smallint not null default 0`;
- `quality_status text not null`;
- `created_at timestamptz not null`;
- `updated_at timestamptz not null`.

`decision_date_status` should distinguish at least:

- `verified_primary_text`;
- `verified_official_metadata`;
- `parsed_high_confidence`;
- `parsed_unverified`;
- `conflicting`;
- `unknown`.

Do not manufacture dates to satisfy a NOT NULL constraint. An unknown date is safer than a plausible but false date.

### `corpus.case_artifact_occurrences`

Links a canonical case to one or more artifact representations and locates it inside compilations.

Minimum fields:

- `id uuid primary key`;
- `case_id uuid not null`;
- `artifact_id uuid not null`;
- `start_physical_page integer not null`;
- `end_physical_page integer not null`;
- `start_offset integer` when a case begins mid-page;
- `end_offset integer` when a case ends mid-page;
- `segment_method text not null`;
- `segment_confidence real`;
- `segment_status text not null`;
- `is_preferred_representation boolean not null default false`;
- `created_at timestamptz not null`.

This table is essential for compilation PDFs.

### `corpus.case_identifiers`

A case can carry more than one identifier, especially where expedition/case numbers have aliases or multiple linked procedural identifiers.

Fields:

- `id uuid primary key`;
- `case_id uuid not null`;
- `identifier_type text not null`;
- `raw_value text not null`;
- `normalized_value text`;
- `source_page_id uuid`;
- `is_primary boolean not null default false`.

Typical identifier types:

- `decision_number`;
- `docket_number`;
- `legacy_docket_number`;
- `source_specific_id`.

Do not force multiple expediente numbers into one opaque string if they can be represented individually.

### `corpus.case_parties`

Fields:

- `id uuid primary key`;
- `case_id uuid not null`;
- `party_name text not null`;
- `party_name_normalized text`;
- `role text not null`;
- `party_order integer`;
- `source_page_id uuid`.

SCJ headings commonly expose roles such as recurrente, recurrido, recurrente incidental, etc. Preserve the raw role and optionally map to a normalized role separately.

### `corpus.case_pages`

A case-level page/evidence projection that maps the legal decision back to physical artifact pages.

Fields:

- `id uuid primary key`;
- `case_id uuid not null`;
- `artifact_page_id uuid not null`;
- `case_page_number integer`;
- `page_order integer not null`;
- `text text not null`;
- `quality_status text not null`.

Unique constraints should prevent duplicate mappings for the same case occurrence where appropriate.

### `corpus.passages`

Retrieval units derived from a case.

Fields:

- `id uuid primary key`;
- `case_id uuid not null`;
- `page_start_id uuid not null`;
- `page_end_id uuid not null`;
- `passage_order integer not null`;
- `section_type text`;
- `text text not null`;
- `token_count integer`;
- `chunking_version text not null`;
- `fts tsvector`;
- `created_at timestamptz not null`.

Embeddings should be versioned separately or tied explicitly to an embedding model/index generation; do not make one embedding column a permanent invariant of the passage record.

### `corpus.case_citations`

Fields:

- `id uuid primary key`;
- `from_case_id uuid not null`;
- `to_case_id uuid`;
- `source_case_page_id uuid not null`;
- `raw_reference text not null`;
- `normalized_reference text`;
- `citation_context text`;
- `resolution_status text not null`;
- `resolution_confidence real`;
- `extraction_method text not null`;
- `created_at timestamptz not null`.

Unresolved citations must remain first-class records rather than being discarded.

## 6. Date semantics are a core legal feature

JurisNexo must treat legal time as structured data, not a text-search afterthought.

At minimum, distinguish:

- `decision_date`: date the SCJ issued/rendered the decision;
- `lower_court_decision_date`: date of the appealed/attacked decision, when captured;
- `filing_dates`: dates of appeals, memorials or procedural acts, when relevant;
- `publication/acquisition dates`: dates concerning the artifact/corpus lifecycle, not the legal decision itself.

These must never be collapsed into one generic `date` column.

### Why `decision_date` matters

Research frequently needs to answer questions such as:

- what was the governing SCJ position on a date relevant to the client's dispute?
- what later decisions treated or changed an earlier line of authority?
- is an apparently relevant decision actually later than the event/proceeding under analysis?
- which authority is newer within the same court/organ?
- did the SCJ repeat, limit, distinguish or abandon an earlier proposition over time?

Therefore `decision_date` is part of both retrieval and precedent analysis.

### Required indexes

At minimum:

```sql
create index ... on corpus.cases (decision_date desc);
create index ... on corpus.cases (court_id, decision_date desc);
create index ... on corpus.cases (court_organ_id, decision_date desc);
```

Later, partial/composite indexes should be driven by real query plans rather than guessed prematurely.

### Date filtering contract

The search service should support explicit temporal constraints:

```text
decided_before
decided_after
decided_between
as_of_date
```

`as_of_date` is semantically stronger than a normal filter. It means the research process should avoid relying on later authority as if it had existed at that historical point, while it may optionally discuss later treatment separately.

This distinction should be preserved in research-job configuration and report provenance.

## 7. Patterns already visible in modern SCJ decisions

Official SCJ material shows recurring header structures such as:

```text
Sentencia núm. SCJ-SR-25-00080
Recurso de Casación Laboral
Expediente núm.: ...
Recurrente ...
Recurrido ...
Ponente: ...
...
en fecha 31 del mes de julio del año 2025 ... dictan la sentencia siguiente
```

Other modern decisions expose fields such as `Materia`, multiple expediente numbers, and different organs/salas.

These are useful parser signals, but they are not guaranteed universal grammar.

The parser should therefore use layered extraction:

1. deterministic regex/header recognizers;
2. cross-field consistency checks;
3. deterministic normalization;
4. small LLM extraction only for unresolved/ambiguous metadata;
5. provenance and confidence for every non-trivial extraction.

The LLM is an exception handler/enrichment tool, not the only parser.

## 8. Metadata extraction contract

For every parsed source fact, persist:

- value;
- raw source text where useful;
- page/evidence location;
- extraction method;
- extractor/parser version;
- confidence/status;
- verification state when material.

For high-value fields such as `decision_date`, `decision_number`, `court`, and `court_organ`, the ingestion pipeline should reject silent contradictory values.

Example:

```text
filename implies 2025
header decision number implies 2025
body says decision date 31 July 2025
```

These agreeing signals increase confidence.

If they disagree, mark the case for review; do not simply choose whichever value the LLM emitted.

## 9. Embeddings and LLM-derived extraction

The database must be usable before an external LLM API is configured.

Phase 1 should support:

- artifact registration;
- checksums;
- page extraction;
- deterministic case-boundary detection experiments;
- deterministic header metadata extraction;
- FTS indexing;
- manual validation.

A small LLM can later be introduced for:

- ambiguous boundary classification;
- metadata fields not robustly captured by rules;
- section classification;
- legal issue/holding extraction;
- quality review candidates.

Model-derived rows must record at least:

- provider;
- model;
- model/version identifier;
- prompt/extractor version;
- invocation timestamp;
- input evidence reference;
- output confidence/verification status where applicable.

Do not allow model output to overwrite the raw page or source artifact.

## 10. Search/index generation model

Index configuration must be versioned.

Suggested supporting entities:

### `internal.embedding_models`

- provider;
- model name;
- dimensions;
- configuration;
- active dates.

### `internal.index_generations`

- generation id;
- corpus snapshot/reference;
- lexical configuration;
- embedding model;
- chunking version;
- fusion/reranking profile;
- created_at.

### `corpus.passage_embeddings`

Prefer a versionable relation such as:

- `passage_id`;
- `embedding_model_id`;
- `index_generation_id`;
- `embedding vector(...)`;
- `created_at`.

This permits benchmarking or re-embedding without mutating the semantic history of the passage.

## 11. Initial ingestion sequence

The first migration/schema implementation should be sufficient for this sequence:

```text
SCJ Jan-Apr 2025 compilation PDF
        -> source_artifact
        -> artifact_pages
        -> detected case occurrences
        -> canonical cases
        -> case identifiers / parties / dates
        -> case_pages
        -> passages
        -> lexical index
        -> manual validation dataset
```

Embeddings should be added only after the relational/provenance path is demonstrably correct.

## 12. Database-first implementation order

Recommended order:

1. PostgreSQL schemas and DB roles;
2. source registry + immutable artifact model;
3. artifact pages and extraction provenance;
4. courts and court organs;
5. canonical cases + case-artifact occurrences;
6. identifiers, parties, and temporal fields;
7. case pages and passages;
8. lexical indexes and stable search queries;
9. citation tables;
10. model/index version tables;
11. vector embeddings;
12. interpretive legal entities;
13. research/evidence/report tables;
14. tenant-private corpus extensions.

This sequence intentionally postpones embeddings and agent orchestration until the legal source model is trustworthy.

## 13. Tests that must exist before corpus expansion

Database/ingestion CI should prove at least:

- a compilation artifact can contain multiple canonical cases;
- a canonical case can appear in multiple artifacts;
- two byte-identical artifacts are detected without becoming two independent cases;
- physical PDF page and case page remain distinguishable;
- `decision_date` survives ingest/reingest unchanged;
- unknown/conflicting dates cannot silently become verified dates;
- case queries can filter by court/organ/date efficiently;
- citations may remain unresolved without violating integrity;
- parser/model reruns cannot overwrite the primary artifact;
- deleting/rebuilding embeddings does not delete cases/pages/evidence.

## 14. Immediate design decision

The first implementation work should target the database and deterministic ingestion path, not the research agent.

The first meaningful technical milestone is:

> Given the official SCJ January-April 2025 compilation, JurisNexo can persist the artifact, preserve every source page, identify decision boundaries, store the individual cases with defensible dates/identifiers, and reproduce the same records on re-ingestion.

Only after this is true should vector retrieval or model-heavy enrichment become a blocking priority.
