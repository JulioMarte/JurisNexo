# SCJ Principales verified corpus census

## Status and purpose

This document is the canonical operational discovery note for the durable **SCJ Principales text-layer verification census**.

Agents working on normalization, OCR, sentence extraction, JEV classification, model benchmarks, corpus selection, or SCJ Principales **must consult this dataset before repeating page-level OCR or inventing a new sample**.

The census is evidence about fidelity between a PDF's native text layer and an independent visual OCR observation. It is **not** a claim that a decision is legally correct, precedential, fully normalized, or semantically extracted.

The current completed census evaluated the 36 PDFs in the frozen SCJ Principales inventory. The successful run processed 29,811 pages and produced 13,732 admitted pages under the frozen alignment policy. No PDF satisfied the deliberately strict `verified_complete` criterion; useful evidence therefore lives primarily at page and contiguous-run level.

## Why this dataset exists

The corpus contains heterogeneous PDFs. Some have native text that closely represents what is visibly rendered; others have badly degraded or misleading text layers. Using `pdftotext` indiscriminately would therefore create unmeasured reference error.

The census separates two concepts:

```text
observation
    native PDF text + independently rendered-page OCR

admission
    deterministic policy deciding whether those observations agree enough
```

Preserving observations separately from admission is intentional. A future policy can rescore the existing observations without paying for or rerunning OCR over roughly 30k pages.

## Durable storage is S3, not GitHub Artifacts

GitHub Actions artifacts are diagnostic/convenience copies with finite retention. They are **not the durable corpus of record**.

The durable evidence is written to the configured S3-compatible object store by:

- `backend/scripts/scj_principales_corpus_publish.py`
- `.github/workflows/scj-principales-text-layer-census.yml`

The storage namespace is content-addressed:

```text
benchmarks/scj-principales/corpus-verification/v1/
  <inventory_sha256>/
    <policy_sha256>/
      <code_revision>/
        inventory.json
        census-summary.json
        _SUCCESS.json
        documents/
          <document_id>.tar.gz
```

Do not hard-code a particular inventory hash, policy hash, or revision in application logic or documentation. Those values identify one immutable census generation and will change when inputs, policy, or executed code change.

### Completion contract

A generation is a completed reusable corpus **only when `_SUCCESS.json` exists** under its generation prefix.

Individual document archives may exist before the aggregate finishes. Treat those as staged evidence, not proof that the generation is complete.

The publisher fails closed and reconciles document publication receipts against the aggregate before writing `_SUCCESS.json`.

## What each durable document archive contains

Each `documents/<document_id>.tar.gz` is deterministic and immutable. It contains the evidence produced for one source PDF, including:

- `document.json` — document-level summary, source identity, counts, verification tier, policy/provenance and run statistics;
- `pages.jsonl` — page-level classifications, scores, hashes and provenance;
- `reference-text/` — admitted native text for pages that pass the alignment gate;
- `observations/native/` — observed native PDF text by page;
- `observations/ocr/` — independent Tesseract OCR text by page.

The raw source PDF and rendered page images are not duplicated into this benchmark namespace. Their cryptographic/source provenance is recorded so the original immutable source can be resolved through the source corpus.

## Aggregate files

### `inventory.json`

Frozen identity of the source set used by the census. Use it to answer what documents were actually evaluated. Do not infer corpus membership from a current S3 listing after the fact.

### `census-summary.json`

The primary starting point for agents. It contains the aggregate totals and `document_ranking`, including per-document page counts, admitted/aligned counts, failure counts, verification rates, contiguous verified/problem runs, policy hash and source identity.

Use this file before downloading all document archives when the question can be answered from aggregate statistics.

### `_SUCCESS.json`

Atomic completion marker for the generation. Its presence means the expected inventory, aggregate and durable document receipts reconciled successfully.

## How an agent should discover and use the corpus

1. Use the repository's configured S3-compatible object-store credentials; never add credentials to source code.
2. Locate generations under `benchmarks/scj-principales/corpus-verification/v1/`.
3. Consider only generation prefixes containing `_SUCCESS.json`.
4. Read `_SUCCESS.json`, `inventory.json`, and `census-summary.json` first.
5. Select documents/pages/runs from the aggregate according to the experiment.
6. Download a document archive only when page-level text/evidence is needed.
7. Verify recorded identities/checksums rather than silently substituting a newer source PDF.
8. Preserve the generation identity (`inventory_sha256`, `policy_sha256`, `code_revision`) in benchmark outputs so results remain reproducible.

