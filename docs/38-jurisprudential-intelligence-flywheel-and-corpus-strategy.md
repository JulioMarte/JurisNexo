# JurisNexo — Jurisprudential Intelligence Flywheel and Corpus Strategy

## Status

This document is the canonical product/data strategy for turning the Dominican public judicial corpus into a defensible JurisNexo asset.

It refines the MVP corpus and sequencing described in `00-product-vision-and-mvp.md`, `06-mvp-roadmap.md`, `08-source-acquisition-coverage-and-canonical-identity.md`, and `16-pilot-corpus-and-first-mvp-validation-slice.md`.

It does **not** replace the legal-reality model. Persisted legal semantics remain governed by the current legal-model chain ending at `35-legal-reality-v4.md`.

When an older document says that the MVP should remain a narrowly bounded SCJ/TC corpus until deep normalization is complete, interpret that language through this document:

> JurisNexo should pursue **broad, cheap, provenance-preserving discoverability** and **narrow, selective, evidence-backed semantic depth** at the same time.

Breadth must not require deep interpretation. Deep interpretation must not be applied indiscriminately to the whole corpus.

---

## 1. Strategic thesis

JurisNexo should not try to win by being another legal chatbot, another vector search interface, or by claiming the largest Dominican case-law collection.

The durable asset to build is:

> **a verified Dominican jurisprudential intelligence graph: canonical judicial identities connected to primary-source evidence, citations, legal issues, propositions, procedural history, and contextual judicial treatment.**

"Graph" describes the legal relationships. It does not prescribe Neo4j, RDF, GraphRAG, or another graph database. PostgreSQL remains the system of record.

The first user-facing product remains the **Precedent & Adverse Authority Report**. The report is the product surface; the jurisprudential intelligence graph is the compounding asset underneath it.

The target flywheel is:

```text
official sources
    -> discover/acquire cheaply
    -> canonical judicial identity
    -> searchable text + provenance
    -> citation extraction/resolution
    -> priority signals
    -> selective deep normalization
    -> legal issues/propositions/treatments
    -> verified evidence
    -> research agent
    -> lawyer use/corrections
    -> benchmark + priority signals
    -> better corpus intelligence
```

A unit of work should become reusable corpus intelligence whenever it is safe and evidence-backed, rather than disappearing after one LLM answer.

---

## 2. Why SCJ Principales is the seed set

The official Poder Judicial page exposes **Principales Sentencias/Decisiones** for the Suprema Corte de Justicia from 2005 through the current publication period. Current official page:

- https://poderjudicial.gob.do/suprema-corte-de-justicia/secretaria-general/principales-sentencias/

JurisNexo treats membership in this official collection as an **editorial importance signal from the source**, not as a legal-authority status.

The following inference is allowed:

```text
case appears in official SCJ Principales collection
    -> high-priority candidate for deep analysis
```

The following inferences are forbidden:

```text
case appears in Principales
    -> binding precedent
    -> legally superior to an otherwise comparable SCJ decision
    -> automatically controlling authority
```

Legal authority still depends on court/organ, legal issue, procedural posture, date, later treatment, factual/legal fit, and applicable Dominican law.

### Why this collection has unusually high leverage

The SCJ has already spent editorial effort selecting these decisions. That means JurisNexo can start its expensive semantic work on a collection with much higher expected jurisprudential signal than a random sample of the full corpus.

For each Principal decision, the system can extract:

- canonical decision identity;
- exact artifact/page provenance;
- decision structure;
- explicit case citations;
- legal references;
- legal issues;
- propositions/holdings;
- material facts where useful;
- disposition;
- candidate treatment of cited authorities.

Its citations then identify older potentially foundational decisions. Forward citations identify later treatment. User retrievals and lawyer corrections provide additional promotion signals.

This is the initial compounding loop.

---

## 3. Historical coverage: measure, never assume

Official Poder Judicial surfaces currently make different coverage claims:

- the consolidated SCJ consultation describes SCJ decisions from 1910 to the present;
- the historical bulletin project states that 1910–1993 bulletins were digitized;
- the "Consultas Diversas" service describes the web Boletín Judicial collection as available from 1994;
- the transparency bulletin surface exposes year selectors extending back to 1910.

Relevant official sources:

- https://transparencia.poderjudicial.gob.do/consultasSCJ/megaconsulta
- https://poderjudicial.gob.do/suprema-corte-de-justicia/secretaria-general/consultas-diversas/
- https://transparencia.poderjudicial.gob.do/transparencia/boletines
- https://transparencia.poderjudicial.gob.do/consultasSCJ/noticia?IdNoticia=1017

These source claims are **discovery evidence, not proof of complete machine-acquirable coverage**.

JurisNexo must therefore not hard-code or market any of the following without a measured inventory:

