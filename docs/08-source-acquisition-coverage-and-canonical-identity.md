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
- source type (official site, official repository, manual import, trusted mirror);
- base URL or acquisition mechanism;
- authority class;
- supported date range if known;
- acquisition cadence;
- parser/downloader implementation version;
- last successful sync;
- last observed source change;
- known gaps;
- terms/usage notes where relevant.

Official sources are preferred. Mirrors may be used for resilience or discovery but must not silently replace provenance to an official source when the official source exists.

## 3. Acquisition contract

Acquisition must be idempotent and append evidence rather than mutate history silently.

For every acquired artifact store:

- `source_registry_id`;
- source URL or stable locator;
- retrieval timestamp;
- HTTP/content metadata when available;
- original bytes;
- cryptographic checksum;
- observed filename;
- MIME type;
- acquisition status;
- retry/error state.

If the same URL later produces different bytes, retain version history or explicitly record replacement. Do not overwrite an earlier source artifact without trace.

## 4. Canonical case identity

A judicial decision may appear under multiple URLs, filenames, formatting conventions, or mirrors. JurisNexo therefore needs a stable internal identity independent of one source URL.

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

## 5. Duplicate handling

Duplicates can arise from:

- the same PDF exposed at multiple URLs;
- HTML and PDF representations of one decision;
- re-published or corrected decisions;
- OCR-derived copies;
- mirrors;
- files with inconsistent decision-number formatting.

Use multiple signals:

- exact file hash;
- normalized decision number;
- court/date;
- docket number;
- normalized text fingerprint;
- source metadata.

Duplicate confidence must be persisted. High-confidence duplicates may point to one canonical case. Ambiguous records must remain separate until resolved.

## 6. Source versions and corrections

A later official source may correct a decision document.

Model this explicitly:

```text
case
  -> source_artifact v1
  -> source_artifact v2 (later/corrected)
```

The system should identify the preferred current source while preserving earlier artifacts for auditability.

A research report must record which source artifact/version supported its claims.

## 7. Coverage manifest

JurisNexo must not use phrases such as "we cover SCJ jurisprudence" without a measurable coverage statement.

Maintain a coverage manifest by at least:

- court;
- chamber when material;
- year/month;
- number of discovered records;
- number successfully acquired;
- number parsed;
- number searchable;
- number blocked by OCR/source quality;
- unresolved identity count;
- known source gaps.

Example:

```text
SCJ / Primera Sala / 2024
Discovered: 1,200
Acquired: 1,188
Searchable: 1,174
OCR/source blocked: 6
Identity unresolved: 8
Known coverage: 97.8% of discovered records
```

"Discovered" is not proof of total institutional completeness. The UI and reports should distinguish corpus coverage from certainty about the institution's total publication universe.

## 8. Freshness

Each source has a synchronization policy.

Track:

- last successful acquisition scan;
- newest indexed decision date;
- backlog count;
- failed acquisition count;
- stale-source warning threshold.

A report should disclose material freshness limitations when recent authority could change the conclusion.

## 9. Source quality states

Suggested artifact states:

- `DISCOVERED`;
- `ACQUIRED`;
- `PARSED`;
- `OCR_REQUIRED`;
- `OCR_COMPLETE`;
- `QUALITY_REVIEW_REQUIRED`;
- `SEARCHABLE`;
- `BLOCKED`;
- `SUPERSEDED`.

Suggested case identity states:

- `CANONICAL`;
- `PROBABLE_DUPLICATE`;
- `IDENTITY_UNRESOLVED`;
- `MERGED_WITH_CANONICAL`.

## 10. Legal and operational caution

Before automated bulk acquisition from any source, review its public access method, technical restrictions, terms, robots behavior where applicable, and availability of official bulk feeds or alternative lawful access mechanisms.

The MVP should prefer respectful, cache-friendly synchronization and avoid repeatedly downloading unchanged artifacts.

## 11. MVP Definition of Done

Source acquisition is MVP-ready when:

- at least one SCJ/TC source can be synchronized repeatably;
- original source artifacts remain immutable;
- duplicates do not silently create multiple independent cases;
- case identity uncertainty is represented explicitly;
- coverage and freshness can be measured;
- a report can identify the exact source version it relied on;
- known corpus gaps can be surfaced to users.
