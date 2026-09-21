# JurisNexo — Universal legal document normalization control plane V3 handoff

## Status

**CURRENT IMPLEMENTATION HANDOFF.**

This document is the current implementation handoff for post-acquisition document normalization.

It **supersedes the implementation sequencing and parser-ownership assumptions** in
`40-universal-normalization-control-plane-implementation-plan.md`, while preserving V2's accepted provenance,
quality, benchmark, JEV shadow-mode, visual-verification, resumability, reconciliation and promotion
requirements unless this document explicitly refines them.

Read together:

- `39-document-normalization-and-derived-artifacts.md` — stable persistence/provenance contract;
- this document — current implementation/control-plane contract;
- `40-universal-normalization-control-plane-implementation-plan.md` — historical design provenance and detailed
  quality rationale retained where not superseded.

The central V3 correction is:

> JurisNexo must not build a universal document parser. It must build a **universal legal-document
> normalization control plane** around mature open-source parsing/normalization engines.

SCJ Principales remains the first validation corpus. It is **not** the architectural scope.

---

## 1. Product/architecture objective

The normalization layer must be capable, by design, of accepting heterogeneous official legal
material from different institutions and jurisdictions without requiring a new end-to-end
normalization pipeline per source.

Expected future source classes include, without making this list exhaustive:

- Suprema Corte de Justicia;
- Tribunal Constitucional;
- lower courts and tribunals;
- constitutions;
- statutes and codes;
- regulations;
- administrative resolutions;
- gazettes;
- judicial bulletins;
- opinions/dictámenes;
- compilations containing multiple legal documents;
- born-digital and scanned historical collections.

Expected source formats may include:

- PDF;
- DOCX;
- DOC;
- RTF;
- HTML/XHTML;
- images;
- OpenDocument and other office/document formats when supported by the selected engines;
- future formats introduced through bounded adapters.

The stable architectural target is:

```text
TRUSTED LEGAL SOURCE
        |
        v
ACQUISITION / SOURCE-SPECIFIC DISCOVERY
        |
        v
IMMUTABLE SOURCE ARTIFACT
        |
        v
UNIVERSAL NORMALIZATION CONTROL PLANE
        |
        v
EVIDENCE-FAITHFUL NORMALIZED DOCUMENT
        |
        v
LEGAL-DOCUMENT CLASSIFICATION / EXTRACTION
        |
        +--> judicial decision
        +--> constitution/statute/regulation
        +--> administrative act
        +--> compilation/bulletin
        +--> other legal-document semantics
```

The normalization core must not need to know that a PDF came from the SCJ rather than the TC unless
a source-specific policy is genuinely required.

---

## 2. What JurisNexo owns and what it delegates

### 2.1 Delegate commodity document parsing

JurisNexo should not implement its own general-purpose:

- PDF parser;
- DOCX parser;
- DOC/RTF parser;
- HTML parser;
- generic OCR engine;
- table/layout detector;
- reading-order model.

These are replaceable infrastructure.

### 2.2 JurisNexo owns the control plane

JurisNexo remains responsible for:

- acquisition-manifest verification;
- immutable source identity;
- normalization planning;
- sandboxed worker execution;
- parser/engine routing policy;
- benchmark-based engine selection;
- OCR policy;
- quality policy;
- legal-critical-token risk;
- JEV/text-quality judging policy;
- visual-verification policy;
- correction assertions;
- provenance and derivation lineage;
- resolved evidence-text policy;
- durable run/item state;
- idempotency and resume;
- external-provider/privacy policy;
- cost and drift telemetry;
- reconciliation;
- immutable normalization manifests;
- stable Document Workspace/API exposure;
- promotion gates;
- legal-domain extraction after normalization.

This is the durable JurisNexo value.

---

## 3. Open-source engine strategy

### 3.1 Docling — primary structural normalizer

Use Docling as the initial primary multi-format structural-normalization engine.

Its role is to provide a unified technical document representation including, when available:

- pages;
- text;
- blocks/elements;
- layout;
- reading order;
- tables;
- images;
- OCR integration;
- complete serialized `DoclingDocument` output.

Treat `DoclingDocument` as the primary **technical derivative**, not as JurisNexo's legal model and
not as a permanent relational schema.

Do not mirror Docling internals wholesale into PostgreSQL.

### 3.2 Apache Tika — universal detector/metadata/fallback capability

Use Apache Tika as a complementary capability for broad format detection, metadata inspection and
fallback extraction where that adds measurable value.

Tika must not automatically become a second canonical document model.

Its primary intended roles are:

```text
format/content detection
metadata inspection
unusual/legacy-format fallback
sanity check when format claims are inconsistent
```

### 3.3 OCR engines are plugins/challengers

The architecture must not depend permanently on one OCR backend.

Initial benchmark candidates may include:

- RapidOCR / PP-OCR family;
- Tesseract;
- PaddleOCR/PP-Structure where a benchmarked capability warrants it.

OCRmyPDF may be used selectively for preprocessing/searchable-PDF needs if measured benefit justifies
the extra stage.

### 3.4 Marker and MinerU are challengers, not simultaneous production dependencies

Marker, MinerU or future open-source parsers may be benchmarked against Docling for difficult
documents, especially scans/layout-heavy PDFs.

Do **not** install and operate every challenger in production simply because it exists.

A challenger is promoted only if it solves an observed failure class with enough quality/cost benefit
to justify the operational complexity.

### 3.5 Unstructured is not the canonical technical document model

Unstructured/connectors may be useful for ETL or future connector needs, but JurisNexo acquisition
already owns source discovery/preservation and the current architecture requires stronger forensic
provenance than a generic RAG-ingestion path.

Do not introduce it merely to duplicate existing acquisition or chunking responsibilities.

---

## 4. Core architecture

The preferred architecture is:

```text
CLOSED ACQUISITION MANIFEST
            |
            v
MANIFEST VERIFIER / PLANNER
            |
            v
IMMUTABLE SOURCE ARTIFACT FROM S3
            |
            v
FORMAT INSPECTION
   Tika + byte-signature/source metadata
            |
            v
NORMALIZATION ROUTER
            |
     +------+-------------------------+
     |                                |
 Docling-supported              exceptional format
     |                                |
     v                                v
DOCLING STRUCTURAL             bounded fallback /
NORMALIZATION                  explicit unsupported
     |
     +---- native text when trustworthy
     |
     +---- selective OCR when required
     |
     v
CANDIDATE DOCLINGDOCUMENT
     |
     v
JURISNEXO QUALITY CONTROL PLANE
     |
     +-- deterministic QA
     +-- Docling confidence
     +-- legal-critical-token risk
     +-- JEV TextQualityJudge (shadow first)
     +-- sentinel sampling
     +-- VisualTextVerifier (selective)
     |
     v
VERSIONED OBSERVATIONS / CORRECTIONS
     |
     v
RESOLVED EVIDENCE TEXT VIEW
     |
     v
NORMALIZATION RECONCILIATION
     |
     v
IMMUTABLE NORMALIZATION MANIFEST
     |
     v
DOCUMENT WORKSPACE / SEARCH PROJECTIONS
     |
     v
LATER LEGAL SEMANTIC EXTRACTION
```

---

## 5. Source adapters versus normalization adapters

Maintain a strict distinction.

### Source adapter

Knows how to discover/acquire a particular official source.

Examples:

```text
SCJ source adapter
TC source adapter
legislative source adapter
gazette source adapter
```

It outputs immutable source artifacts and acquisition manifests.

### Normalization adapter/engine

Knows how to convert a document format or artifact class into the common technical representation.

Examples:

```text
PDF -> Docling
DOCX -> Docling
DOC/RTF -> Docling/LibreOffice-supported path
HTML -> Docling/Tika-supported path
image -> OCR/Docling path
```

