# JurisNexo — Source Acquisition, Coverage, and Canonical Identity

## 1. Purpose

JurisNexo cannot claim trustworthy jurisprudential research unless it can answer three operational questions for every source:

1. Where did this decision come from?
2. Is this the authoritative or best available version?
3. How complete is our coverage of the court/time period we claim to search?

This document defines the MVP contract for source acquisition, corpus coverage, identity, deduplication, and refresh.

## 2. Source registry

Maintain a registry of approved public sources. Each source should record:

- source name;
- court/institution;
- source type (official site, official repository, manual import, trusted mirror, preloaded object storage);
- base URL, storage locator, or acquisition mechanism;
- authority class;
- supported date range if known;
- acquisition cadence;
- parser/downloader implementation version;
- last successful sync;
- last observed source change;
- known gaps;
- terms/usage notes where relevant.

Official sources are preferred. Mirrors may be used for resilience or discovery but must not silently replace provenance to an official source when the official source exists.

Existing Supabase Storage objects may be registered as acquisition inputs for the MVP, but their presence in object storage is not itself proof of canonical identity, source authority, corpus completeness, or successful ingestion.

## 3. Acquisition contract

Acquisition must be idempotent and append evidence rather than mutate history silently.

For every acquired artifact store:

- `source_registry_id`;
- source URL or stable locator;
- retrieval/import timestamp;
- HTTP/content metadata when available;
- original bytes;
- JurisNexo-computed cryptographic checksum;
- observed filename;
- MIME type;
- acquisition status;
- retry/error state.

If the same URL later produces different bytes, retain version history or explicitly record replacement. Do not overwrite an earlier source artifact without trace.

Provider object metadata such as an ETag may be retained as an acquisition signal, but it must not replace a JurisNexo-computed content hash for exact-byte identity.

## 4. Physical artifacts are not canonical cases

A core MVP invariant is:

```text
source artifact != judicial decision
```

A single PDF may contain many judicial decisions, as is the case with Supreme Court principal-decision compilations. Conversely, one judicial decision may be represented by multiple URLs, PDFs, mirrors, editions, or filenames.

Therefore the model must distinguish at least:

```text
source_artifact
    -> artifact pages
    -> candidate/canonical judicial cases
```

A case must preserve the exact artifact page span that supports its normalized representation.

## 5. Canonical case identity

A judicial decision may appear under multiple URLs, filenames, formatting conventions, compilations, or mirrors. JurisNexo therefore needs a stable internal identity independent of one source URL or physical PDF.

Candidate identity fields include:

- court;
- chamber/sala where applicable;
- decision number;
- docket/expediente number;
- decision date;
- parties/title where available;
- source-specific identifiers.

The canonical identity algorithm must be deterministic, versioned, and conservative.

When identity is uncertain, retain multiple source artifacts and mark the case as unresolved rather than merging aggressively.

For compilation PDFs, decision-boundary detection is a prerequisite for canonical identity. The system must not infer one case per PDF.

## 6. Duplicate handling

Duplicates can arise from:

- the same PDF exposed under multiple filenames or storage objects;
- the same PDF exposed at multiple URLs;
- HTML and PDF representations of one decision;
- re-published or corrected decisions;
- OCR-derived copies;
- mirrors;
- files with inconsistent decision-number formatting.

Use multiple signals:

- JurisNexo-computed exact file hash;
- normalized decision number;
- court/date;
- docket number;
- normalized text fingerprint;
- source metadata;
- provider object metadata as a secondary signal.

Duplicate confidence must be persisted. High-confidence duplicates may point to one canonical case. Ambiguous records must remain separate until resolved.

The initial Supabase Storage inventory already contains duplicate-content Supreme Court objects with different filenames, including duplicate variants in the 2024 collection. This is direct evidence that exact-content deduplication is required in the MVP rather than a hypothetical future optimization.

Exact duplicate artifacts should not be re-parsed and re-embedded unnecessarily. Their distinct observed locators may still be retained for provenance.

## 7. Decision-boundary provenance

For compilation artifacts, segmentation results must preserve:

- artifact ID;
- start page;
- end page;
- detection method/version;
- confidence or review state;
- supporting boundary signals where practical.

If a case begins or ends ambiguously, the system must represent that uncertainty. It must not manufacture page precision merely to satisfy downstream schemas.

