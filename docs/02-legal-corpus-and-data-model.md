# JurisNexo — Legal Corpus and Data Model

## 1. Goal

The corpus layer must make Dominican jurisprudence searchable, comparable, auditable, and progressively enrichable without confusing primary legal sources with model-generated interpretation.

The data model should support the MVP today and deeper precedent intelligence later.

## 2. Source hierarchy

Every record must retain its origin.

Primary source classes:

- Supreme Court of Justice decisions;
- Constitutional Court decisions;
- later court sources added explicitly;
- official legislative or administrative sources when introduced.

For each source artifact retain:

- canonical source URL when available;
- acquisition timestamp;
- original filename;
- checksum/hash;
- MIME type;
- extraction method;
- OCR status;
- parser version;
- page count;
- source authority metadata.

Never discard the original source after extraction.

## 3. Core entities

### `courts`

Suggested fields:

- `id`;
- `name`;
- `short_name`;
- `jurisdiction`;
- `level`;
- `authority_rank`;
- `active_from` / `active_to` where relevant.

`authority_rank` is a retrieval signal, not a substitute for legal analysis.

### `cases`

Suggested fields:

- `id`;
- `court_id`;
- `decision_number`;
- `case_number` / docket identifier when available;
- `decision_date`;
- `chamber`;
- `matter`;
- `procedure_type`;
- `title`;
- `source_artifact_id`;
- `normalization_level`;
- `language`;
- `ingestion_status`;
- `quality_status`.

Case identity should be normalized carefully because public sources may use inconsistent formatting.

### `case_pages`

Suggested fields:

- `case_id`;
- `page_number`;
- `text`;
- `ocr_confidence` when applicable;
- `page_image_ref` when applicable;
- optional layout coordinates.

Page boundaries are first-class data because citations must be auditable.

### `passages`

Passages are retrieval units, not authoritative units.

Suggested fields:

- `id`;
- `case_id`;
- `page_start`;
- `page_end`;
- `text`;
- `section_type` if known;
- `token_count`;
- vector embedding when enabled;
- full-text search representation.

Chunking should preserve provenance and should never prevent reconstructing the original page context.

### `case_citations`

Represents explicit references from one case to another.

Suggested fields:

- `from_case_id`;
- `to_case_id` when resolved;
- `raw_reference`;
- `page_number`;
- `citation_context`;
- `resolution_status`;
- `resolution_confidence`;
- `extraction_method`.

An explicit citation is different from an inferred jurisprudential relationship.

### `legal_references`

Represents laws, articles, regulations, constitutional provisions, and other referenced authorities.

Suggested fields:

- normalized identifier;
- authority type;
- title/name;
- article/section;
- raw citation;
- source evidence.

### `case_legal_references`

Links cases to legal references with page-level provenance.

## 4. Interpretive entities

Interpretive entities are model-derived and must remain distinguishable from primary-source facts.

### `case_issues`

- issue statement;
- normalized concept when available;
- evidence pages;
- extraction model/version;
- confidence;
- verification state.

### `case_holdings`

A case may contain multiple holdings.

Suggested fields:

- proposition text;
- issue association;
- source pages;
- scope;
- extraction model/version;
- confidence;
- verification status.

### `case_material_facts`

- fact proposition;
- issue association;
- source page;
- normalized factor label when available;
- confidence;
- verification state.

### `precedent_relations`

Possible relation types:

- `CITES`;
- `FOLLOWS`;
- `REITERATES`;
- `APPLIES`;
- `DISTINGUISHES`;
- `LIMITS`;
- `CLARIFIES`;
- `DEPARTS_FROM`;
- `OVERRULES`;
- `CONFLICTS_WITH`;
- `SUPERSEDED_BY_STATUTE`;
- `UNKNOWN_TREATMENT`.

Every non-explicit relation must record:

- source and target proposition/case;
- evidence;
- inferred versus explicit;
- model/version;
- confidence;
- verification status.

Do not collapse all graph relationships into a generic `RELATED_TO` edge.

## 5. Provenance model

Every important extracted proposition should be traceable to:

```text
case
  -> source artifact
  -> page
  -> passage / exact supporting text
```

A report claim should ultimately point to this chain.

The system should allow the user to move from a generated conclusion to the exact source page with minimal friction.

## 6. OCR and born-digital documents

Ingestion should first determine whether the source has usable native text.

### Born-digital

Prefer direct text extraction with page boundaries preserved.

### Scanned/image PDF

Use OCR or a document-understanding model, then preserve:

- original page image;
- OCR text;
- confidence or quality indicators;
- corrected/normalized text separately.

OCR output is derived data and must not replace the original image.

Low-confidence pages should be eligible for human review or stronger OCR processing.

## 7. Normalization levels

### Level 0 — archived

The source exists and is immutable.

### Level 1 — searchable

Minimum viable normalized form:

- identity;
- court;
- date;
- page text;
- FTS representation;
- provenance.

### Level 2 — linked

Adds:

- explicit case citations;
- legal references;
- chamber/matter/procedure metadata;
- citation resolution.

### Level 3 — interpreted

Adds:

- issues;
- holdings;
- material facts;
- outcome;
- precedent treatment candidates.

### Level 4 — verified intelligence

Adds human/model-audited:

- verified holdings;
- verified legal factors;
- verified precedent relationships;
- proposition-level graph edges;
- temporal treatment.

The MVP does not require Level 4 coverage across the whole corpus.

## 8. Lazy deep normalization

All cases should become cheaply searchable first.

Expensive semantic normalization should be demand-driven where useful.

Example:

```text
100,000 searchable cases
        |
        +-- rarely retrieved -> Level 1/2 remains sufficient
        |
        +-- frequently relevant -> promote to Level 3
        |
        +-- important precedent -> promote to Level 4 after verification
```

This makes cost proportional to legal importance and observed use.

## 9. Corpus quality rules

A case should not be available for high-confidence citation if:

- source identity is unresolved;
- pages are materially missing;
- OCR quality is too poor for reliable reading;
- decision date or court is unresolved and material to authority;
- source provenance is missing.

The research runtime may still surface such a case with explicit warnings.

## 10. Search indexes

Initial indexes should support:

- case identifier exact search;
- court/chamber/date filters;
- full-text ranking;
- legal-reference lookup;
- citation source/target traversal;
- optional vector retrieval.

Index implementation is replaceable. Stable query semantics matter more than selecting a fashionable search backend.

## 11. Tenant-private documents

Private organization uploads are a separate corpus class.

They must:

- be tagged with `organization_id`;
- use isolated authorization paths;
- never enter the globally shared jurisprudence index;
- never enrich shared legal intelligence unless an explicit future opt-in and review process exists;
- be deletable according to retention policy.

## 12. Data model principle

JurisNexo should preserve three epistemic layers:

1. **Primary source** — what the official legal document actually contains.
2. **Deterministically derived data** — metadata, resolved citations, indexes, counts.
3. **Interpretive knowledge** — holdings, material facts, legal issues, treatment, comparisons.

These layers must never be silently conflated.
