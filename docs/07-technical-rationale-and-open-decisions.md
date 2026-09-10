# JurisNexo — Technical Rationale and Open Decisions

## 1. Why this document exists

JurisNexo is intentionally borrowing ideas from multiple research lines instead of adopting one named RAG framework as the product architecture.

This document records the rationale so future implementation work does not accidentally collapse the design into a conventional vector-database chatbot.

## 2. Retrieval is necessary but insufficient

Traditional RAG typically performs:

```text
query -> embedding -> nearest chunks -> LLM answer
```

That is useful for locating semantically similar text, but legal precedent research requires additional questions:

- Is the case legally analogous, not merely linguistically similar?
- Which facts were material?
- What did the court actually hold?
- Is the cited statement a party argument or the court's reasoning?
- Was the authority later limited, distinguished, or displaced?
- Is there higher-authority contrary jurisprudence?
- Which cases support the opposite position?

Therefore JurisNexo treats vector retrieval as one candidate-generation channel.

## 3. Research lines influencing JurisNexo

### Hybrid information retrieval

Use exact matching, metadata, lexical retrieval, semantic retrieval, rank fusion, and later reranking.

Reason:

Legal citations and terms of art often benefit from exact/lexical search, while factual similarity benefits from semantic retrieval.

### Legal Elements / factor-based retrieval

Represent cases through legally meaningful issues, facts, elements, and outcomes rather than only document embeddings.

Reason:

Two cases may be semantically similar but legally different because of one material fact.

MVP implication:

Do not require a complete legal-element ontology initially. Preserve a data model that allows issues, holdings, material facts, and normalized factors to be added progressively.

### HYPO/CATO-style case-based reasoning

Compare precedent through common and distinguishing factors.

Reason:

The value of precedent often depends on why two fact patterns are materially alike or different.

MVP implication:

Subagent outputs should capture material facts and distinctions even before a formal factor engine exists.

### KELLER / LegalSearchLM-style query decomposition

Convert a long factual query into multiple legally meaningful subqueries before retrieval.

Reason:

A single embedding of an entire user narrative can obscure the issues that matter.

MVP implication:

The root research agent should decompose research questions and run multiple searches.

### CaseGNN / structural case representation

Treat a judgment as structure: facts, issues, reasoning, holdings, outcome, citations.

Reason:

A decision is not merely a long string.

MVP implication:

Store page structure and permit later case-structure enrichment. Do not require graph neural networks initially.

### CaseLink / citation graph learning

Use the network between cases as retrieval/ranking evidence.

Reason:

Judicial decisions naturally reference earlier authorities.

MVP implication:

Explicit citation extraction and `citing`/`cited-by` traversal are first-class MVP capabilities.

### GraphRAG / LegalGraphRAG

Use graph relationships and hierarchical representations for corpus-wide research and evidence-aware synthesis.

Reason:

Some questions concern jurisprudential lines and relationships across many decisions rather than one nearest passage.

MVP implication:

Do not deploy a full GraphRAG pipeline initially. Build the underlying citation/provenance contracts first so graph approaches can be benchmarked later.

### RAPTOR / hierarchical long-document retrieval

Represent large documents at multiple levels of abstraction.

Reason:

Long judgments may require both local passages and whole-decision context.

MVP implication:

Preserve section/page structure and add hierarchical summaries only if within-case retrieval becomes a measured bottleneck.

### Recursive Language Models (RLM)

Allow a root model to manipulate external context programmatically and delegate bounded analysis to recursive/sub-model calls.

Reason:

Deep research may require navigating much more information than fits into one model context.

MVP implication:

Adopt the pattern, not necessarily the literal framework:

- root research agent;
- external persistent corpus;
- sandboxed Python;
- subagent delegation;
- iterative investigation.

JurisNexo should not repeatedly load the entire corpus into a Python variable when indexed storage and APIs can prune candidates more efficiently.

### DocETL

Use model-assisted document-processing pipelines for exhaustive transformation of unstructured documents into structured data.

Reason:

Ingestion and normalization are different problems from interactive research.

MVP implication:

Evaluate DocETL-style approaches for corpus preprocessing only if simple deterministic + model extraction pipelines become difficult to maintain or insufficiently complete.

### LOTUS

Combine relational/dataframe operations with semantic operators such as semantic filter, join, top-k, and aggregation.

Reason:

A normalized corpus enables cheap deterministic operations before expensive semantic reasoning.

MVP implication:

