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