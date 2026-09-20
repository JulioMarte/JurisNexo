# JurisNexo — Pilot Corpus and First MVP Validation Slice

## 1. Purpose

JurisNexo already has useful Supreme Court source material available in the Supabase project used for the product. This materially changes the first implementation milestone: the MVP does not need to begin with an abstract sample corpus. It can prove the complete ingestion and retrieval path against real Dominican Supreme Court material that is already available.

This document defines the **deep-validation pilot**, what it is allowed to prove, what it does not prove, and how it coexists with broader source discovery/acquisition.

The canonical corpus strategy is defined in `38-jurisprudential-intelligence-flywheel-and-corpus-strategy.md`:

```text
broad, cheap, provenance-preserving discoverability
        +
selective, evidence-backed semantic depth
```

The pilot is deliberately narrow because validation needs a controlled fixture. That does **not** mean the broader corpus must remain undiscovered, unacquired or unsearchable until the pilot is complete.

## 2. Current available source material

As of the initial inventory, Supabase Storage contained approximately:

- 34 PDF files under the Supreme Court collection;
- approximately 243.84 MB of source PDFs;
- compilations spanning approximately 2005 through 2025;
- recent compilations for 2022, 2023, 2024, and early 2025;
- older annual or volume-based compilations for multiple prior years.

These files are source artifacts, not yet by themselves a trustworthy normalized legal corpus, and this historical inventory is not a claim about the complete official SCJ publication universe.

The broader acquisition system should reconcile official source surfaces independently of this pilot inventory and measure discovered, downloadable, acquired, searchable, unresolved and missing material.

## 3. First canonical deep-validation artifact

The first deep-ingestion fixture remains:

```text
Suprema Corte PDF/Principales_Decisiones_enero_abril_2025.pdf
```

It should be treated as an immutable source artifact and retained byte-for-byte.

It is intentionally a compilation rather than assuming one PDF equals one judicial decision.

### Critical invariant

```text
physical PDF artifact != canonical judicial case
```

A source PDF may contain multiple judicial decisions. One judicial decision may later be observed through multiple physical artifacts, mirrors, editions, filenames, collections or raw citations.

The data model and ingestion implementation must preserve this distinction from the first production-quality test.

## 4. Expected deep-ingestion transformation

The first vertical ingestion path should prove:

```text
source artifact
        -> register immutable artifact
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
        -> build search representations
        -> quality/audit gates
        -> searchable corpus generation
```

No stage is allowed to destroy the ability to trace normalized text back to the original artifact and page.

This full audited path is not required before every broader source artifact can be discovered or acquired. Cheap breadth may stop at the strongest trustworthy state available and record unresolved work explicitly.

## 5. Decision-boundary detection is a first-class deep-ingestion problem

The first source is a compilation. Therefore the deep-ingestion pipeline must not simply chunk the complete PDF as one document and call it a case.

The pipeline must attempt to identify individual judicial decisions and their page spans.

Candidate signals may include court/chamber headings, decision identifiers, dates, expediente identifiers, parties, formal opening patterns, dispositive sections, table-of-contents information, layout and page transitions.

Boundary detection may use deterministic parsing, model-assisted extraction, or both, but its result must be persisted with provenance and confidence.

When a boundary is uncertain, the system must mark it for review rather than fabricate precision.

## 6. Canonical identity versus artifact identity

For every candidate decision, JurisNexo should attempt to produce a stable canonical identity using available fields such as court, chamber/sala, decision number, expediente/docket number, decision date, parties/title and source-specific identifiers.

The physical artifact remains separately identifiable by checksum and source/storage locator.

This permits:

```text
canonical case
    -> artifact A pages 100-118
    -> artifact B pages 45-63
```

without falsely creating two independent cases.

Canonical identity is useful to both tracks: the deep pilot tests it rigorously, while broader source/citation observations provide additional evidence for resolving identities over time.

## 7. Real duplicate evidence already exists

The initial Storage inventory contained duplicate-content files under different filenames. This means deduplication is not merely a theoretical concern.

The ingestion pipeline must calculate its own cryptographic content hash and must not rely solely on filenames or storage-provider metadata.

If two artifacts contain exactly the same bytes:

- retain distinct observed source/storage identities when useful for provenance;
- identify the duplicate-content relationship;
- avoid unnecessary repeated processing;
- never create duplicate canonical judicial decisions merely because filenames differ.

Provider ETags may be retained as acquisition metadata, but JurisNexo's own content hash is authoritative for exact-byte deduplication.

## 8. Pilot depth and corpus breadth are separate axes

The old interpretation of corpus expansion as one serial sequence is retired.

### Track A — deep-validation / intelligence seed

Start by proving the early-2025 Principales compilation end to end. Then deepen additional SCJ Principales material and high-signal decisions according to the promotion policy in document 38.

Early 2024/2023 compilations remain useful adjacent fixtures because they exercise additional layouts, years and retrieval questions.

Deep work includes expensive or semantically risky operations such as:

- robust segmentation/auditing;
- legal issues and propositions;
- material factual structure;
- contextual treatment;
- human/model verification;
- high-confidence evidence construction.

### Track B — broad official-source corpus