If an agent cannot access S3, it must report that limitation. It must not silently regenerate OCR, substitute GitHub artifacts as the durable source of truth, or claim the corpus is unavailable merely because a local checkout does not contain the evidence.

## What can be reused without rerunning OCR

The durable observations support questions such as:

- which PDFs have the highest proportion of visually verified native-text pages;
- which pages pass the frozen fidelity gate;
- which documents contain the longest contiguous verified regions;
- which pages failed and why;
- whether a new deterministic alignment policy would admit a different subset;
- selection of evidence-backed text for JEV classification;
- selection of realistic long document regions for Luna/DeepSeek/Ling or other model benchmarks;
- construction of positive and negative controls for normalization experiments.

Do **not** rerun Tesseract merely to answer one of these questions when the required observation already exists in the durable archive.

## Interpretation rules

### An admitted page means

Under the recorded policy and OCR configuration, the native PDF text agreed sufficiently with an independent OCR reading of the rendered page.

### An admitted page does not mean

- OCR is perfect;
- every legal semantic field has been extracted;
- the page constitutes a complete judicial decision;
- the surrounding pages pass;
- the entire PDF is trustworthy;
- the decision has any particular precedential weight.

### `verified_complete` means

Every expected page of that PDF passed the complete-document gate with no processing gaps/errors. The completed 36-PDF census produced no such document. Do not relabel an approximately 80–86% document as fully verified.

### Contiguous verified runs

These are especially useful for long-context/model experiments because they preserve natural document continuity while restricting scoring/reference claims to pages whose text layer has independent visual support.

## Current baseline result

The completed 36-PDF census established this baseline:

```text
PDFs expected:                 36
PDFs processed:                36
missing/incomplete/unexpected: 0 / 0 / 0
pages processed:               29,811
admitted/aligned pages:        13,732
relevant pages failing gate:   15,855
low-information pages:         179
pages without native text:     45
verified-complete PDFs:        0
```

Treat these numbers as the result of this frozen census generation, not as timeless facts about SCJ Principales. A new official inventory, policy, OCR engine/configuration, or code revision creates a new generation.

## Relationship to future JEV and LLM benchmarks

The intended progression is:

```text
frozen official PDFs
    -> native-text vs independent visual OCR census
    -> durable verified pages / contiguous regions
    -> JEV or deterministic boundary/classification experiments
    -> evidence-confirmed complete decision spans
    -> whole-decision extraction benchmarks
    -> compare model quality / latency / token and monetary cost
```

A model benchmark must not turn the census admission decision itself into semantic gold. The census proves text-layer fidelity; sentence boundaries, legal metadata, holdings, parties, dispositions and other semantics require their own independent evidence/evaluation contract.

## Reproduction and retry behavior

The census workflow is intentionally restartable. Completed immutable document evidence can be restored from S3 for the same inventory/policy/code generation rather than repeating OCR. Incomplete documents are recomputed.

Do not defeat this behavior by changing generation identity merely to retry a failed run. Change inventory, policy or code identity only when the underlying thing actually changed.

## Relevant implementation

Read these before modifying the census contract:

- `.github/workflows/scj-principales-text-layer-census.yml`
- `backend/scripts/scj_principales_corpus_inventory.py`
- `backend/scripts/scj_principales_text_layer_census.py`
- `backend/scripts/scj_principales_corpus_publish.py`
- `backend/src/jurisnexo/normalization/visual_reference_alignment.py`
- `backend/src/jurisnexo/normalization/visual_reference_ocr.py`
- `backend/tests/unit/test_scj_principales_text_layer_census.py`
- `backend/tests/unit/test_scj_principales_corpus_publish.py`
- `backend/tests/unit/test_visual_reference_alignment.py`
- `backend/tests/unit/test_visual_reference_ocr.py`

## Agent rule

Before proposing a new SCJ Principales OCR/reference-text benchmark, answer these questions:

```text
Can the existing durable census answer the question?
Is page fidelity or legal semantic correctness actually being measured?
Which immutable census generation is being used?
Can existing observations be rescored instead of rerunning OCR?
Does the proposed benchmark need pages, contiguous regions, or complete decisions?
What independent oracle proves the new claim?
```

If the existing census is sufficient, reuse it. New expensive processing must have a measured reason.

## Targeted single-PDF parallel recheck lane

