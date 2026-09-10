# JurisNexo — Pilot Corpus and First MVP Validation Slice

## 1. Purpose

JurisNexo already has a useful body of Supreme Court source material available in the Supabase project used for the product. This materially changes the first implementation milestone: the MVP does not need to begin by discovering an abstract sample corpus. It can begin by proving the complete ingestion and retrieval path against real Dominican Supreme Court material that is already available.

This document defines the initial pilot corpus, what it is allowed to prove, what it does not prove, and the order in which the corpus should expand.

## 2. Current available source material

As of the initial inventory, Supabase Storage contains approximately:

- 34 PDF files under the Supreme Court collection;
- approximately 243.84 MB of source PDFs;
- compilations spanning approximately 2005 through 2025;
- recent compilations for 2022, 2023, 2024, and early 2025;
- older annual or volume-based compilations for multiple prior years.

The available files include, among others:

- `Principales_Decisiones_enero_abril_2025.pdf`;
- `Principales_Decisiones_enero_abril_2024.pdf`;
- `Principales_Decisiones_mayo_agosto_2024.pdf`;
- `Principales-Decisiones-septiembre-diciembre-2024.pdf`;
- corresponding recent Supreme Court compilations for 2023 and 2022;
- historical principal-decision/sentence compilations reaching back to approximately 2005.

These files are source artifacts, not yet a trustworthy normalized legal corpus.

At inventory time, the existing application-level tables such as `sources` and `chunks` did not contain an ingested corpus. This is useful: the MVP can exercise the new ingestion architecture from source artifact to searchable evidence rather than inheriting undocumented transformations.

## 3. First canonical pilot artifact

The first ingestion fixture should be:

```text
Suprema Corte PDF/Principales_Decisiones_enero_abril_2025.pdf
```

This should be treated as an immutable source artifact and retained byte-for-byte.

It is intentionally a compilation rather than assuming one PDF equals one judicial decision.

### Critical invariant

```text
physical PDF artifact != canonical judicial case
```

A source PDF may contain multiple judicial decisions. One judicial decision may also later be observed through multiple physical artifacts, mirrors, editions, or filenames.

The data model and ingestion implementation must preserve this distinction from the first production-quality test.

## 4. Expected ingestion transformation

The first vertical ingestion path should prove:

```text
Supabase Storage PDF
        -> register immutable source artifact
        -> calculate cryptographic content hash
        -> extract page-preserving text
        -> detect extraction/OCR quality
        -> identify decision boundaries
        -> create candidate judicial decisions
        -> extract candidate case identity metadata
        -> resolve or flag canonical identity
        -> associate each case with exact artifact pages
        -> create page/passage records
        -> extract explicit legal citations where reliable
        -> build lexical search representation
        -> build configured semantic embeddings
        -> quality checks
        -> searchable corpus generation
```

No stage is allowed to destroy the ability to trace normalized text back to the original artifact and page.

## 5. Decision-boundary detection is a first-class MVP problem

The first source is a compilation. Therefore the ingestion pipeline must not simply chunk the complete PDF as one document and call it a case.

The pipeline must attempt to identify individual judicial decisions and their page spans.

Candidate signals may include:

- court/chamber headings;
- decision or sentence identifiers;
- dates;
- case/expediente identifiers;
- parties;
- repeated formal opening patterns;
- dispositive sections;
- table-of-contents information when present;
- layout and page transitions.

Boundary detection may use deterministic parsing, model-assisted extraction, or both, but its result must be persisted with provenance and confidence.

When a boundary is uncertain, the system must mark it as requiring review rather than fabricate precision.

## 6. Canonical identity versus artifact identity

For every candidate decision, JurisNexo should attempt to produce a stable canonical identity using available fields such as:

- court;
- chamber/sala;
- decision number;
- expediente/docket number;
- decision date;
- parties/title where available;
- source-specific identifiers.

The physical artifact remains separately identifiable by its checksum and storage locator.

This allows:

```text
canonical case
    -> artifact A pages 100-118
    -> artifact B pages 45-63
```

without falsely creating two independent cases.

## 7. Real duplicate evidence already exists

The current Storage inventory already contains at least two pairs of files whose object metadata indicates identical content despite different filenames.

Examples observed during inventory include duplicate-content variants for:

- the first 2024 period;
- the September-December / third-period 2024 compilation.

This means deduplication is not merely a theoretical future concern.

### Requirement

The ingestion pipeline must calculate its own cryptographic content hash and must not rely solely on filenames or storage-provider object metadata for canonical deduplication.

If two artifacts contain exactly the same bytes:

- retain their observed source/storage identities when useful for provenance;
- identify the duplicate-content relationship;
- avoid processing the same bytes repeatedly unless explicitly requested;
- never create duplicate canonical judicial decisions merely because filenames differ.

Provider ETags may be retained as acquisition metadata, but JurisNexo's own content hash is authoritative for exact-byte deduplication.

## 8. Pilot corpus expansion order

Do not ingest all available historical files immediately merely because they exist.

The recommended sequence is:

### Stage A — one compilation

Ingest only the early-2025 Supreme Court compilation.

Objectives:

- validate parser quality;
- validate page preservation;
- validate decision-boundary detection;
- validate canonical case extraction;
- expose OCR or formatting problems;
- validate idempotent re-ingestion;
- construct the first search/evaluation fixture.

### Stage B — one complete recent year plus adjacent period

After Stage A passes manual quality review, expand to the recent 2024 and 2023 compilations.

Recommended target set:

```text
2025 Jan-Apr
2024 Jan-Apr
2024 May-Aug
2024 Sep-Dec
2023 Jan-Apr
2023 May-Aug
2023 Sep-Dec
```