```text
"we cover every SCJ decision since 1910"
"our SCJ corpus is complete from 1994"
"all historical bulletins are downloadable and ingestible"
```

Instead maintain a coverage manifest that distinguishes:

```text
source claims
discovered records
downloadable artifacts
acquired artifacts
segmented decisions
canonical decisions
searchable decisions
deeply normalized decisions
known gaps
last reconciliation
```

Coverage is an observed property of the corpus, not a slogan.

---

## 4. Two-speed corpus strategy

### 4.1 Horizontal source corpus — breadth cheaply

Goal: make as much trustworthy official material discoverable/searchable as practical while preserving source provenance.

Minimum useful normalization:

- source registry and source collection;
- source document identity;
- artifact bytes/checksum/version;
- court/organ where reliably available;
- decision number/date/expediente observations;
- canonical decision identity or explicit unresolved state;
- page-preserved text/OCR;
- full-text index;
- optional embeddings after text quality is acceptable;
- citation strings when cheaply extractable.

Do **not** require issues, holdings, material facts, treatment, argument graphs, or other expensive semantic analysis for every decision before it becomes searchable.

### 4.2 Intelligence corpus — depth selectively

Deep normalization is reserved for high-value decisions.

Initial priority sources/signals:

1. membership in official SCJ `principales-sentencias`;
2. member of the manually reviewed Golden Precedent Set;
3. cited by one or more Principal decisions;
4. high inbound citation count after identity resolution;
5. important forward-citing decision for an already important authority;
6. repeatedly retrieved in real lawyer research;
7. surfaced during adverse-authority investigation;
8. explicitly marked critical by a legal reviewer;
9. unresolved authority that blocks an important treatment chain.

Deep normalization may include:

- legal issues;
- legal propositions/holdings;
- factual propositions and material-fact relations;
- structured disposition;
- procedural history;
- citation context;
- contextual judicial treatment;
- relation evidence;
- human/model verification state.

The intelligence corpus grows from observed value, not from a requirement to semantically annotate everything.

---

## 5. Promotion is an operational policy, not legal authority

JurisNexo may calculate a `normalization_priority` or equivalent scheduler score.

Illustrative inputs:

```text
official principal selection
benchmark membership
citation centrality
cited by a Principal
forward-citation relevance
real-user retrieval frequency
adverse-authority relevance
human reviewer priority
unresolved reference blocking a research path
```

This score controls **where JurisNexo spends compute/review effort**.

It must never be reused as:

- a precedential-weight score;
- a prediction of case outcome;
- a statement that one decision is legally "better";
- an automatic answer to a lawyer's research question.

Scheduling importance and legal authority are distinct concepts.

---

## 6. Citation-first expansion

After reliable decision segmentation and canonical identity, citation extraction/resolution is the highest-leverage next corpus capability.

### Stage A — preserve the raw citation

An observed citation should retain:

- source case/document;
- raw citation text;
- exact source page;
- exact excerpt/context where useful;
- extraction/assertion method;
- confidence;
- resolution state.

Never discard the raw reference after resolution.

### Stage B — resolve conservatively

Candidate signals may include:

- court;
- organ;
- normalized decision number;
- decision date;
- bulletin number;
- docket/expediente;
- parties/title;
- textual fingerprint;
- source metadata.

High-confidence deterministic matches may resolve automatically according to an accepted policy. Ambiguous matches remain unresolved.

### Stage C — create the cheap graph

The first useful relationship is simply:

```text
decision A --cites--> decision B
```

This can be valuable without knowing whether A follows, distinguishes, limits, or merely mentions B.

### Stage D — classify treatment only when valuable

Substantive treatment is more expensive and semantically risky. Analyze it selectively for important citation edges.

Examples:

```text
A --applies(issue X)--> B
A --follows(issue X)--> B
A --distinguishes(issue Y)--> B
A --limits(issue Y)--> B
A --declines_to_apply(issue Z)--> B
```

Every substantive treatment must follow the current V4 legal model: contextual legal issue, relevant source/target propositions when available, evidence, assertion method, verification state, and bitemporal knowledge semantics where applicable.

---

## 7. Backward and forward traversal

A Principal decision creates two useful expansion directions.

### Backward

```text
Principal decision
    -> authorities it cites
    -> resolve canonical identities
    -> promote important older nodes
```

This is particularly useful for older historical decisions: JurisNexo does not need to deeply normalize decades of historical material before knowing which authorities modern important decisions continue to rely on.

### Forward

```text
important authority
    -> later decisions citing it
    -> identify treatment candidates
    -> find later limits/distinctions/conflicts
```

Together:

```text
Principal seed
    -> foundational authorities
    -> later citing decisions
    -> treatment chain
    -> jurisprudential evolution
```

This is the core mechanism for eventually answering:

> What has happened to this legal proposition since the decision was issued?

---

## 8. Canonical identity is part of the moat