Do not create:

```text
normalize_scj.py
normalize_tc.py
normalize_constitution.py
normalize_laws.py
```

with duplicated OCR/retry/provenance logic.

A source-specific normalization policy is permitted only when the source demonstrates a real,
measured exception.

---

## 6. Common output contract

The control plane must converge heterogeneous input into a common JurisNexo-facing technical contract.

Conceptually:

```text
NormalizedDocument
  source_artifact_id
  structural_artifact_id
  source_format
  pages/elements
  text observations
  resolved evidence-text view
  quality state/dimensions
  provenance/derivation lineage
  normalization run/config identity
```

This is a conceptual API boundary, not a requirement to create one giant database table.

The complete structural artifact stays in object storage.

The stable consumer-facing API should hide engine internals.

---

## 7. Preserve the V2 epistemic model

Keep four truths distinct:

```text
1. SOURCE
   exact official bytes

2. STRUCTURAL NORMALIZATION
   Docling/Tika-derived technical representation

3. TEXT OBSERVATIONS
   native text / OCR / VLM / human readings

4. RESOLVED TEXT VIEW
   current preferred evidence-faithful reconstruction
```

No parser/model output automatically becomes legal truth.

A visual correction does not silently rewrite source bytes or the original candidate observation.

---

## 8. Stable Document Workspace boundary

Downstream ingestion/research agents consume stable capabilities such as:

```text
get_document_structure()
read_page(page_id)
read_pages(range)
search_document(query)
render_page_image(page_id)
get_evidence(locator)
```

They must **not** choose among:

- Docling versions;
- Tika;
- RapidOCR;
- Tesseract;
- JEV;
- a VLM;
- candidate versus corrected storage keys.

A deterministic resolver chooses the preferred accepted normalized representation according to
version/quality policy.

This makes engines replaceable without rewriting legal agents.

---

## 9. Manifest-driven planning and idempotency

The normalizer starts from a closed acquisition manifest, never public source URLs.

Verify:

- manifest locator/digest;
- manifest closure;
- artifact IDs and hashes;
- object existence;
- source-format metadata;
- collection/snapshot scope;
- prior equivalent successful output.

Logical idempotency key:

```text
source_sha256
+ normalization_pipeline_version
+ configuration_sha256
```

A rerun may create a new run ledger for audit, but must reuse already verified equivalent immutable
derivatives rather than recomputing blindly.

---

## 10. Format detection strategy

Do not rely on filename extensions.

Use:

1. preserved byte-signature/detected format from acquisition;
2. Tika inspection when useful;
3. parser-level validation.

Disagreement between these signals is itself a quality/diagnostic event.

Unknown or unsupported input remains explicit; never coerce arbitrary bytes into a plausible legal
document.

---

## 11. Native text before OCR

Default preference:

```text
trustworthy native source text
    >
OCR transcription
    >
VLM transcription
```

This is not an absolute truth hierarchy; embedded PDF text can itself be corrupt.

Operationally:

- inspect native text;
- keep usable native text;
- use OCR only for pages/regions requiring it;
- support mixed documents at page/region granularity;
- never rasterize all born-digital text by default.

---

## 12. OCR strategy is benchmark-owned

Before choosing the production OCR backend:

1. construct the SCJ Normalization Gold Set;
2. run candidate engines on the same calibration inputs;
3. score both generic and legal-critical fidelity;
4. validate the selected configuration against holdout;
5. retain the adapter abstraction.

Required metrics remain those in V2, including:

- CER/WER;
- digits;
- dates;
- law/article numbers;
- judgment/expediente IDs;
- money;
- names;
- citations;
- missing spans;
- reading order.

Do not optimize only punctuation-level CER.

---

## 13. Quality control remains JurisNexo-specific

Open-source parsers do not eliminate the need for our QA layer.

Before JEV/VLM, compute deterministic signals for:

- invalid/replacement characters;
- extreme fragmentation;
- suspicious text density;
- missing/empty regions;
- duplicates;
- reading-order anomalies;
- malformed high-value numeric/legal patterns;
- page-to-page discontinuities;
- legal-critical spans/regions.

Quality remains multi-dimensional; no single opaque score determines trust.

---

### DeepSeek V4.1 Flash reasoning policy

The current DeepSeek challenger is `deepseek/deepseek-v4.1-flash`.

- Default reasoning effort: `high`.
- `xhigh` is reserved for explicit high-vs-max comparison runs.
- The same benchmark cases and decision contract must be used when comparing efforts.
- Persist requested/effective model, effort, input tokens, output tokens, reasoning tokens, latency and provider-reported cost.
- Do not promote `xhigh` merely because it is more expensive or produces more reasoning tokens; promotion requires measured quality benefit on JurisNexo legal-document tasks.

## 14. JEV role

Keep the V2 policy.

JEV implements a provider-neutral:

```text
TextQualityJudge
```

It is not:

- OCR;
- vision;
- legal truth;
- an automatic gate on day one.

Begin in **shadow mode**.

Use atomic probabilistic questions.

Promote it to active routing only if holdout + sentinel evidence proves that it materially reduces
visual work without an unacceptable material-error miss rate.

Accept three outcomes:

```text
active router
advisory signal only
removed because heuristics are sufficient
```

Do not design the benchmark to justify keeping JEV.

---

## 15. Permanent sentinel sampling

Even an active quality router must sample apparent PASS pages for independent visual verification.

Use random and stratified sampling across:

- era/year;
- source format;
- OCR engine;
- document profile;
- legal-critical-token density;
- known troublesome classes.

This is how JurisNexo estimates residual false negatives and detects drift.

---

## 16. Visual verification

Keep a provider-neutral:

```text
VisualTextVerifier
```

The VLM may be hosted locally or externally and may itself be served through vLLM or another runtime.

Prefer verifying suspect spans/crops plus page context rather than retranscribing an entire page.

The verifier must be instructed to:

- transcribe conservatively;
- preserve source spelling;
- avoid legal inference;
- avoid filling unreadable content with plausible text;
- expose uncertainty.

A visual answer is another observation, not unquestioned truth.

---

## 17. Corrections and resolved text

Represent corrections as evidence-bearing assertions/patches with:

- source artifact;
- page;
- stable element/region;
- bbox when available;
- candidate reading;
- alternate reading;
- method/model/provider/version;
- verification state;
- uncertainty;
- timestamp.

High-risk unresolved disagreement becomes:

```text
QUALITY_REVIEW_REQUIRED
```

not a guessed value.

Construct resolved evidence text from accepted observations.

Maintain separate evidence text and search-normalized text.

---

## 18. Multi-document and special-document handling

A universal normalization control plane must not assume:

```text
one source artifact == one legal document
```

Some artifacts are containers/compilations:

- judicial bulletins;
- gazettes;
- bound historical volumes;
- annex bundles;
- multi-decision PDFs.

Therefore keep segmentation as a layer **after technical normalization or through a bounded specialist
workspace**, with provenance back to the physical artifact/page/region.

Do not force Docling to solve legal-document boundaries.

The Structure/Audit pipeline remains responsible for semantic/document boundaries when deterministic
segmentation is insufficient.

---

## 19. Pagination policy

Preserve the distinction between:

- physical/rendered page;
- source-printed page number;
- logical document page;
- reflowable document without intrinsic authoritative pages.

PDF pages often have stable physical coordinates.

DOC/DOCX/RTF page numbers generated through rendering are not automatically source-authoritative.

Do not invent authoritative pagination where the format does not contain it.

---

## 20. Stable evidence locators

Do not rely solely on global character offsets.

Prefer locators combining, where meaningful:

```text
source/derived artifact
page or source region
stable JurisNexo element/block locator
local span
bbox
normalization version
```

Docling element IDs may inform implementation, but raw engine internals must not become the permanent
external API without an explicit stability decision.

