# JurisNexo — Document normalization pipeline V2 implementation handoff

## Status

**Implementation handoff / current accepted design.**

This document converts the accepted document-normalization plan into an executable
engineering sequence. It is intentionally more operational than
`39-document-normalization-and-derived-artifacts.md`.

Current repository state at the time of this handoff:

- official SCJ source bytes and acquisition manifests already exist in S3-compatible storage;
- acquisition and normalization are separate workflows;
- PR #111 (`feat/document-normalization-artifacts`) contains the database substrate for
  derived artifacts, derivation lineage, normalization runs and per-item outcomes;
- the actual Docling/OCR/JEV/VLM normalization worker is **not implemented yet**;
- the initial production slice is **SCJ Principales only**, not the full SCJ corpus.

Do not infer that a documented stage already exists in code. Verify the current branch and
schema head before implementation.

---

## 1. Goal

Build a resumable, auditable technical-normalization pipeline that transforms preserved official
source artifacts into trustworthy, queryable normalized documents while preserving every material
observation and uncertainty.

The pipeline must answer:

> What can JurisNexo faithfully reconstruct from this source, what remains uncertain, and which
> later corrections or verifications produced the currently preferred text view?

It must **not** answer substantive legal questions. Legal extraction remains a later pipeline.

---

## 2. Non-goals

This work does not:

- extract legal issues, holdings, facts, disposition semantics or treatment;
- assign legal authority;
- create embeddings before text passes the quality gate;
- deeply normalize the full SCJ corpus in the first rollout;
- make Markdown or RAG chunks the canonical normalized representation;
- use JEV, Docling confidence or a VLM as unquestioned ground truth;
- mutate or replace official source bytes;
- make GitHub Actions the permanent scheduler architecture;
- hard-code one OCR engine, one VLM provider or one quality threshold forever.

---

## 3. Canonical separation of truths

Keep four epistemic layers distinct:

```text
1. SOURCE
   exact official bytes + source provenance

2. STRUCTURAL NORMALIZATION
   DoclingDocument / page/block/layout reconstruction

3. TEXT OBSERVATIONS
   native text, OCR readings, VLM readings, human readings

4. RESOLVED TEXT VIEW
   current preferred reconstruction assembled from accepted observations
```

A visual correction must not silently rewrite the original Docling output. The original candidate
normalization remains immutable and later corrections are separate evidence-bearing observations.

---

## 4. End-to-end architecture

```text
CLOSED ACQUISITION MANIFEST
            |
            v
MANIFEST VERIFIER
            |
            v
NORMALIZATION PLANNER
            |
            v
SOURCE PROFILER
            |
     +------+------+
     |             |
 native/digital   scan/mixed
     |             |
     v             v
native parse     OCR candidate
     |             |
     +------+------+
            |
            v
         DOCLING
            |
            v
CANDIDATE STRUCTURAL DOCUMENT
            |
            v
DETERMINISTIC QUALITY SIGNALS
            |
            +---- Docling confidence
            |
            v
JEV TEXT QUALITY JUDGE
(initially shadow-only)
            |
      +-----+------+
      |            |
   appears       suspicious /
    clean         uncertain
      |            |
      |            v
      |      VISUAL VERIFIER
      |        (VLM)
      |            |
      |            v
      |      correction assertion
      |            |
      +------+-----+
             |
             v
SENTINEL / QUALITY AUDIT SAMPLE
             |
             v
RESOLVED NORMALIZED TEXT VIEW
             |
             v
NORMALIZATION RECONCILIATION
             |
             v
IMMUTABLE NORMALIZATION MANIFEST
             |
             v
SEARCHABLE CORPUS / LATER LEGAL INGESTION
```

---

## 5. Hard invariants

### INV-NORM-SOURCE-IMMUTABILITY

Official bytes are immutable and are never replaced by OCR, rendering, normalization or model output.

### INV-NORM-DERIVATION-LINEAGE