In parallel, JurisNexo may discover, acquire and make broader SCJ material cheaply searchable as source reliability permits.

Breadth work is useful for:

- coverage measurement;
- canonical identity resolution;
- exact/reference retrieval;
- adverse-authority search;
- backward/forward citation traversal;
- identifying candidates worth deep normalization.

Broad material must preserve provenance and uncertainty, but it does not need complete semantic enrichment before it becomes useful.

### Important distinction

```text
narrow pilot != narrow total corpus
broad acquisition != deep legal understanding
```

The system should do both jobs without conflating them.

## 9. Two independent MVP proofs

### 9.1 Deep-ingestion proof

Question:

> Can JurisNexo reliably transform a real Supreme Court compilation into canonical, page-traceable, searchable judicial decisions?

Success requires evidence that artifacts are immutable and hashed, pages are preserved, decisions are not conflated, metadata is acceptably extracted, uncertainty is explicit, repeat ingestion is idempotent, duplicates do not become duplicate cases, and normalized text remains traceable to source pages.

### 9.2 Product/retrieval proof

Question:

> Given a real legal research question and the corpus actually available to the run, can JurisNexo find material decisions, including adverse authority, and provide auditable evidence while disclosing material corpus limitations?

Success requires:

- a manually reviewed seed benchmark;
- known relevant cases where possible;
- Recall@K and nDCG measurements;
- Critical Miss Rate measurement;
- adverse-authority recall where applicable;
- exact evidence-page verification;
- documented retrieval configuration and corpus generation;
- explicit searched-corpus/coverage boundaries.

Successful parsing or embedding generation alone is not MVP success.

## 10. Initial benchmark creation

Once the first deeply processed decisions have been manually inspected, create an initial diagnostic benchmark of approximately 10–20 legal questions grounded in material whose relevance can actually be reviewed.

Questions should vary across exact-reference lookup, doctrinal search, fact-pattern similarity, supporting authority, adverse/limiting authority, citation-chain discovery and date/chamber constraints.

The benchmark must not be generated entirely by the same model that will be evaluated without human review. A legal reviewer should establish or validate relevant authorities and material evidence.

This diagnostic set can later grow into the Golden Precedent Set described in document 38.

## 11. Retrieval experiments enabled by the pilot

Use frozen/versioned corpus generations to compare at least:

```text
lexical only
semantic only
lexical + semantic + RRF
lexical + semantic + RRF + reranker
```

Additional experiments may compare passage-level versus case-level representations, embeddings, candidate limits, passaging strategies, query decomposition and citation expansion.

Every experiment must use versioned retrieval profiles so results can be reproduced.

## 12. Storage policy

Existing source storage can serve as acquisition input, but product storage must preserve data-class boundaries.

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

Public jurisprudential sources and private tenant documents must never share an access policy merely for convenience.

## 13. What is already ready

The project has already removed several bootstrap uncertainties:

- a functioning Supabase project exists;
- PostgreSQL and Storage are available;
- a nontrivial SCJ seed collection exists;
- recent and historical source material is available;
- real duplicate-content cases exist for exercising deduplication;
- product, architecture, tenancy, research, evidence, benchmark, stack, CI, Docker, deployment and corpus-strategy contracts are documented.

This materially reduces startup friction.

## 14. What is not yet ready

The existence of source files must not be confused with having a trustworthy legal corpus.

The following remain empirical risks until implemented and measured:

- text/OCR quality across source families;
- page-number fidelity;
- decision-boundary detection;
- canonical identity accuracy;
- citation extraction/resolution accuracy;
- chunk/passaging quality;
- embedding/retrieval quality for Dominican Spanish jurisprudence;
- adverse-authority retrieval;
- research-agent correctness;
- report claim/evidence verification;
- actual coverage relative to official publication surfaces.

These are substantive product risks, not implementation details.

## 15. First vertical slice Definition of Done

The first deep JurisNexo vertical slice is complete only when one selected Supreme Court compilation can travel through:

```text
immutable source artifact
    -> reproducible acquisition record
    -> page-preserving extraction
    -> decision segmentation
    -> canonical cases
    -> searchable passages
    -> retrieval baseline
    -> benchmark legal question
    -> relevant case retrieval
    -> bounded case analysis
    -> evidence verification against source page
    -> auditable research report
```

Additionally, rerunning ingestion must not create duplicate logical records; duplicate source files are identified; a manually reviewed segmentation sample is correct; retrieval metrics are recorded; report evidence resolves to original pages; and known limitations are surfaced.

This Definition of Done gates confidence in **deep processing**. It does not prohibit parallel broad source inventory, acquisition or cheap searchability.

## 16. Governing principle

The source collection gives JurisNexo a meaningful head start, but it is raw material rather than finished intelligence.

The immediate deep-validation objective is:

> prove that JurisNexo can transform real Dominican judicial source material into trustworthy, reproducible, searchable legal evidence and use that evidence correctly.

At the same time, broader official material can be inventoried, acquired and made searchable cheaply enough to improve coverage, citation traversal and adverse-authority discovery.

The combined rule is:

> **validate depth narrowly; expand trustworthy breadth cheaply; deepen selectively according to legal/research value.**