---

## 21. Worker isolation and supply-chain policy

Treat every input document/parser as untrusted.

Workers should use, where practical:

- unprivileged execution;
- no general network access;
- bounded RAM/CPU;
- bounded temp storage;
- per-document timeout;
- deterministic cleanup;
- read-only filesystem where practical.

Legacy Office/LibreOffice paths require particular isolation.

Pin:

- Docling version;
- Tika version/image;
- OCR package/model version;
- model revision/checksum when available;
- container digest;
- JurisNexo pipeline/config version.

Avoid implicit model downloads during production execution.

---

## 22. External provider/data-governance gate

Public legal documents may contain sensitive personal information.

Before sending text/images to JEV or an external VLM, define an approved provider policy covering:

- provider identity;
- retention/data-use/training terms;
- permitted document classes;
- redaction requirements;
- local/self-hosted fallback;
- audit metadata;
- credentials and egress boundaries.

Parser network access and deliberate model-provider egress are separate capabilities.

No provider is approved merely because an SDK supports it.

---

## 23. Durable artifact model

Retain the persistence model introduced by migration 0002:

```text
source_artifacts
    -> artifact_derivations
    -> derived_artifacts

normalization_runs
    -> normalization_run_items
```

Examples of derived artifacts:

- candidate Docling JSON;
- OCR-enhanced derivative when useful;
- quality report;
- correction/observation map;
- optional evidence crop;
- resolved normalized text;
- normalization manifest.

Do not store large complete Docling JSON payloads directly in PostgreSQL.

---

## 24. Run state, retry and circuit breaking

Checkpoint each item durably.

Distinguish:

### Permanent/document-specific

- corrupt source;
- unsupported encryption;
- unsupported format.

### Quality outcomes

- poor OCR;
- unresolved visual disagreement;
- unreliable layout/reading order.

### Retryable infrastructure

- S3/network transient;
- database transient;
- provider 429/5xx.

### Systemic/global

- invalid storage credentials;
- DB outage;
- disk exhaustion;
- required provider auth broken;
- repeated engine/runtime corruption.

Systemic failures trip a circuit breaker rather than generating thousands of identical item failures.

No degraded mode is silent.

---

## 25. Sharding and runtime portability

Estimate shard work using:

```text
page count
x scan/OCR factor
x format/legacy factor
x expected visual-verification factor
```

Bound:

- pages;
- documents;
- expected compute;
- wall time.

GitHub Actions may orchestrate the initial Principales workflow, but the worker must remain portable to:

- local/container execution;
- VM;
- batch scheduler;
- Kubernetes/other job runtime.

GitHub Actions is not the architecture.

---

## 26. Reconciliation

A normalization run closes only after comparing:

```text
input work plan
normalization_run_items
derived-artifact records
derivation edges
S3 objects
quality reports
```

Require:

- every selected input accounted for;
- every referenced object present;
- derivation lineage complete;
- unresolved quality explicit;
- counts reconcile;
- no unaccounted current-run output under the governed namespace.

Then publish an immutable normalization manifest.

---

## 27. Observability and economics

Per item record where practical:

- format/profile;
- pages;
- native pages;
- OCR pages;
- JEV pages/tokens/cost;
- VLM pages/tokens/cost;
- corrections;
- critical corrections;
- unresolved pages;
- duration;
- output size;
- resource usage;
- failure class.

Per run monitor:

- format distribution;
- OCR rate;
- escalation rate;
- critical correction rate;
- review rate;
- failure rate;
- throughput;
- cost/page;
- cost/document.

These metrics detect drift and determine whether a challenger engine is worth operational complexity.

---

## 28. Search/index boundary

Do not let raw OCR feed trusted search automatically.

Preferred sequence:

```text
normalized candidate
    -> quality acceptance
    -> resolved evidence/search views
    -> full-text index
    -> chunking
    -> embeddings when enabled
```