Every derived artifact must trace through explicit acyclic lineage to one preserved source artifact.

### INV-NORM-MANIFEST-BOUNDARY

Normalization only consumes a closed, verified acquisition manifest. A normalization failure cannot
retroactively make acquisition incomplete.

### INV-NORM-NO-SILENT-CORRECTION

OCR/VLM/human corrections remain versioned observations or patches. They never silently rewrite the
source observation that produced them.

### INV-NORM-NO-SILENT-DEGRADATION

If JEV, VLM, S3, database, parser capability or another required component is unavailable, the item/run
must expose that degraded state. Do not silently lower evidence standards.

### INV-NORM-QUALITY-NOT-SINGLE-SCORE

Do not represent normalization trust as one opaque scalar. Preserve separate dimensions such as
text completeness, OCR quality, layout quality, reading order and legal-critical-token risk.

### INV-NORM-MODEL-NOT-TRUTH

JEV is a routing signal. A VLM is another reading of visual evidence. Neither becomes source truth
merely because the model is confident.

### INV-NORM-IDEMPOTENCY

Equivalent successful processing for the same:

```text
source_sha256
+ pipeline_version
+ config_sha256
```

must be reusable rather than duplicated.

---

## 6. Initial rollout boundary: SCJ Principales

The first real-corpus normalization workflow must reject accidental broad SCJ processing.

Initial allowed corpus:

```text
SCJ Principales
```

The code should remain source-agnostic where practical, but the operational workflow must require an
explicit Principales collection/snapshot identity until promotion criteria are met.

Recommended manual controls:

- `dry_run`;
- `max_documents`;
- `max_pages`;
- selected manifest/snapshot;
- explicit pipeline/config version;
- bounded shard concurrency.

The first objective is to learn the normalization error/cost distribution, not to maximize document count.

---

## 7. CI versus corpus execution

Do not conflate repository CI with a corpus backfill.

### Repository CI

Runs on pull requests and must use fixtures/small controlled samples to prove:

- parser routing;
- quality-signal logic;
- idempotency;
- database invariants;
- manifest validation;
- reconciliation;
- failure/retry state;
- provider adapter contracts through fakes or dedicated provider tests where appropriate.

Repository CI must not normalize real production corpus data on every PR.

### Operational normalization workflow

A manually invoked or explicitly scheduled workflow may initially run on GitHub Actions:

```text
prepare
  -> verify immutable manifest
  -> build work plan/shards

normalize matrix
  -> process bounded shard
  -> checkpoint after every item

reconcile
  -> compare plan / DB / S3 / lineage
  -> close normalization manifest
```

The worker contract must remain portable to a VM/container/batch scheduler later.

---

## 8. Phase 0 — build the benchmark before trusting the pipeline

Create a **SCJ Normalization Gold Set** before full Principales processing.

Deliberately include:

- born-digital PDFs;
- clean scans;
- poor scans;
- skew/rotation;
- small fonts;
- stamps/signatures;
- tables;
- dense legal citations;
- dates and money;
- names;
- judgment/case/expediente identifiers;
- mixed native+scan PDFs;
- DOC/DOCX/RTF examples where available;
- long and structurally odd documents.

Split the benchmark into:

```text
calibration set
holdout set
```

Never tune thresholds against the holdout.

Before expanding beyond Principales, add an out-of-distribution SCJ holdout.

### Required quality metrics

Measure at minimum:

- character error rate (CER);
- word error rate (WER);
- exact digit accuracy;
- exact date accuracy;
- legal article/law-number accuracy;
- judgment/decision/case/expediente identifier accuracy;
- proper-name accuracy;
- citation accuracy;
- missing-span/content rate;
- reading-order accuracy;
- JEV escalation recall for material errors;
- JEV false-negative rate;
- VLM false-correction rate;
- unresolved disagreement rate.

The primary product-risk metric is:

> residual materially dangerous OCR error rate after the entire normalization pipeline.

---

## 9. Phase 1 — manifest verifier and normalization planner