The same judicial decision may occur in:

- an individual PDF;
- a judicial bulletin;
- a Principales compilation;
- a historical compilation;
- multiple URLs;
- a corrected/reissued artifact;
- another decision's raw citation.

JurisNexo must converge these observations conservatively onto one canonical judicial identity when evidence supports it.

Do not add `cases.is_principal` or equivalent intrinsic boolean.

"Principal" is source/editorial provenance, not intrinsic case identity. It should be derivable from the case's official source membership/occurrences. A convenience read model/view may later expose this efficiently without creating a second writable truth.

Likewise, a source-provided classification tag may be added as a denormalized index, but the source collection/observation remains the evidence for the editorial selection.

---

## 9. Existing schema fit

The current PostgreSQL model is sufficient to begin this flywheel without a new foundational migration.

Existing structures already cover the required distinctions, including:

- `source_registries`;
- `source_collections`;
- `source_documents`;
- `source_document_observations`;
- `source_document_artifacts`;
- `source_artifacts`;
- `artifact_pages`;
- `case_artifact_occurrences`;
- canonical judicial decisions/cases;
- `legal_documents` and document occurrences;
- legal relations/observations/evidence;
- legal proceedings and procedural relations;
- V4 `legal_issues`;
- V4 factual propositions;
- legal propositions;
- contextual treatment assertions;
- bitemporal assertion/history structures;
- extensible legal concepts.

The immediate work is therefore primarily:

```text
acquisition policy
+ source inventory
+ ingestion
+ citation extraction/resolution
+ priority scheduling
+ benchmarks
+ selective semantic analysis
```

not another broad schema redesign.

### Schema changes require demonstrated pressure

Do not add a new table merely because this strategy names a useful concept.

Examples deliberately deferred:

- generic `editorial_selections` table;
- persisted normalization-priority table;
- universal graph nodes/edges;
- graph database migration;
- case-level `is_principal` flag.

Use existing source collection membership and `latest_source_metadata` until real source behavior shows that a more structured editorial-assertion model is needed.

If a future source has multiple overlapping editorial selections with explicit rationale/effective dates that cannot be represented cleanly, then propose a source-editorial-assertion entity with evidence. That decision must be driven by observed source requirements.

---

## 10. Initial source sequence

### Track A — high-signal depth

Start with:

```text
SCJ Principales 2005-present
```

Inventory the collection completely before making completeness claims.

For every publication:

- preserve discovery URL;
- acquire immutable bytes;
- hash;
- identify publication/layout family;
- segment individual decisions;
- resolve canonical identities;
- capture source-collection membership;
- extract citations;
- run accepted structure/extraction audits.

Then progressively normalize the decisions deeply.

### Track B — SCJ breadth

In parallel, build the broad SCJ inventory from official decision/bulletin/historical surfaces.

The purpose is initially:

- canonical resolution;
- forward/backward citation traversal;
- lexical/semantic candidate discovery;
- adverse-authority search;
- measurable coverage.

Do not block searchability on expensive legal-semantic enrichment.

### Track C — multi-court expansion

The architecture remains multi-court.

After SCJ source acquisition/reconciliation is mechanically trustworthy, add official TC, TSA, appellate, first-instance, labor, criminal, land/inmoviliaria, and other sources according to:

```text
professional value
x source availability
x acquisition reliability
x provenance quality
x expected integration cost
```

Do not introduce SCJ-specific assumptions into stable Corpus API/domain contracts.

The strategy starts with SCJ because the source topology provides a strong seed and historical/citation spine, not because the data model or product is SCJ-only.

---

## 11. Golden Precedent Set

Create a small, legally reviewed benchmark from high-signal Dominican decisions before trying to annotate a huge corpus.

Initial target: approximately 40–100 decisions across materially different SCJ organs/matters and years, then extend to other courts.

For each gold decision annotate only what is necessary to test current capabilities, such as:

- canonical identity;
- exact source occurrence/pages;
- important legal issues;
- material holdings/propositions;
- important factual distinctions;
- explicit citations;
- citation resolutions;
- known materially important citing decisions;
- treatment when legally reviewable;
- dispositive outcome;
- supporting evidence spans.

This one set should be reusable across:

- segmentation evaluation;
- metadata extraction;
- citation extraction;
- citation resolution;
- issue/proposition extraction;
- treatment classification;
- retrieval;
- case analysis;
- research-agent evaluation.

Do not leak gold annotations into runtime prompts or retrieval indexes used by the evaluated system.

---

## 12. Failure corpus as a compounding asset

Every material real-world failure should be classified.

Examples:

- missing critical authority;
- missing adverse authority;
- wrong canonical merge;
- duplicate case identity;
- unresolved citation that should resolve;
- false citation resolution;
- incorrect issue;
- party argument mislabeled as holding;
- incorrect treatment;
- wrong court/organ;
- broken page provenance;
- stale coverage assumption.

