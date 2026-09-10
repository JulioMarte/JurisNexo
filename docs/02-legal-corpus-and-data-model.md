# JurisNexo — Legal Corpus and Data Model

## 1. Goal

The corpus layer must make Dominican jurisprudence searchable, comparable, auditable, and progressively enrichable without confusing primary legal sources with model-generated interpretation.

The data model should support the MVP today and deeper precedent intelligence later.

The concrete PostgreSQL implementation direction, including physical artifacts, compilation segmentation, date semantics, indexes, and migration order, is defined in [`17-database-schema-and-temporal-legal-metadata.md`](./17-database-schema-and-temporal-legal-metadata.md).

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

A source artifact is not necessarily a judicial decision. Official publications may be compilations containing many decisions. JurisNexo must model the physical artifact independently from the canonical cases contained in it.

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
- `decision_date_status`;
- `chamber` / normalized court organ;
- `matter`;
- `procedure_type`;
- `title`;
- `normalization_level`;
- `language`;
- `ingestion_status`;
- `quality_status`.

Case identity should be normalized carefully because public sources may use inconsistent formatting.

`decision_date` is a first-class legal fact and must not be confused with filing dates, lower-court decision dates, publication dates, acquisition timestamps, or PDF metadata dates. Unknown or conflicting decision dates must remain explicitly unresolved rather than being guessed.

### `case_artifact_occurrences`

A canonical case may appear inside a compilation PDF, as a standalone PDF, or in multiple official representations.

This relation should preserve:

- `case_id`;
- source artifact;
- physical start/end page;
- offsets when a boundary occurs mid-page;
- segmentation method;
- segmentation confidence/status;
- preferred representation.

This prevents the false invariant `one PDF = one case`.

### `case_pages`

Suggested fields:

- `case_id`;
- physical artifact-page reference;
- legal/case page number when available;
- page order;
- text;
- OCR confidence when applicable;
- optional layout coordinates.

Page boundaries are first-class data because citations must be auditable.

Physical PDF page numbering and the page numbering printed inside a judicial decision must remain distinguishable.

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
- chunking/index generation metadata;
- vector embedding through a versioned relation when enabled;
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

## 4. Temporal legal metadata

Legal research is temporal. The database and search contracts must support chronology directly.

At minimum distinguish:

- decision date of the authority being researched;
- date of the lower-court decision being challenged;
- filing/procedural dates;
- artifact publication date;
- acquisition/indexing timestamps.

Search must eventually support `decided_before`, `decided_after`, ranges, and an `as_of_date` research constraint.

`as_of_date` has substantive meaning: authority issued later than that date must not be presented as if it were available law at the historical research point, although later treatment may be discussed separately.

Chronology is also required for later-treatment analysis: a newer decision may reiterate, limit, distinguish, clarify, conflict with, or supersede treatment associated with earlier authority. Recency alone never determines legal authority, but dates are necessary to reconstruct that evolution.

## 5. Interpretive entities

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

## 6. Provenance model

Every important extracted proposition should be traceable to:

```text
case
  -> source artifact
  -> physical page
  -> case/evidence page
  -> passage / exact supporting text
```

A report claim should ultimately point to this chain.

The system should allow the user to move from a generated conclusion to the exact source page with minimal friction.

## 7. OCR and born-digital documents

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

## 8. Normalization levels

### Level 0 — archived

The source exists and is immutable.

### Level 1 — searchable

Minimum viable normalized form:

- identity;
- court;
- decision date with provenance/status;
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

## 9. Lazy deep normalization

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

## 10. Corpus quality rules

A case should not be available for high-confidence citation if:

- source identity is unresolved;
- pages are materially missing;
- OCR quality is too poor for reliable reading;
- decision date or court is unresolved and material to authority;
- source provenance is missing.

The research runtime may still surface such a case with explicit warnings.

## 11. Search indexes

Initial indexes should support:

- case identifier exact search;
- court/chamber/date filters;
- chronological retrieval by court/organ;
- full-text ranking;
- legal-reference lookup;
- citation source/target traversal;
- optional vector retrieval.

Index implementation is replaceable. Stable query semantics matter more than selecting a fashionable search backend.

## 12. Tenant-private documents

Private organization uploads are a separate corpus class.

They must:

- be tagged with `organization_id`;
- use isolated authorization paths;
- never enter the globally shared jurisprudence index;
- never enrich shared legal intelligence unless an explicit future opt-in and review process exists;
- be deletable according to retention policy.

## 13. Data model principle

JurisNexo should preserve three epistemic layers:

1. **Primary source** — what the official legal document actually contains.
2. **Deterministically derived data** — metadata, resolved citations, indexes, counts.
3. **Interpretive knowledge** — holdings, material facts, legal issues, treatment, comparisons.

These layers must never be silently conflated.