Input:

- immutable acquisition manifest locator;
- manifest SHA-256;
- expected source/collection identity;
- pipeline version;
- config digest.

Verify:

- manifest integrity;
- manifest closure/accounting state;
- each referenced source artifact identity;
- S3 object existence;
- recorded byte size;
- recorded source format;
- SHA verification where required by policy;
- whether equivalent normalization already exists.

Output an immutable/versioned work plan.

The planner must not depend on source URLs for document bytes. Workers consume the preserved S3 artifact.

---

## 10. Phase 2 — source profiler

Profile each document cheaply before selecting the expensive path.

For PDFs record operational signals such as:

- page count;
- usable native text by page;
- characters per page;
- image coverage;
- mixed scan/native behavior;
- rotation/page-size anomalies;
- evidence of an existing OCR layer;
- corrupt/encrypted/unsupported state.

For Office/RTF record format and supported conversion path.

Use a small routing vocabulary:

```text
NATIVE
SCAN
MIXED
LEGACY_OFFICE
CORRUPT
UNSUPPORTED
```

Routing must support **page-level OCR decisions** for mixed PDFs.

---

## 11. Phase 3 — structural normalization with Docling

Docling is the initial primary technical normalizer, not the legal model and not a permanent database schema.

Rules:

- preserve good native text instead of OCRing it again;
- OCR only pages/regions that require it;
- do not force full-page OCR by default;
- preserve page/block/layout provenance;
- serialize the complete candidate `DoclingDocument` to immutable object storage;
- store only identity/provenance/query-critical projections in PostgreSQL;
- do not use Markdown as canonical;
- do not use chunk JSONL as canonical.

### OCR engine selection

Do not hard-code the architecture to RapidOCR or Tesseract.

Initial benchmark candidates:

- RapidOCR / PP-OCR family;
- Tesseract.

Promote a default only from SCJ benchmark evidence.

OCRmyPDF remains optional and should be introduced only if benchmarked preprocessing/deskew/rotation
or searchable-PDF output materially improves the pipeline.

---

## 12. Phase 4 — deterministic quality analysis

Run cheap deterministic checks before any language model.

Signals should include where applicable:

- replacement/invalid characters;
- extreme fragmentation;
- suspicious whitespace/tokenization;
- unexpected empty pages;
- density drops relative to neighbors;
- duplicate page/text signatures;
- abnormal reading-order indicators;
- likely text regions with no text;
- malformed high-value numeric patterns;
- suspicious legal references;
- candidate critical spans.

### Legal-critical tokens/regions

Treat uncertainty as higher risk around:

- judgment/decision numbers;
- case/docket/expediente identifiers;
- law numbers;
- article numbers;
- dates;
- monetary amounts;
- names;
- citations;
- dispositive/decision regions such as headings equivalent to `FALLA`, `DECIDE`,
  `POR TALES MOTIVOS`.

This is risk routing, not legal interpretation.

Do not waste equivalent effort transcribing purely decorative seals/signatures unless they contain relevant text.

---

## 13. Phase 5 — Docling confidence as one signal

Record available Docling page/document quality/confidence outputs.

Do not convert them directly into source truth or hard-code undocumented numeric semantics.

Persist the relevant grade/version/configuration so future upgrades can be compared.

---

## 14. Phase 6 — JEV quality judge in shadow mode

JEV's role is **textual risk classification/routing**, not OCR and not visual verification.

Create a provider-neutral interface such as:

```text
TextQualityJudge
```

with JEV as one implementation.

Do not spread provider-specific conditionals throughout the pipeline.

### Initial JEV mode

```text
SHADOW ONLY
```

During calibration/canary runs:

- call JEV;
- persist its typed probabilities/decisions;
- do not let JEV alone decide which pages bypass visual checking;
- compare its decisions to visual/manual benchmark truth.

### Atomic questions

Prefer small independent judgments such as:

- text appears corrupted;
- important content may be missing;
- reading order appears broken;
- legal identifiers appear suspicious;
- text is sufficiently readable for research;
- visual inspection is warranted.

Our deterministic policy combines these signals.

### Promotion rule

JEV becomes an active router only after the holdout demonstrates acceptable recall for materially
important errors. It may ultimately remain advisory or be removed if deterministic QA performs as well.

---

## 15. Phase 7 — permanent sentinel sampling

Even after JEV becomes an active router, sample some apparent PASS pages for independent visual checking.

Sampling must include:

- random PASS sample;
- year/era strata;
- source-format strata;
- OCR-engine strata;
- high legal-critical-token density;
- historically troublesome document profiles.

This estimates the errors the router does **not** know it missed.

Sentinel sampling is permanent operational quality monitoring, not a one-time experiment.

---

## 16. Phase 8 — visual verification

Define a provider-neutral interface:

```text
VisualTextVerifier
```

A VLM implementation may be local or external.

Note terminology:

- **VLM** = vision-language model;
- **vLLM** = a runtime/server that may host a compatible model.

Do not conflate them.

### Visual verification policy

Prefer:

```text
suspect span / crop
+ page context when useful
```

over free retranscription of an entire page.

The instruction must require conservative transcription:

- do not normalize spelling;
- do not fix grammar;
- do not infer a legal citation from world knowledge;
- do not fill unreadable text with plausible content;
- preserve uncertainty explicitly.

A VLM output is an observation, not automatic truth.

---

## 17. Phase 9 — correction assertions, not destructive rewrites

Represent a correction/verification conceptually as:

```text
source artifact
page
Docling element / region locator
bbox where available
candidate reading
alternate visual reading
verification method
provider/model/version
status
confidence/uncertainty
timestamp
```

Possible statuses:

```text
candidate
verified
conflicting
human_review_required
```

Do not mutate the original Docling JSON in place.

Produce a resolved text view from the accepted observation set.

For high-risk disagreements (dates, amounts, identifiers, citations), prefer
`QUALITY_REVIEW_REQUIRED` over silently choosing one model's answer.

---

## 18. Evidence text versus search text

Maintain conceptually distinct views:

### Evidence text

Closest accepted reconstruction of the source and suitable for citation/provenance.

### Search text

May apply controlled search-oriented normalization such as Unicode/whitespace normalization.

Search normalization must never destroy the evidence text.

Do not automatically correct source spelling, punctuation, capitalization or source-native errors.

---

## 19. Stable locators and offsets

Global character offsets are fragile because an earlier correction can shift all later positions.

Prefer evidence references that can survive text-view changes:

```text
artifact
+ page
+ stable element/block identity
+ local span
+ bbox when available
```

Character offsets may remain a derived convenience.

Before large-scale legal extraction, define and benchmark a sufficiently stable JurisNexo element locator.
Do not expose raw Docling internals as a permanent API contract.

---

## 20. Parser/worker isolation

Treat every source file as untrusted parser input.

Document workers should use:

- unprivileged execution;
- no network by default;
- bounded CPU/RAM;
- bounded temporary disk;
- hard per-document timeout;
- deterministic cleanup;
- read-only root filesystem where practical.

Legacy DOC/RTF processing through LibreOffice especially belongs in isolated workers.

External JEV/VLM access, when authorized, should be a separate deliberate outbound capability rather than general parser network access.

---

## 21. External-provider/privacy gate

Public judgments can still contain personal or sensitive data.

Before transmitting OCR text or page images to any external provider, define an explicit
normalization-provider policy covering:

- approved providers;
- retention/training/data-use terms;
- permitted document classes;
- whether redaction is required;
- whether local/self-hosted alternatives are mandatory for some content;
- audit metadata retained for the call.

Apply the same policy family to JEV text calls and VLM image calls.

Do not accidentally encode provider approval in model-adapter code.

---

## 22. Failure taxonomy and retry policy

### Document-permanent / non-retryable without a new strategy