The root research runtime may adopt LOTUS-like semantic-data operations or use LOTUS directly if benchmarking shows a practical advantage.

## 4. Target architectural synthesis

The target pattern is:

```text
normalized persistent corpus
        |
        +-- SQL / metadata
        +-- lexical index
        +-- semantic index
        +-- citation relationships
        +-- primary-source pages
        |
        v
stable retrieval APIs
        |
        v
root research agent
        |
        +-- bounded subagents
        +-- sandboxed Python
        +-- evidence workspace
        |
        v
auditor
        |
        v
verified research report
        |
        v
optionally persist reusable verified public knowledge
```

This is closer to a legal research operating system than a single RAG algorithm.

## 5. Why normalize before agentic analysis

Normalization should move repeatable work out of expensive per-query reasoning.

Example:

Instead of asking the root model to inspect 100,000 texts to discover dates, chambers, or explicit citations on every research job, compute/store those once and expose indexed filters.

Desired funnel:

```text
large corpus
   -> cheap deterministic filters/search
   -> candidate pool
   -> semantic reranking
   -> bounded subagent reading
   -> deep verification
```

Agent intelligence is most valuable in deciding what question to ask next, not in reimplementing a database engine.

## 6. Persistent learning without unsafe self-modification

Research jobs may discover reusable public knowledge such as:

- resolved citation links;
- likely holding boundaries;
- recurring legal issues;
- candidate `FOLLOWS` or `DISTINGUISHES` relationships.

Do not immediately promote all model discoveries to truth.

Use states such as:

```text
candidate -> verified -> reusable
```

Every interpretive artifact must retain provenance and model/version information.

This allows the corpus to improve over time without turning previous model errors into hidden ground truth.

## 7. Open product decisions

These should remain open until pilot evidence exists.

### Initial legal domain

Options:

- civil/procedural;
- constitutional;
- labor;
- criminal;
- mixed SCJ/TC corpus.

Decision criterion: availability/quality of sources plus frequency and economic value of the research problem.

### Free-demo quota

Unknown until per-job cost is measured.

Need:

- standard-research cost;
- deep-research cost;
- expected abuse rate;
- conversion hypothesis.

### Pricing model

Possible:

- subscription;
- research credits;
- per-report payment;
- team workspace;
- usage + integration fee.

Do not commit before observing real usage.

### LLM provider/model

The architecture should permit different root, subagent, extraction, and verification models.

Select models through benchmark quality/cost, not preference.

### Embedding/reranking stack

Start with a simple baseline.

Candidates for later testing include:

- multilingual dense embeddings;
- BGE-M3-style hybrid representations;
- ColBERT/multi-vector retrieval;
- SPLADE;
- cross-encoder reranking;
- domain-fine-tuned retrievers.

### OCR/document parser

Must be benchmarked on actual Dominican judicial PDFs, especially scans.

Do not select based solely on generic document benchmarks.

### Dedicated graph database

Default answer for MVP: no.

Revisit if:

- multi-hop citation queries become operationally difficult in PostgreSQL;
- proposition graph becomes core product functionality;
- graph algorithms become frequent enough to justify separate infrastructure.

### Dedicated JurisNexo domain/company

Default answer for MVP: no.

Validate under QuisqueyaTech first. Revisit when independent demand, repeat usage, and willingness to pay justify separation.

## 8. Open technical experiments

The MVP should create repeatable tests for:

1. lexical-only retrieval;
2. vector-only retrieval;
3. hybrid retrieval;
4. hybrid + reranker;
5. one-shot RAG versus iterative research agent;
6. agent without Python versus agent + Python;
7. fixed case analysis versus parallel subagents;
8. basic retrieval versus citation expansion;
9. supporting-only search versus mandatory adverse search;
10. shallow normalization versus deep legal-element enrichment.

Only adopt added complexity when it improves meaningful metrics.

## 9. Anti-goals

Avoid architecture driven by names of papers or frameworks.

Do not say:

> "We use GraphRAG, therefore retrieval is solved."

or:

> "We use RLM, therefore long-context research is solved."

or:

> "We indexed 200,000 cases, therefore the corpus is useful."

Each technique must earn its place through measured improvement in retrieval completeness, legal accuracy, cost, latency, or professional time saved.

## 10. Governing principle

Outcomes matter.

The winning JurisNexo architecture is the simplest one that reliably helps lawyers find the material authority they would otherwise spend substantial time locating and verifying.
