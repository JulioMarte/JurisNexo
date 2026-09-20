# JurisNexo — Document normalization and derived artifacts

## Status

Current architecture contract for the boundary between official-source acquisition
and document normalization.

## 1. Separation of responsibilities

Acquisition and normalization are different workflows.

```text
official source
    -> exact source bytes
    -> SHA-256
    -> object storage
    -> immutable acquisition manifest
    -> normalization run
    -> OCR/layout/Docling when needed
    -> immutable derived artifacts
    -> searchable/legal extraction
```

Acquisition is complete when the official source observation has been accounted
for and the immutable acquisition manifest is closed. Docling, OCR and vision
processing do not participate in acquisition closure.

A normalization failure must never invalidate or erase an already preserved
official artifact.

## 2. Primary source versus derived artifact

`corpus.source_artifacts` remains the catalog of preserved source bytes.

Derived outputs live separately in `corpus.derived_artifacts`. Examples include:

- OCR-enhanced PDF;
- Docling document JSON;
- ALTO/PAGE layout output;
- page images;
- normalized plain text.

A derived artifact is immutable and content-addressed by SHA-256. PostgreSQL
stores its identity, MIME type, size and object-storage locator. The large
payload itself remains in object storage.

Do not store a complete multi-megabyte Docling document in a PostgreSQL JSONB
column merely because PostgreSQL can hold it.

## 3. Explicit lineage

`corpus.artifact_derivations` records how an output was produced.

A derivation has exactly one parent:

- a preserved `source_artifact`; or
- an earlier `derived_artifact`.

This permits chains such as:

```text
official scan
    -> OCR PDF
    -> Docling JSON
```

and direct paths such as:

```text
born-digital PDF/DOCX
    -> Docling JSON
```

Each edge records:

- derivation type;
- engine;
- engine version when available;
- JurisNexo pipeline version;
- configuration SHA-256;
- bounded JSON configuration/parameters.

Derived-artifact cycles are rejected by PostgreSQL.

## 4. Normalization runs

`corpus.normalization_runs` is the durable execution ledger for one immutable
acquisition-manifest input.

It records:

- manifest locator and SHA-256;
- pipeline version;
- configuration SHA-256;
- run state and counts;
- timestamps;
- small structured metadata.

`corpus.normalization_run_items` records one source artifact outcome per run,
including the optional OCR artifact, final normalized artifact, quality summary
and bounded failure information.

The manifest is therefore the handoff boundary:

```text
acquisition manifest closed
        |
        v
normalization run
```

The future normalizer must validate the referenced acquisition manifest before
creating/executing work. This migration models that provenance but does not
pretend PostgreSQL can validate object-storage manifest contents by itself.

## 5. Docling storage contract

The canonical Docling representation is an immutable derived object in S3-compatible
storage, for example conceptually:

```text
derived/normalization/docling/<version>/<sha256>.json
```

The exact object-key layout is an implementation concern and may evolve while
identity remains SHA-256 based.

PostgreSQL may materialize query-critical projections later, such as page text,
blocks or search fields, but those projections do not replace the complete
Docling JSON artifact.

## 6. OCR and vision

OCR/vision outputs are also derived data. They never overwrite official bytes.

A typical scanned-document lineage may be:

```text
official PDF
    -> OCR PDF/text
    -> Docling JSON
```

A stronger vision-model correction may produce another versioned derivation
rather than mutating an earlier result. Engine/model identity, version and
configuration belong in derivation/run provenance.

## 7. Legal-model boundary

Normalization answers:

> What document structure/text can we faithfully reconstruct?

Legal extraction answers:

> What does that source mean legally?

Docling output, OCR output and vision-model transcription are not automatically
canonical legal truth. Existing evidence/audit gates still control promotion to
legal issues, facts, propositions, treatments and other canonical semantics.

## 8. Implementation handoff

The complete operational V2 plan — benchmark strategy, manifest planner, source profiling,
OCR selection, deterministic QA, JEV shadow mode, sentinel sampling, visual verification,
correction assertions, privacy/provider gates, resumability, reconciliation and promotion
criteria — lives in:

- `41-universal-legal-document-normalization-control-plane-v3-handoff.md` — current implementation handoff;
- `40-document-normalization-pipeline-v2-handoff.md` — retained V2 quality/provenance rationale where not superseded.

V3 is the implementation sequence for this architecture. This document remains the stable artifact/provenance contract.

## 8. Initial implementation scope

Migration `0048_document_normalization_artifacts` establishes only the durable
database substrate:

- `derived_artifacts`;
- `artifact_derivations`;
- `normalization_runs`;
- `normalization_run_items`.

It does not yet run Docling, OCR or a vision model. Those workers should be
implemented separately after this persistence boundary is proven in CI.