Examples:

- corrupt PDF;
- unsupported encryption;
- malformed legacy Office input;
- genuinely unsupported format.

### Quality outcome

Examples:

- OCR too poor;
- unresolved OCR/VLM disagreement;
- reading order unreliable.

These should usually become `QUALITY_REVIEW_REQUIRED`, not infrastructure failure.

### Retryable infrastructure/provider

Examples:

- S3 timeout;
- DB transient failure;
- provider 429/5xx;
- network interruption.

### Global circuit-breaker failures

Examples:

- storage credentials invalid;
- DB unavailable;
- disk exhausted;
- required provider authorization broken;
- repeated identical systemic parser failure.

A global failure should stop further expensive mutation instead of failing thousands of documents individually.

---

## 23. Degraded-mode policy

Any degraded mode must be explicit.

Examples:

- JEV unavailable -> quality judge unavailable;
- VLM unavailable -> visual verification pending;
- provider disabled by policy -> local/manual path required.

Do not report a document as fully accepted merely because an optional/required verification layer was silently skipped.

---

## 24. Checkpointing and resumability

Persist after every document/item:

- item state;
- produced artifact identity;
- derivation edge;
- quality summary;
- error/verification state.

A shard interruption after item N must not require repeating completed items 1..N.

Use the same recovery philosophy as acquisition:

```text
incremental durable evidence
+ verified resume
+ final immutable manifest only after controlled closure
```

---

## 25. Sharding and concurrency

Do not shard solely by document count.

Estimate work using signals such as:

```text
page_count
x scan/OCR factor
x legacy-format factor
x expected visual-verification factor
```

Each shard should have bounded:

- document count;
- page count;
- expected compute;
- wall-time budget.

Start with low concurrency and measure peak RAM/runtime before increasing parallelism.

---

## 26. Artifact strategy

Conceptual durable artifacts may include:

```text
source artifact
candidate Docling JSON
quality-report.json
correction/observation map
optional OCR/render derivative
optional persisted verification crop
resolved text derivative/view
normalization manifest
```

Do not persist every rendered page image by default. Render from the source on demand unless the derivative itself is needed as evidence or is expensive to reproduce.

Visual preprocessing (deskew/rotation/contrast/denoise) is also a derivative when it materially affects recognition and must not replace the source image.

---

## 27. Database mapping

The first persistence substrate is the model introduced by migration
`0048_document_normalization_artifacts`:

```text
source_artifacts
    -> artifact_derivations
    -> derived_artifacts

normalization_runs
    -> normalization_run_items
```

The complete Docling/quality payload remains in object storage.

Do not create relational mirrors of every Docling internal node unless a demonstrated query need requires a stable JurisNexo projection.

Before implementing correction assertions or stable element locators, inspect the current schema and add only the smallest evidence-bearing extension required by the benchmarked pipeline.

---

## 28. Reconciliation and run closure

A run does not close because all workers exited.

The reconciler must compare:

```text
normalization plan
normalization_run_items
derived artifacts
artifact derivations
S3 objects
quality reports
```

Closure requires:

- every selected input accounted for;
- no missing referenced object;
- no unaccounted output under the current run namespace/policy;
- lineage present for every derived artifact used by the run;
- unresolved quality states explicitly represented;
- deterministic run counts matching item outcomes.

Then publish an immutable normalization manifest.

A later re-normalization creates a new run/manifest rather than rewriting the old one.

---

## 29. Observability, cost and drift

Record per item where practical:

- pages;
- native/OCR page counts;
- pages sent to JEV;
- pages sent to visual verification;
- corrections;
- critical corrections;
- unresolved pages;
- duration;
- output sizes;
- resource/cost usage;
- failure class.

Track per run:

- native/scan/mixed distribution;
- OCR rate;
- JEV suspect rate;
- VLM escalation rate;
- critical-correction rate;
- quality-review rate;
- failure rate;
- throughput;
- estimated cost/page and cost/document.