Chunker/model/index versions must reference the normalized-text version so later corrections can
invalidate/rebuild stale downstream derivatives.

---

## 29. Garbage collection

Do not implement automatic derivative deletion in the initial rollout.

First build a read-only reachability/orphan audit.

Only later introduce a retention/GC policy with proof that historical provenance and live manifests
cannot be deleted.

---

## 30. Generic contract tests versus source-specific regression suites

This is a key universal-platform rule.

### Generic normalization contract suite

Must ultimately cover representative behavior independent of institution:

- born-digital PDF;
- scanned PDF;
- mixed PDF;
- DOCX;
- DOC;
- RTF;
- HTML when supported;
- image input when supported;
- corrupt/unsupported input;
- engine failure;
- S3/DB interruption;
- resumability;
- idempotency;
- reconciliation;
- provider failure/degraded mode;
- evidence lineage.

### Source-specific regression suites

Examples:

- SCJ Principales;
- TC;
- historical judicial bulletin;
- legislation/gazette.

A new institution should normally require a source adapter and regression corpus, **not another
normalization architecture**.

---

## 31. Engine benchmark strategy

Do not compare parsers with one vague "quality" number.

For structural engines/challengers compare:

- supported input coverage;
- exact text fidelity;
- legal-critical-token fidelity;
- missing content;
- reading order;
- tables;
- page/region provenance;
- output determinism/stability;
- runtime;
- RAM/CPU/GPU needs;
- license/deployment constraints;
- failure modes;
- artifact size.

The baseline initially is:

```text
Docling + selected OCR backend
```

Use Tika primarily as detection/fallback.

Only benchmark Marker/MinerU/PaddleOCR or another challenger against an observed problem or strategic
risk; do not create permanent benchmark theater with every available parser.

---

## 32. Principales rollout plan

Principales is the first controlled production experiment because it is bounded and high signal.

Execute in stages:

```text
fixtures
    ->
Gold Set calibration
    ->
Gold Set holdout
    ->
10-20 adversarial Principales documents
    ->
broader Principales canary
    ->
full Principales
    ->
out-of-distribution SCJ sample
    ->
decision on broader SCJ
```

The normalizer itself remains source-agnostic throughout.

---

## 33. Principales Definition of Done

Do not declare Principales normalized because a workflow is green.

Require evidence for:

- all selected inputs accounted for;
- immutable source preservation;
- complete derivation lineage;
- idempotent rerun;
- interrupted-run resume;
- S3/DB/manifest reconciliation;
- OCR holdout quality;
- reading-order quality;
- legal-critical residual error;
- JEV false-negative/escalation recall;
- permanent sentinel sampling;
- VLM false-correction rate;
- explicit unresolved disagreements;
- cost/page and cost/document;
- runtime/resource distribution;
- provider/privacy compliance;
- parser isolation;
- no silent degraded modes.

---

## 34. Promotion to other sources

After Principales:

1. run the out-of-distribution SCJ sample;
2. validate the same generic normalization contracts;
3. onboard TC or another source through acquisition/source adapters;
4. run a source-specific regression set;
5. add a normalization exception only if measured document behavior requires it.

The success condition is:

> adding a new legal source does not require rewriting manifest handling, OCR policy, quality policy,
> JEV/VLM routing, provenance, run state or reconciliation.

If it does, investigate whether the control-plane abstraction is leaking.

---

## 35. Decisions deliberately open

Do not prematurely freeze:

- exact Tika role beyond detection/metadata/fallback;
- OCR winner;
- whether PaddleOCR/Marker/MinerU are needed in production;
- OCRmyPDF usage;
- Docling tuning;
- JEV production role/thresholds;
- sentinel percentage;
- VLM/provider;
- stable element-locator implementation;
- scheduler;
- concurrency;
- external-provider privacy policy details.

Close these through benchmark or operational evidence.

---

## 36. Explicit rejected approaches

Do not:

- build a JurisNexo general-purpose document parser;
- create institution-specific copies of the normalization pipeline;
- equate file extension with format;
- OCR all born-digital pages;
- treat Tika extracted text as canonical merely because it is broad;
- treat Docling JSON as legal semantics;
- relationalize all Docling internals;
- make Markdown/chunks canonical;
- make one OCR engine a permanent architecture dependency;
- run all challenger parsers in production without demonstrated need;
- make JEV an active gate before benchmark evidence;
- treat VLM as ground truth;
- mutate earlier observations destructively;
- index unaccepted OCR as trusted text;
- couple legal agents to parser/provider versions;
- claim universal support merely because a library advertises a file type;
- widen to the full SCJ corpus before the Principales and holdout gates pass.

---

## 37. Implementation workstreams

Implement in this order.

### Workstream 0 — reconcile substrate

Before new normalization code:

1. reconcile PR #111 against current `development`;
2. resolve migration-head drift;
3. require exact-head CI;
4. preserve migration 0002 semantics or deliberately supersede them with equal/stronger provenance.

### Workstream 1 — engine spike, not production pipeline

Build a small isolated executable proving:

```text
source bytes
 -> format detection
 -> Docling conversion
 -> Docling JSON
```

against representative fixtures.

Include Tika inspection.

Do not add JEV/VLM yet.

Output: measured compatibility/failure matrix.

### Workstream 2 — universal engine interfaces

Define narrow internal interfaces for:

```text
FormatInspector
StructuralNormalizer
OcrBackend
TextQualityJudge
VisualTextVerifier
NormalizedRepresentationResolver
```

Do not create an abstraction framework larger than current needs.

Each interface should correspond to a real replaceability boundary proven by at least two implementations,
a fake/test implementation, or a credible imminent alternative.

### Workstream 3 — Gold Set and generic fixtures

Create:

- generic format fixtures;
- SCJ calibration set;
- SCJ holdout;
- legal-critical scoring;
- reading-order/missing-content scoring.

Benchmark Docling + OCR candidates.

### Workstream 4 — manifest planner + durable run

Implement:

- manifest verification;
- Principales selection;
- dry run;
- idempotency;
- durable run/items;
- checkpoint/resume.

### Workstream 5 — Docling/Tika production adapter

Integrate the selected versions with:

- sandboxing;
- pinned dependencies/models;
- object-storage artifacts;
- provenance lineage;
- quality metadata.

### Workstream 6 — deterministic QA

Implement:

- text/layout health signals;
- legal-critical risk;
- page/region routing;
- explicit quality state.

### Workstream 7 — JEV shadow

Add JEV behind `TextQualityJudge`.

Persist predictions.

No active routing until benchmark promotion.

### Workstream 8 — visual verification

Add:

- image/crop rendering;
- provider policy gate;
- `VisualTextVerifier`;
- correction assertions;
- unresolved review state.

### Workstream 9 — resolved views + sentinel sampling

Implement:

- evidence-text resolver;
- search-text view;
- stable workspace resolution;
- permanent sentinel selection;
- residual-error measurement.

### Workstream 10 — reconciliation

Implement run closure and immutable normalization manifest.

### Workstream 11 — Principales canary/full rollout

Run the staged rollout and publish benchmark/operational evidence.

### Workstream 12 — second-source proof

Onboard a materially different source (preferably TC or another legal-document class) without forking
the core pipeline.

This workstream is the real proof that the platform is universal in architecture rather than merely
an SCJ normalizer with generic names.

---

## 38. Required test/evidence matrix

For every workstream, distinguish:

```text
structural/fitness proof
unit/contract proof
real PostgreSQL/object-storage integration proof
benchmark semantic proof
operational canary evidence
```

Not every change needs every evidence class, but claims must match the evidence actually run.

Critical future evidence includes:

- derivation/source immutability invariant;
- normalization-run reproducibility;
- source-agnostic core boundary fitness;
- parser/provider replaceability contract;
- manifest/reconciliation integration;
- interrupted-run recovery;
- OCR/legal-critical benchmark;
- JEV false-negative benchmark;
- VLM correction benchmark;
- second-source regression proof.