This produces a compact but temporally meaningful recent corpus and is more useful for product experiments than indiscriminately importing twenty years immediately.

### Stage C — controlled historical expansion

Only after ingestion and retrieval metrics are stable should JurisNexo expand systematically into older Supreme Court compilations.

Historical expansion should be driven by:

- benchmark gaps;
- lawyer research needs;
- matter/domain coverage;
- missing precedent chains;
- corpus freshness/coverage goals;
- processing quality.

## 9. Two independent MVP proofs

The first corpus must support two distinct categories of validation.

### 9.1 Ingestion proof

Question:

> Can JurisNexo reliably transform a real Supreme Court compilation into canonical, page-traceable, searchable judicial decisions?

Success requires evidence that:

- the artifact is immutable and hashed;
- pages are preserved;
- individual decisions are not conflated;
- case metadata is acceptably extracted;
- uncertain identities/boundaries are explicitly represented;
- repeat ingestion is idempotent;
- duplicate artifacts do not become duplicate cases;
- normalized text can always be traced to source pages.

### 9.2 Product/retrieval proof

Question:

> Given a real legal research question whose relevant authorities are present in the pilot corpus, can JurisNexo find the material decisions, including adverse authority, and provide auditable evidence?

Success requires:

- a manually reviewed seed benchmark;
- known relevant cases for each test question where possible;
- retrieval Recall@K and nDCG measurements;
- Critical Miss Rate measurement;
- adverse-authority recall where applicable;
- exact citation/evidence page verification;
- documented retrieval configuration and corpus generation.

Successful PDF parsing alone is not MVP success.

Successful vector embedding generation alone is not MVP success.

## 10. Initial benchmark creation from the pilot corpus

Once Stage A decisions have been manually inspected, create an initial benchmark of approximately 10-20 legal questions grounded in material actually present in the pilot corpus.

The questions should include variation such as:

- exact legal-reference lookup;
- doctrinal/legal-principle search;
- fact-pattern similarity;
- supporting authority;
- adverse or limiting authority;
- citation-chain discovery;
- date/chamber constraints.

The benchmark must not be generated entirely by the same model that will be evaluated without human review. A legal reviewer should establish or validate relevant authorities and material evidence.

The first benchmark is diagnostic rather than statistically definitive. Its purpose is to expose architecture failures early.

## 11. Retrieval experiments enabled by the pilot

The same frozen corpus generation should be used to compare:

```text
lexical only
semantic only
lexical + semantic + RRF
lexical + semantic + RRF + reranker
```

Additional experiments may compare:

- passage-level versus case-level semantic representations;
- general multilingual versus legal-specific embeddings;
- candidate limits;
- chunking/passaging strategies;
- query decomposition;
- citation expansion.

Every experiment must use versioned retrieval profiles so results can be reproduced.

## 12. Storage policy

The currently observed `docs-sentencia` bucket is suitable as an existing source-material location for the pilot, but bucket structure for the product must preserve data-class boundaries.

Recommended target logical separation:

```text
public-legal-sources/
    SCJ/
    TC/

private-tenant-documents/
    <organization_id>/

private-generated-reports/
    <organization_id>/
```

Public jurisprudential sources and private tenant documents must never share an access policy merely for convenience.

A currently public source bucket does not establish the access policy for future tenant uploads or generated reports.

## 13. What is already ready

The project has already removed several bootstrap uncertainties:

- a functioning Supabase project exists;
- PostgreSQL is available;
- Supabase Storage is available;
- a nontrivial Supreme Court source collection already exists;
- recent and historical source material is present;
- real duplicate-content cases exist for exercising deduplication;
- product, architecture, tenancy, research, evidence, benchmark, stack, CI, Docker, and deployment contracts are documented.

This materially reduces startup friction.

## 14. What is not yet ready

The existence of the PDFs must not be confused with having a legal corpus.

The following remain unproven until implemented and measured:

- quality of text extraction from these specific SCJ PDFs;
- page-number fidelity;
- decision-boundary detection;
- canonical identity accuracy;
- citation extraction/resolution accuracy;
- OCR requirements;
- chunk/passaging quality;
- embedding quality for Dominican Spanish jurisprudence;
- retrieval recall;
- adverse-authority retrieval;
- research-agent correctness;
- report claim/evidence verification;
- corpus completeness relative to the official SCJ publication universe.

These are substantive product risks, not implementation details.

## 15. First vertical slice Definition of Done

The first real JurisNexo vertical slice is complete only when one selected Supreme Court compilation can travel through the complete path:

```text
immutable source artifact
    -> reproducible acquisition record
    -> page-preserving extraction
    -> decision segmentation
    -> canonical cases
    -> searchable passages
    -> lexical + semantic retrieval baseline
    -> benchmark legal question
    -> relevant case retrieval
    -> bounded case analysis
    -> evidence verification against source page
    -> auditable research report
```

Additionally:

- rerunning ingestion does not create duplicate logical records;
- duplicate source files are identified;
- at least a manually reviewed sample of segmented decisions is correct;
- retrieval metrics are recorded;
- all report evidence resolves to original source pages;
- known limitations are surfaced rather than hidden.

Only after this Definition of Done should corpus volume become a primary implementation goal.

## 16. Governing principle

The source collection gives JurisNexo a meaningful head start, but it is raw material rather than finished product infrastructure.

The immediate objective is not:

> ingest as many PDFs as possible.

It is:

> prove that JurisNexo can transform real Dominican judicial source material into trustworthy, reproducible, searchable legal evidence and use that evidence to answer a narrow research question correctly.

Once that is reliable, adding the remaining source collection becomes an incremental corpus operation rather than an architectural experiment.