Material shifts in these distributions should be treated as drift signals after upgrades or source changes.

---

## 30. Upgrade discipline

For major changes to:

- Docling;
- OCR engine/model;
- JEV model/questions;
- VLM model/prompt;
- rendering/preprocessing;

run old and new configurations on the same controlled sample.

Compare:

- text changes;
- changed pages/blocks;
- legal-critical-token changes;
- quality metrics;
- escalation behavior;
- runtime/cost.

Do not upgrade the production configuration solely because a dependency has a newer version.

Pin:

- package versions;
- model revision/checksum where obtainable;
- container image digest;
- pipeline version;
- config digest;
- quality-question schema/prompt versions.

Avoid implicit model downloads in production workers; pre-fetch and verify pinned assets where practical.

---

## 31. Indexing boundary

Only accepted normalized text should feed the trusted search/index pipeline.

```text
normalize
  -> quality gate
  -> materialize searchable text
  -> FTS
  -> chunking
  -> embeddings when enabled
```

Chunks and embeddings must be versioned against the normalized text/chunker/model configuration so a later correction can invalidate/rebuild stale derived indexes.

---

## 32. Human review

Human review is a normal quality state, not a pipeline crash.

A reviewer should create another evidence-bearing observation rather than editing stored source/OCR text destructively.

The resolved-text policy may prefer a verified human reading, but the earlier OCR/VLM observations remain inspectable.

---

## 33. Phased implementation order

### Phase A — substrate reconciliation

Before new worker code:

1. reconcile PR #111 with current `development`;
2. ensure migration head and CI are green;
3. verify derived-artifact/run tables match this handoff;
4. add any minimal schema extension only when required by the next phase.

### Phase B — benchmark + fixtures

1. build calibration/holdout Gold Set;
2. create representative fixture artifacts;
3. define scoring code for OCR/legal-critical metrics.

### Phase C — manifest planner

1. verify acquisition manifest;
2. select Principales;
3. create idempotent normalization run/work plan;
4. implement dry-run and bounded canary controls.

### Phase D — profiler + Docling baseline

1. implement PDF/Office profiler;
2. route native/scan/mixed;
3. produce immutable candidate Docling JSON;
4. register derived artifact + lineage.

### Phase E — OCR benchmark/default

1. compare candidate OCR engines on calibration;
2. select initial default;
3. validate on holdout;
4. retain engine abstraction.

### Phase F — deterministic QA

1. implement quality dimensions;
2. legal-critical-token/region detection;
3. missing-content/reading-order signals;
4. persist quality report.

### Phase G — JEV shadow

1. implement provider-neutral text-quality judge;
2. add JEV adapter;
3. version atomic questions;
4. record predictions without gating;
5. measure against gold/visual truth.

### Phase H — visual verifier

1. provider-neutral VLM interface;
2. crop/page rendering;
3. conservative transcription contract;
4. correction assertion format;
5. unresolved/high-risk disagreement handling.

### Phase I — resolved text + sentinel sampling

1. deterministic resolved-text policy;
2. evidence/search text views;
3. sentinel sample selection;
4. residual-error measurement.

### Phase J — canary runs

Run successively:

```text
fixtures
-> adversarial 10-20 Principales docs
-> broader Principales canary
-> full Principales
```

### Phase K — reconciliation + indexing

1. final run reconciler;
2. immutable normalization manifest;
3. materialized searchable text;
4. defer embeddings until quality/invalidation contracts are proven.

### Phase L — out-of-distribution gate

Run a controlled non-Principales SCJ sample before any broad backfill decision.

---

## 34. Decisions intentionally left open

These are benchmark decisions, not missing architecture:

- RapidOCR vs Tesseract vs another OCR backend;
- whether OCRmyPDF preprocessing materially helps;
- exact Docling OCR/layout settings;
- JEV promotion thresholds;
- sentinel sampling percentage;
- which JEV atomic questions survive calibration;
- which VLM/provider/local model wins;
- whether a second visual verifier is worth the cost for high-risk conflicts;
- exact worker concurrency;
- exact shard sizing;
- GitHub Actions vs later dedicated batch workers;
- exact stable element-locator implementation;
- exact provider privacy policy.

