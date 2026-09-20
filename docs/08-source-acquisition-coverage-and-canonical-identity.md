# JurisNexo — Source Acquisition, Coverage, and Canonical Identity

## 1. Purpose

JurisNexo cannot claim trustworthy jurisprudential research unless it can answer three operational questions for every source:

1. Where did this decision come from?
2. Is this the authoritative or best available version?
3. How complete is our observed coverage of the court/time period we searched?

This document defines the acquisition, coverage, identity, deduplication and refresh contract. Corpus prioritization is governed by `38-jurisprudential-intelligence-flywheel-and-corpus-strategy.md`.

A critical distinction applies throughout:

```text
source breadth != semantic depth
```

JurisNexo should make trustworthy official material discoverable/acquirable/searchable as cheaply as practical while reserving expensive semantic normalization for material whose value justifies it.

## 2. Source registry

Maintain a registry of approved public sources. Each source should record source name, court/institution, source type, base URL/storage locator/acquisition mechanism, authority class, claimed or observed date range, acquisition cadence, implementation version, last successful sync, last observed change, known gaps and relevant usage notes.

Official sources are preferred. Mirrors may be used for resilience or discovery but must not silently replace provenance to an official source when the official source exists.

Existing object-storage material may be registered as acquisition input, but its presence is not proof of canonical identity, source authority, corpus completeness or successful ingestion.

Source-advertised date ranges are discovery evidence, not measured coverage. Store source claims separately from observed acquisition facts when they differ.

## 3. Acquisition contract

Acquisition must be idempotent and append evidence rather than mutate history silently.

For every acquired artifact retain, where available:

- source registry/document identity;
- source URL or stable locator;
- retrieval/import timestamp;
- HTTP/content metadata;
- original bytes;
- JurisNexo-computed cryptographic checksum;
- observed filename;
- MIME/media type;
- acquisition status;
- retry/error state.

If the same locator later produces different bytes, retain version history or explicitly record replacement. Do not overwrite earlier evidence without trace.

Provider metadata such as ETag may be retained as a signal, but it must not replace a JurisNexo-computed content hash for exact-byte identity.

### Progressive processing is allowed

Acquisition must not require every artifact to complete deep legal-semantic normalization before the artifact can contribute value.

A trustworthy artifact may progressively contribute to:

```text
coverage inventory
-> provenance
-> page-preserved text/OCR
-> lexical search
-> optional semantic search
-> citation observations
-> canonical resolution
-> selective deep normalization
```

Each state must be explicit. Failure to reach a deeper state must not be misrepresented as failure to acquire the source.

## 4. Physical artifacts are not canonical cases

A core invariant is:

```text
source artifact != judicial decision
```

A single PDF may contain many decisions. Conversely, one decision may appear through multiple URLs, PDFs, mirrors, editions, filenames or source collections.

Therefore the model distinguishes source documents/artifacts/pages from canonical judicial identity and preserves exact source occurrences.

## 5. Canonical case identity

Candidate identity evidence may include court, chamber/sala, decision number, docket/expediente, decision date, parties/title, source identifiers, text fingerprints and citation context.

Canonical resolution must be conservative, versioned and evidence-backed. When identity is uncertain, preserve unresolved observations rather than merge aggressively.

For compilations, reliable decision-boundary evidence may be necessary before a source occurrence can be assigned confidently to a canonical decision. The system must never infer one case per PDF by default.

## 6. Duplicate handling

Duplicates can arise from the same bytes under different locators, multiple official representations, re-publications/corrections, OCR-derived copies, mirrors or inconsistent metadata.

Use multiple signals including JurisNexo-computed file hash, normalized identifiers, court/date, docket, text fingerprint and source metadata.

Exact duplicate artifacts should not be re-parsed/re-embedded unnecessarily, while distinct observed locators may remain for provenance. Ambiguous logical duplicates remain separate until evidence supports resolution.

## 7. Decision-boundary provenance

For compilation artifacts, segmentation results must preserve artifact identity, start/end page, detection method/version, confidence/review state and supporting signals where practical.

If a boundary is ambiguous, represent uncertainty. Do not manufacture precision merely to satisfy downstream schemas.

Manual review should be possible, and high-signal/deep-normalization material should pass the accepted structure/extraction audit policy.

## 8. Source versions and corrections

A later official source may correct or replace a decision document.

Model this explicitly while preserving earlier artifacts. Research evidence must identify the exact artifact/version on which a claim relied.

## 9. Initial pilot versus source universe

The initial Supabase Storage inventory contained a useful SCJ seed collection, including Principales material. That inventory is a bootstrap asset, not the definition of the corpus universe.

The first canonical deep-validation artifact is documented in `16-pilot-corpus-and-first-mvp-validation-slice.md`.

In parallel with that controlled deep fixture, source acquisition should reconcile approved official SCJ surfaces and record what is actually discoverable and downloadable. Do not wait for every deep semantic benchmark to pass before learning what official material exists.