Manual review should be possible for segmentation before broad corpus expansion.

## 8. Source versions and corrections

A later official source may correct a decision document.

Model this explicitly:

```text
case
  -> source_artifact v1
  -> source_artifact v2 (later/corrected)
```

The system should identify the preferred current source while preserving earlier artifacts for auditability.

A research report must record which source artifact/version supported its claims.

## 9. Initial pilot inventory

At the time the MVP corpus plan was defined, the JurisNexo Supabase Storage project contained approximately:

- 34 Supreme Court PDFs;
- approximately 243.84 MB of Supreme Court source material;
- material spanning approximately 2005 through early 2025;
- recent compilations covering 2023, 2024, and early 2025.

This inventory is not equivalent to known complete institutional coverage.

The first canonical pilot artifact is documented in `16-pilot-corpus-and-first-mvp-validation-slice.md` and should be processed before bulk historical expansion.

## 10. Coverage manifest

JurisNexo must not use phrases such as "we cover SCJ jurisprudence" without a measurable coverage statement.

Maintain a coverage manifest by at least:

- court;
- chamber when material;
- year/month;
- number of discovered records;
- number successfully acquired;
- number of compilation artifacts segmented;
- number of candidate decisions detected;
- number of canonical decisions resolved;
- number parsed;
- number searchable;
- number blocked by OCR/source quality;
- unresolved boundary count;
- unresolved identity count;
- known source gaps.

Example:

```text
SCJ / Primera Sala / 2024
Discovered artifacts: 3
Candidate decisions detected: 1,200
Canonical decisions resolved: 1,188
Searchable: 1,174
OCR/source blocked: 6
Boundary/identity unresolved: 8
```

"Discovered" is not proof of total institutional completeness. The UI and reports should distinguish corpus coverage from certainty about the institution's total publication universe.

## 11. Freshness

Each source has a synchronization policy.

Track:

- last successful acquisition scan;
- newest indexed decision date;
- backlog count;
- failed acquisition count;
- stale-source warning threshold.

A report should disclose material freshness limitations when recent authority could change the conclusion.

## 12. Source quality states

Suggested artifact states:

- `DISCOVERED`;
- `ACQUIRED`;
- `PARSED`;
- `OCR_REQUIRED`;
- `OCR_COMPLETE`;
- `SEGMENTATION_REVIEW_REQUIRED`;
- `QUALITY_REVIEW_REQUIRED`;
- `SEARCHABLE`;
- `BLOCKED`;
- `SUPERSEDED`.

Suggested case identity states:

- `CANONICAL`;
- `PROBABLE_DUPLICATE`;
- `IDENTITY_UNRESOLVED`;
- `MERGED_WITH_CANONICAL`.

Suggested boundary states:

- `BOUNDARY_CONFIRMED`;
- `BOUNDARY_PROBABLE`;
- `BOUNDARY_REVIEW_REQUIRED`.

## 13. Storage data-class boundaries

Public legal source artifacts and tenant-private artifacts must not inherit the same access policy merely because Supabase Storage hosts both.

Recommended logical separation:

```text
public-legal-sources/
    SCJ/
    TC/

private-tenant-documents/
    <organization_id>/

private-generated-reports/
    <organization_id>/
```

The current `docs-sentencia` bucket may serve as an existing pilot source location. It must not become the default bucket for private uploads or generated tenant reports.

## 14. Legal and operational caution

Before automated bulk acquisition from any source, review its public access method, technical restrictions, terms, robots behavior where applicable, and availability of official bulk feeds or alternative lawful access mechanisms.

The MVP should prefer respectful, cache-friendly synchronization and avoid repeatedly downloading unchanged artifacts.

## 15. MVP Definition of Done

Source acquisition is MVP-ready when:

- at least one real SCJ compilation can be registered and ingested repeatably;
- original source artifacts remain immutable;
- compilation PDFs are segmented into individual candidate decisions rather than modeled as one case;
- exact-content duplicates do not silently create multiple independent cases;
- case identity and boundary uncertainty are represented explicitly;
- normalized evidence preserves exact artifact/page provenance;
- coverage and freshness can be measured;
- a report can identify the exact source artifact/version and pages it relied on;
- known corpus gaps can be surfaced to users.

The existence of many PDFs in Storage is not sufficient to satisfy this Definition of Done.