Do not invent permanent values before collecting Principales evidence.

---

## 35. Explicitly deferred/rejected shortcuts

Do not:

- run full SCJ 1994+ before the Principales/holdout gate;
- OCR all pages indiscriminately;
- trust embedded PDF text blindly;
- make JEV an active gate on day one;
- treat VLM output as guaranteed truth;
- allow whole-page free rewriting when only a span is suspect;
- overwrite Docling JSON after visual correction;
- automatically spell-correct source text;
- store complete multi-MB Docling payloads in PostgreSQL by default;
- make Markdown canonical;
- make chunks canonical;
- create embeddings before quality acceptance;
- use global char offsets as the only evidence locator;
- keep parser network access open;
- hide degraded modes;
- close a run without S3/DB/plan reconciliation;
- optimize only for throughput/cost while residual legal-critical error is unknown.

---

## 36. Definition of Done — full Principales normalization

Do not call Principales normalization complete until all of the following are evidenced:

- every selected artifact is accounted for;
- source bytes remain unchanged;
- derived outputs are immutable/content-addressed;
- complete lineage exists back to source;
- rerun idempotency is demonstrated;
- interrupted work resumes without redoing completed items;
- normalization reconciliation closes cleanly;
- OCR quality is measured on holdout;
- legal-critical error rate is measured;
- JEV false-negative/escalation recall is measured;
- sentinel sampling is operational;
- VLM false-correction/verification quality is measured;
- unresolved high-risk disagreements are visible;
- cost/page and cost/document are known;
- runtime/peak-resource distribution is known well enough for worker sizing;
- degraded/provider failure behavior is explicit;
- privacy/provider policy is approved for the chosen execution path.

A green GitHub workflow alone does not satisfy this Definition of Done.

---

## 37. Promotion gate — Principales to broader SCJ

Broader SCJ normalization may start only after:

1. Principales Definition of Done passes;
2. an out-of-distribution SCJ sample is evaluated;
3. residual legal-critical error remains acceptable outside Principales;
4. runtime/cost is sustainable;
5. recovery/reconciliation survives realistic interruption;
6. provider/privacy constraints are settled;
7. JEV's production role is explicitly chosen:
   - active router;
   - advisory only; or
   - removed;
8. OCR/VLM defaults are chosen from benchmark evidence, not preference.

The first broad run should still be a bounded shard/canary, not a one-shot corpus-wide attempt.

---

## 38. Next-agent start checklist

A new implementation agent should begin in this order:

1. read repository `AGENTS.md` and branch-governance rules;
2. inspect current `development` head and integration lane;
3. inspect PR #111/current migration head before assuming `0048` is merged;
4. read:
   - `38-jurisprudential-intelligence-flywheel-and-corpus-strategy.md`;
   - `39-document-normalization-and-derived-artifacts.md`;
   - this handoff;
   - `10-job-state-machines-and-reproducibility.md`;
   - `11-benchmark-annotation-and-evaluation-protocol.md`;
   - `15-ingestion-agent-pipeline.md`;
   - `05-security-privacy-and-trust.md`;
5. inventory actual Principales acquisition manifests and source-format distribution;
6. build the Gold Set/metrics before tuning OCR/JEV/VLM;
7. implement phases in order and add falsifiable proof for each boundary;
8. do not widen scope to full SCJ until the documented promotion gate is met.

---

## 39. Handoff completion criterion

This document is intended to prevent any of the accepted plan's core ideas from living only in chat.

If implementation discovers that one of these contracts is wrong, incomplete or too expensive,
change the canonical docs/guarantees deliberately with benchmark/evidence support. Do not silently
implement a different architecture because a provider/library makes a shortcut convenient.