Likewise, do not interpret successful discovery/download as proof that a decision has been correctly segmented, canonicalized or semantically understood.

## 10. Coverage manifest

JurisNexo must not use phrases such as "we cover SCJ jurisprudence" without a measurable coverage statement.

Maintain coverage by relevant court/organ/time/source dimensions and distinguish at least:

```text
source-advertised claims
discovered records
downloadable artifacts
acquired artifacts
failed/unavailable downloads
segmented decisions
canonical decisions
searchable decisions
citation-linked decisions
deeply normalized decisions
unresolved boundaries/identities
known gaps
last reconciliation
```

A source record without a downloadable artifact is still useful coverage evidence and should be represented as discovered-but-unavailable rather than silently disappearing.

"Discovered" is not proof of total institutional completeness. "Acquired" is not proof of canonical correctness. "Searchable" is not proof of deep legal normalization.

These distinctions are product features, not bookkeeping trivia.

## 11. Freshness and reconciliation

Each source has a synchronization/reconciliation policy.

Track last successful discovery scan, last acquisition attempt, newest observed publication/decision date where meaningful, backlog, failed/unavailable acquisition count, source changes and stale-source warning thresholds.

A report should disclose material freshness limitations when recent authority could affect the research result.

## 12. Source and processing states

The implementation may use a richer state model than one linear enum because discovery, acquisition, extraction, identity and semantic normalization are partially independent axes.

At minimum the system must be able to express conditions equivalent to:

- discovered but not downloadable;
- acquired;
- parse/OCR required or completed;
- segmentation review required;
- identity unresolved/canonical/probable duplicate;
- searchable;
- blocked;
- superseded;
- deeply normalized/verified where applicable.

Do not force all lifecycle dimensions into one misleading linear state if the real workflow is not linear.

## 13. Storage data-class boundaries

Public legal source artifacts and tenant-private artifacts must not inherit the same access policy merely because one storage provider hosts both.

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

Existing pilot buckets may serve as acquisition inputs. They must not become the default policy boundary for private tenant material.

## 14. Legal and operational caution

Before automated bulk acquisition from any source, review its public access method, technical restrictions, terms, robots behavior where applicable, and availability of official bulk feeds or alternative lawful access mechanisms.

Synchronization should be respectful, cache-friendly and incremental. Unchanged artifacts should not be downloaded repeatedly without reason.

Acquisition code should degrade gracefully: one unavailable/non-downloadable record should be recorded as such rather than destroying a complete reconciliation run or losing the manifest.

## 15. MVP Definition of Done

Source acquisition is MVP-ready when:

- at least one real SCJ compilation can be registered and deeply ingested repeatably;
- original source artifacts remain immutable;
- compilation PDFs are segmented into individual candidate decisions rather than modeled as one case;
- exact-content duplicates do not silently create independent cases;
- case identity and boundary uncertainty are explicit;
- normalized evidence preserves exact artifact/page provenance;
- approved official source surfaces can be inventoried/reconciled idempotently;
- non-downloadable and failed acquisitions are represented without aborting the entire coverage record;
- discovered/acquired/searchable/deep-normalized coverage can be distinguished;
- freshness and known gaps can be surfaced;
- a report can identify the exact source artifact/version/pages it relied on.

The existence of many PDFs is not sufficient. Conversely, deep normalization of every acquired artifact is not required before source acquisition can be considered operationally useful.

## 16. Governing rule

The acquisition layer should maximize trustworthy optionality:

> preserve official source evidence broadly and cheaply; resolve identity conservatively; make reliable text searchable when practical; spend expensive semantic analysis where jurisprudential/research value warrants it.

This is the acquisition counterpart of the flywheel strategy in document 38.


## 17. Operational acquisition topology

Production acquisition is source-scoped. JurisNexo does not use one workflow that acquires multiple courts and then performs normalization, linking, or semantic ingestion in the same orchestration.

The current operational shape is:

```text
official source
    -> source-specific discovery/inventory
    -> source-specific certification
    -> immutable artifact acquisition
    -> source-specific reconciliation

later, independently
    -> corpus registration / normalization
    -> structure and extraction pipeline
    -> semantic enrichment
```

For the current SCJ decisions corpus, the production workflow is `.github/workflows/scj-1994-full-storage-backfill.yml` (legacy filename; its runtime scope is dynamically discovered SCJ official decisions, not a hard-coded 1994+ contract).

Rules for production acquisition:

- one court/source family per production backfill workflow;
- acquisition must not silently expand into another court;
- acquisition must not require semantic normalization to finish successfully;
- PostgreSQL corpus registration, source-document linking, segmentation, OCR normalization, and legal-semantic enrichment are separate downstream concerns;
- a future TC acquisition path must have its own workflow and source-specific inventory/reconciliation contract rather than being appended to the SCJ workflow;
- cross-source scheduled orchestration may be introduced later only when the individual source pipelines are independently proven and there is a demonstrated operational need.

This separation keeps recovery, provenance, source drift, manifests, and failures attributable to one source boundary at a time.