High-value failures should become durable regression evidence.

The desired loop is:

```text
lawyer/reviewer finds failure
    -> evidence-backed correction
    -> benchmark/regression case
    -> fix
    -> exact-head test/benchmark
    -> failure cannot silently return
```

A growing Dominican failure corpus is more defensible than any particular model provider.

---

## 13. Coverage and freshness are product features

Every research report should eventually be able to describe the corpus boundary it actually searched.

Example shape:

```text
SCJ / collection X / period Y
discovered: ...
acquired: ...
searchable: ...
citation-linked: ...
deeply normalized: ...
known gaps: ...
last reconciled: ...
```

The report must never transform "no contrary authority found" into "no contrary authority exists."

Preferred language is equivalent to:

> No materially contrary authority was found within the searched corpus and disclosed coverage.

Coverage state should come from deterministic source inventory/reconciliation, not model confidence.

---

## 14. Product moat hierarchy

JurisNexo should invest in assets approximately in this order:

1. primary-source provenance and immutable artifacts;
2. conservative canonical judicial identity;
3. measurable source inventory/coverage/freshness;
4. citation extraction and resolution;
5. Golden Precedent Set + failure corpus;
6. selective issues/propositions/facts/dispositions;
7. contextual treatment graph;
8. research-agent workflows using those assets;
9. jurisprudential analytics after coverage is adequate;
10. litigation analytics only when sample completeness supports responsible statistics.

Things that are **not** durable moat by themselves:

- a particular frontier LLM;
- prompt wording;
- generic chat;
- embeddings;
- vector search;
- raw PDF count;
- one report-generation template;
- a graph database product;
- a proprietary model trained before there is evidence it beats simpler approaches.

---

## 15. What not to build now

Do not make the following current priorities unless a benchmark/observed failure justifies them:

- full semantic normalization of the entire historical corpus;
- Neo4j/RDF/OWL migration;
- custom legal foundation model;
- GNN/CaseLink reproduction;
- full GraphRAG infrastructure;
- RAPTOR over every case;
- generic semantic SQL/LOTUS layer;
- judge/lawyer outcome analytics without measured coverage;
- practice-management/CRM features;
- broad document-generation feature parity with general legal-AI competitors.

The highest-value near-term path is a boring-looking but compounding data pipeline.

---

## 16. Near-term execution order

The next coherent implementation sequence is:

1. inventory the official SCJ Principales collection from 2005 to the present;
2. reconcile that inventory against already stored artifacts;
3. acquire missing Principales artifacts idempotently;
4. prove segmentation/canonical identity across representative publication families;
5. make all accepted Principal decisions searchable with exact provenance;
6. extract raw explicit citations and citation contexts;
7. build conservative citation resolution;
8. create a Golden Precedent Set from selected Principal decisions;
9. inventory/acquire broad SCJ material cheaply for resolution and search;
10. use Principal citations, forward citations, benchmark membership, and real research to drive promotion;
11. run selective issue/proposition/treatment extraction behind independent audit;
12. expose citation/later-treatment traversal through stable Corpus API capabilities;
13. build the Precedent & Adverse Authority research flow on top;
14. record every material pilot failure as benchmark/regression evidence;
15. expand sources/courts according to measured value and source quality.

Do not start a new architecture redesign merely because some steps are difficult. Prefer proving the current model against real SCJ data first.

---

## 17. Agent discovery rule

Any coding/research agent working on corpus acquisition, ingestion, retrieval, research, citation processing, or legal-model enrichment must discover this strategy before proposing broad work.

At minimum read:

1. `AGENTS.md`;
2. `19-documentation-crosswalk.md`;
3. this document;
4. the domain-specific canonical document for the task;
5. current implementation/tests before claiming a gap.

When proposing a feature, the agent should answer:

```text
Does this increase trustworthy breadth?
Does this improve canonical identity?
Does this create/reuse citation intelligence?
Does this improve selective semantic depth?
Does this strengthen benchmark/regression evidence?
Does this directly improve the lawyer research workflow?
```

If the answer to all is no, the feature is probably not on the current critical path.

---

## 18. Definition of strategic success

This strategy is working when JurisNexo can take an important Dominican decision and reliably show:

- where the source came from;
- every canonical representation/occurrence we know;
- what authorities it explicitly cites;
- which citations are resolved versus unresolved;
- which later decisions cite it within measured coverage;
- what legal issues/propositions matter;
- how important later courts treated those propositions where verified;
- the exact primary-source evidence for every material assertion;
- the disclosed coverage limitations.

The research agent should then use this accumulated intelligence to reduce the amount of work a lawyer must redo manually.

That — not the number of indexed PDFs or sophistication of generated prose — is the compounding asset JurisNexo is trying to build.