---

## 39. No-orphan decision ledger

The following decisions are accepted and must not remain only in chat:

| Decision | Status |
| --- | --- |
| Acquisition and normalization remain separate | CURRENT |
| Normalization reads preserved S3 source bytes, not public URLs | CURRENT |
| Original source bytes are immutable | CURRENT |
| Full technical derivatives live primarily in object storage | CURRENT |
| PostgreSQL stores identity, lineage, run state and useful projections | CURRENT |
| JurisNexo builds a normalization control plane, not universal parsers | CURRENT |
| Docling is the initial primary structural normalizer | CURRENT |
| Tika is the complementary format/metadata/fallback capability | CURRENT |
| OCR engines remain benchmark-selected plugins | CURRENT |
| Marker/MinerU/PaddleOCR are challengers/specialists, not mandatory stack | CURRENT |
| Unstructured is not the canonical document model | CURRENT |
| Normalization core is source/institution agnostic | CURRENT |
| Principales is first validation corpus, not architecture scope | CURRENT |
| One physical artifact may contain multiple legal documents | CURRENT |
| Technical normalization and legal-semantic extraction remain separate | CURRENT |
| Native good text is preferred over unnecessary OCR | CURRENT |
| JEV begins in shadow mode | CURRENT |
| JEV may be kept, demoted or removed based on evidence | CURRENT |
| Sentinel sampling remains permanent | CURRENT |
| VLM is verifier/reader, not ground truth | CURRENT |
| Corrections are versioned assertions, not destructive rewrites | CURRENT |
| Evidence text and search text are distinct | CURRENT |
| Agents consume stable workspace capabilities, not engine internals | CURRENT |
| External provider use requires explicit data-governance policy | CURRENT |
| GitHub Actions is an initial orchestrator, not architectural scheduler | CURRENT |
| Run closure requires plan/DB/S3/lineage reconciliation | CURRENT |
| Principales -> broad SCJ requires measured promotion gate | CURRENT |
| Second materially different source is required to prove universality | CURRENT |
| Automatic derivative GC is deferred; begin with read-only orphan audit | CURRENT |

---

## 40. Next-agent execution checklist

The next agent must:

1. read repository `AGENTS.md`, `docs/AGENTS.md`, crosswalk and branch rules;
2. inspect current `development`, active integration lane and PR #111 before modifying code;
3. read docs 38, 39 and this document;
4. use doc 40 as retained V2 rationale, not as competing current parser architecture;
5. inspect actual acquired Principales manifests/source formats;
6. verify the current migration head and normalization DB substrate;
7. implement **Workstream 1 only** before committing to new abstractions;
8. run Docling/Tika against representative real/fixture documents and record failure classes;
9. build the Gold Set before tuning OCR/JEV/VLM;
10. preserve all HARD provenance guarantees while evolving implementation;
11. keep parser/provider choices replaceable;
12. do not expand to full SCJ before Principales gates pass;
13. after Principales, prove the architecture on a materially different second source;
14. update docs/guarantees/proof map whenever an accepted contract materially changes;
15. never report a parser/model/benchmark as successful unless the intended exact inputs/version/environment actually ran.

---

## 41. Completion criterion for this handoff

This handoff is successful if an implementation agent can answer, without prior conversation:

- what problem JurisNexo owns versus delegates;
- why Docling and Tika are used;
- which parts remain replaceable;
- how source adapters differ from normalization engines;
- what the common normalized contract is;
- how OCR/JEV/VLM are benchmarked and gated;
- how provenance and corrections remain auditable;
- how workers recover and reconcile;
- why Principales is only the first canary;
- what proves the design works for another legal source;
- what workstream to implement first;
- what evidence is required before promoting scope.

If any of those answers requires reconstructing chat history, the documentation is incomplete.