The completed corpus census is the default source of page-level OCR/native-text evidence. Do not rerun it merely to obtain the same observations.

For targeted investigation of one problematic or high-value PDF, the repository now also provides:

- `.github/workflows/scj-principales-single-pdf-quality.yml`;
- `backend/scripts/scj_single_pdf_parallel_quality.py`;
- `backend/scripts/scj_ocr_jev_triage.py`;
- `backend/scripts/scj_ocr_visual_recheck.py`.

This lane freezes one exact source PDF once, then fans its pages across 20 isolated GitHub jobs. Page ownership is deterministic and disjoint (`page_index % shard_count`), every shard verifies the same source SHA-256, and aggregation fails closed on duplicate, missing, unexpected or wrong-source pages.

The OCR observation now retains confidence-distribution evidence in addition to mean confidence:

- word count;
- mean confidence;
- median confidence;
- p10 confidence;
- ratio of OCR words below the low-confidence threshold.

These tail metrics are **routing evidence**, not a replacement gold definition. The existing native-vs-rendered-OCR alignment policy remains the authority for `aligned` admission.

The targeted lane also records whether the PDF page exposes embedded image objects. Image presence alone does not prove OCR failure and does not automatically reject an otherwise aligned page. It becomes an escalation signal when combined with missing native text, disagreement, or other uncertainty.

Deterministic output routes are intentionally conservative:

```text
accept_candidate
sentinel
jev_review
visual_review
blocked
```

The first paid stage is optional JEV triage. JEV receives only deterministic metrics and bounded native/OCR disagreement excerpts. It runs in `shadow` mode: probabilities and recommendations are persisted, but JEV cannot overwrite source text or silently promote evidence.

A second optional stage visually rechecks JEV-selected pages with the configured DeepSeek visual model. The output records requested/returned model, routed provider metadata, reasoning setting, tokens, latency, cost, transcription and pairwise scores against native text and Tesseract. Pairwise consensus is evidence only; it does not become primary-source ground truth automatically.

Both provider-backed stages are `workflow_dispatch` opt-in and have explicit cost caps. Ordinary branch commits must not invoke them.

Targeted results are also durable in the configured S3-compatible store, independently of GitHub Artifact retention. The namespace is:

```text
benchmarks/scj-principales/single-pdf-quality/v1/
  <source_pdf_sha256>/
    <code_revision>/
      runs/github-<run_id>-attempt-<attempt>/
        deterministic/
        jev/
        deepseek/
```

Each populated stage contains its derived JSON/JSONL evidence plus an immutable `_MANIFEST.json` with payload hashes. The official source PDF is not duplicated there; `source_pdf_sha256` and the source corpus locator bind every result back to the immutable source. JEV/DeepSeek stages preserve their model/provider/configuration telemetry inside the published evidence.


## Corpus-wide two-pass Ling recovery lane

Pages already admitted by the completed census are not sent to a paid model again.
The recovery lane selects only `misaligned` and `no_native_text` pages from the
newest completed durable census generation. Low-information pages remain outside
the paid set unless a later explicit policy changes that decision.

`.github/workflows/scj-principales-ling-literal-ocr.yml` is manual-only. Before
any paid inference, it freezes a plan from the durable census and refuses to
continue if the target is no longer exactly 15,900 pages. The current frozen
baseline is 15,855 `misaligned` pages plus 45 `no_native_text` pages.

The frozen plan retains its historical `worker_count = 20` field in its hash so
existing page observations remain resumable. Execution concurrency is a separate
runtime setting: the current async worker has a global cap of 200 in-flight
OpenRouter requests in one GitHub job; it is not 200 requests per plan worker.
The scheduler processes one source PDF at a time and uses a bounded page window,
so it does not enqueue the 15,900 rendered pages into memory at once.

The workflow exposes two explicit corpus-wide stages. Pass 1 completes literal
transcription coverage across the frozen plan before Pass 2 begins. Pass 2 reads
each durable pass-1 transcription, renders the same immutable source page under
the pinned render profile, and adversarially checks the candidate against the
image. OpenRouter is pinned to NovitaAI with provider fallback disabled. The
image remains authoritative; model output never overwrites the official source
artifact. Each pass records its own PNG checksum and a decoded-pixel checksum;
the raw PNG byte checksum is observational because PDFium/Pillow can encode the
same page pixels differently across processes.

Evidence is resumable and immutable:

```text
benchmarks/scj-principales/ling-literal-ocr/v1/
  <plan-sha256>/
    inclusionai__ling-3.0-flash-vl/
      NovitaAI/
        pages/
          <document-id>/
            <page-index>/
              pass-1.json
              pass-2.json
        runs/
          github-<run-id>-attempt-<attempt>/
            summary.json
        _SUCCESS.json
```

Every pass records the source PDF SHA-256, rendered PNG SHA-256, page identity,
requested and returned model, requested and routed provider, OpenRouter
generation ID, token usage, latency, and exact OpenRouter `usage.cost` returned
with that same inference response, plus the transcription. Pass 2 additionally records the first-pass object key and
transcription SHA-256.

Completed pass-1 and pass-2 objects are skipped on retry. Pass 2 cannot start
unless every selected page has durable pass-1 evidence, and it resumes directly
for pages whose pass 1 exists but whose pass 2 is missing. This is the paid-run
idempotency boundary: retries must not silently pay again for already durable
work. The workflow pins the expected plan SHA on a resume dispatch, and worker
concurrency changes do not alter that frozen plan identity.

The aggregate fails closed unless every planned page has both passes from the
pinned provider. It verifies the decoded-pixel hashes when both pass records
contain them and reports legacy pairs that predate that checksum. Its final
report includes both the amount billed by the current GitHub run and the
cumulative cost of all persisted calls in the completed generation. The
workflow can run in inventory-only mode with no provider spend. For a paid
canary, `start_page_ordinal` plus `max_pages_per_worker` selects a bounded page
range without changing the frozen plan SHA; completed page/pass observations
are reused by later runs. A full run uses start ordinal `0` and
`max_pages_per_worker=0`. Any paid mode requires the explicit
`RUN_15900_PAGES` confirmation. The runtime async cap is separately authorized
and included in each worker summary; it must not be added to the frozen plan
hash.

The Ling request does not request a reasoning mode because the task is literal
transcription, not legal interpretation. This avoids making Novita support an
unnecessary parameter and keeps the output contract focused on visible text.
Identical OpenRouter retries also enable the 24-hour response cache so an
ambiguous transport retry can reuse the same inference instead of deliberately
paying for a second identical call.

## Running the Ling worker locally

The worker can read source PDFs from a local snapshot instead of downloading
them from object storage, while the durable census and the evidence output still
use the configured S3-compatible store. Point `JURISNEXO_LOCAL_CORPUS_ROOT` at a
directory that holds the PDFs by object key, using the same layout as the bucket:

```text
<root>/jurisdictions/do/scj/principales-sentencias/<prefix>/<sha>.pdf
```

`--corpus-root` overrides the environment variable per invocation. In local
mode `_source_pdf` reads the file, verifies its SHA-256 against the frozen
plan's `source_pdf_sha256`, and fails closed on checksum drift or a missing
object. A local snapshot must match the frozen census exactly; a partial or
stale snapshot must not be used to claim corpus coverage. Loading the local
environment (including the read-only S3 credentials) is typically done with:

```powershell
. .\scripts\local-env.ps1 -WithS3
```

Because a completed plan is fully resumable, re-running the worker against an
already finished plan restores durable observations (no model spend). Real
inference happens only for page/pass observations that are not yet durable.

## Current Ling generation status

The corpus-wide two-pass Ling generation is **complete at the runtime/provenance
level** for the frozen plan
`63f0ac73fa659a67bca79c20dbf1bde5e18a99f560c0bef6f50de10c51df8cc4`: all 15,900
pages have both passes, 31,800 model generations, 0 failed pages, and 0 retries,
at a cumulative generation cost of US$2.6055758134. Semantic fidelity is **not**
certified; independent visual adjudication of the adversarial-difference and
anomalous pages is still pending.

The full evidence, per-document coverage, cost, anomalies, and known limitations
(slow aggregate, rendering-gated concurrency, legacy render pairs) are frozen in
`docs/benchmarks/2026-10-03-scj-principales-ling-literal-ocr.md`. Read that
document for the current state instead of reconstructing it from expiring Actions
artifacts.

The worker exposes a global async in-flight cap (`--max-concurrent-requests`,
authorized separately from the frozen plan hash), separate Pass 1 / Pass 2
execution, and a local-corpus mode (`JURISNEXO_LOCAL_CORPUS_ROOT`) for offline
source reading. These are execution details; they do not change the frozen plan
identity or the evidence namespace.


