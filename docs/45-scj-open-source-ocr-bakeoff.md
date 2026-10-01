# SCJ Principales open-source OCR bakeoff

## Purpose

This benchmark selects a **base OCR engine** for SCJ `principales-sentencias`
using JurisNexo evidence rather than vendor benchmarks.

The selected engine is intended to produce the first independent visual
transcription for the 36-PDF corpus. It does not become primary-source truth and
must not silently overwrite official PDF evidence.

## GitHub Actions operating envelope

The benchmark is intentionally designed for standard public-repository
`ubuntu-24.04` runners:

- 4 CPU;
- 16 GB RAM;
- 14 GB SSD;
- GitHub Free concurrency ceiling: 20 standard hosted jobs;
- this workflow uses at most 6 OCR engine jobs in parallel.

JurisNexo is currently public, so standard hosted-runner usage is free and
unlimited under GitHub's current public-repository policy. The 20-job
concurrency limit still applies.

Sources:

- https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- https://docs.github.com/en/actions/reference/limits

The workflow must remain usable without GPU or paid OCR services. GPU-only
systems can be studied separately but cannot win the **default GitHub Actions
base OCR** role unless the execution contract changes deliberately.

## Engines in the primary bakeoff

The active reproducible matrix contains:

| Engine | Pinned package/runtime | Why included |
| --- | --- | --- |
| Tesseract | Ubuntu Tesseract 5 package, `spa+eng` | Current independent OCR baseline |
| PaddleOCR | `paddleocr==3.7.0`, `paddlepaddle==3.2.2` | PP-OCRv6 generation; modern Latin multilingual OCR with CPU support |
| RapidOCR | `rapidocr==3.9.2` + ONNX Runtime | Lightweight offline Paddle-derived inference path |

EasyOCR, docTR, and Surya were evaluated during the exploratory smoke phase and
are retained as historical evidence, but they are not active candidates in the current
base-OCR race. Surya is explicitly parked for now rather than optimized further.

Every active job records `pip freeze`, runtime version, page failures, wall time, mean
latency, and peak resident memory.

### Parked Surya caveat

Current Surya OCR 2 is a VLM-backed document OCR system. On CPU it requires a
`llama-server` runtime. The exploratory workflow used `llama.cpp` release `v0.4.1` rather
than following its moving default branch. Its code is Apache-2.0, while model weights
carry Datalab's model license conditions. It is not included in the active three-engine matrix. Resource use and licensing remain part of any future reconsideration.

Reference:

- https://github.com/datalab-to/surya

## Deliberately not treated as separate base engines

### OCRmyPDF

Useful preprocessing/orchestration around OCR, especially Tesseract, but not an
independent recognition engine. If Tesseract remains competitive, preprocessing
variants such as deskew/clean/rotate should be a second ablation rather than
misrepresented as another recognizer.

### Kraken and Calamari

Both remain relevant for historical, degraded, line-oriented, or trainable OCR.
They are not in the first general-page bakeoff because their strongest value is
specialized historical recognition and model training rather than an
out-of-the-box modern Spanish legal-page baseline. They should be added to a
historical-bulletin benchmark when that corpus becomes the target.

References:

- https://github.com/mittagessen/kraken
- https://github.com/Calamari-OCR/calamari

### Kraken 7.1

Kraken is actively maintained and its 7.1 release added multilingual PP-OCRv6-derived
recognition models optimized for historical handwritten and machine-printed material.
That makes it a serious **historical-corpus** candidate, but not yet an apples-to-apples
base engine for this first modern SCJ page bakeoff: Kraken is line/segmentation oriented
and requires an explicit recognition model choice. We should test it in the hard/rescue
phase if the failed-page strata contain enough degraded/historical typography to justify
that specialized path.

Reference:

- https://github.com/mittagessen/kraken/releases

### MMOCR

MMOCR remains a broad research toolbox with many detector/recognizer combinations rather
than one canonical production OCR configuration. Its current public installation path
still carries the OpenMMLab stack (PyTorch + MMEngine + MMCV + MMDetection) and its model
choice is itself an experiment. Adding one arbitrary MMOCR detector/recognizer pair would
not mean that "MMOCR" had been fairly tested. It is therefore catalogued but not placed
in the first CPU matrix. If the three active primary engines fail to separate clearly, select a
specific MMOCR pair and benchmark that exact model/configuration as a named candidate.

Reference:

- https://github.com/open-mmlab/mmocr

### Open-weight page VLM OCR systems

Projects such as olmOCR and PaddleOCR-VL are relevant to document conversion, but their
normal local inference path is GPU-oriented and materially different from the standard
4-CPU/16-GB GitHub runner contract. They belong in a separate **open-weight VLM OCR**
league, not in the default CPU-base-OCR election. Surya is the exception we deliberately
probe because it exposes a documented llama.cpp CPU path; the smoke run will determine
whether that path is operationally realistic here.

Reference:

- https://github.com/allenai/olmocr
- https://github.com/PaddlePaddle/PaddleOCR

### OCRopus and stale/unmaintained OCR projects

Do not add a project merely to make the engine count larger. A candidate must
have a maintainable installation path, a usable pretrained model for the target
script/language, and a realistic path to the current runner envelope.

## Why the old 290-page gold cannot choose the winner by itself

The 2026-09-27 visual benchmark contains 290 high-quality pages. They are useful,
but their admission contract required:

```text
native PDF text
    agrees with
Tesseract reading of the rendered page
```

That makes the sample **selection-biased in Tesseract's favor**.

Therefore it is a clean/control benchmark, not the final election.

The scorer embeds this warning and refuses to mark any engine as production
winner based only on this stage.

## Stage A — clean/control fidelity

All engines receive the exact same rendered PNGs and frozen references.

Metrics:

- page failure rate;
- character error rate (CER);
- word error rate (WER);
- token content recall and precision;
- token-order preservation;
- aggregate legal-critical recall;
- latency/page;
- peak memory.

Legal-critical matching uses the existing JurisNexo independent scorer rather
than engine-specific confidence.

The clean-stage hard floor is:

```text
failure rate <= 1%
aggregate legal-critical recall >= 99.5%
```

This is a filter, not a weighted score.

Among surviving engines, WER/CER and resource cost are reported. The order is
diagnostic only.

## Stage B — hard/rescue benchmark

This stage is mandatory before promotion.

It must draw from the 15,855 relevant pages that failed the original
native-text/Tesseract alignment gate. These are precisely the pages on which a
replacement base OCR must create value.

The Stage B reference must be independent of **every candidate OCR engine**.
Native PDF text cannot automatically be called gold on these pages because
native/OCR disagreement is why they entered the set.

The target design is:

1. stratified sample across all 36 PDFs and census failure reasons;
2. preserve exact rendered image, native text, existing Tesseract observation,
   and provenance;
3. run every candidate engine without exposing competing outputs to it;
4. adjudicate reference text independently;
5. lock the adjudicated reference before scoring engines;
6. retain disagreements and ambiguous pages instead of forcing false gold.

A pragmatic adjudication lane can use high-quality multimodal models already
benchmarked by JurisNexo (DeepSeek V4.1 Flash and GPT-6 Luna) as independent
observers, followed by fail-closed consensus rules and targeted manual review
for residual conflicts. Model agreement is evidence, not primary-source truth.

Stage B should contain at least 100 adjudicated hard pages before an engine is
promoted, and preferably 300 distributed across the 36 PDFs.

## Promotion rule

The production candidate must satisfy all of the following:

1. <=1% runtime/page failures on the clean benchmark;
2. >=99.5% aggregate legal-critical recall on clean pages;
3. materially better recovery on independently adjudicated hard pages than the
   current Tesseract baseline;
4. no statistically or practically meaningful regression in legal identifiers,
   dates, article/law numbers, monetary amounts, citations, or dispositive text;
5. stable CPU execution inside 4 CPU / 16 GB / 14 GB runners;
6. acceptable throughput for a 29,811-page corpus;
7. compatible code/model licensing for JurisNexo's intended deployment;
8. exact engine/model/version/configuration frozen in evidence.

If quality is effectively tied, prefer the simpler and faster engine. Complexity
must earn itself through measured recovery.

## Workflow

`.github/workflows/scj-open-source-ocr-bakeoff.yml`

PR runs use a 12-page smoke to prove installation, output shape, scoring, and
resource compatibility without wasting runner time.

Manual dispatch supports 12, 60, 120, or 290 clean/control pages. A full 290-page
run should only be executed after every engine passes its smoke.

Artifacts:

```text
ocr-bakeoff-prepared-<run>-<attempt>
ocr-bakeoff-<engine>-<run>-<attempt>
ocr-bakeoff-aggregate-<run>-<attempt>
```

Engine artifacts are temporary diagnostics. The aggregate report or a frozen
result document should be committed/published when a decision is made.

## Corpus-wide rollout after a winner exists

Do not OCR all 29,811 pages merely because a benchmark job is green.

First freeze:

- winning engine + version/model hashes;
- render DPI/scale;
- language/configuration;
- deterministic page ownership;
- output/provenance schema;
- retry/checkpoint contract;
- expected runtime/resource envelope.

Then reuse the existing 20-way concurrency discipline. One safe shape is up to
20 independent jobs, each owning a disjoint deterministic subset of pages, with
aggregation that fails on missing, duplicate, unexpected, or wrong-source page
identities.

The previously stored Tesseract observations remain evidence. A new winning OCR
observation should be stored beside them, not overwrite them.


## Portable hard/rescue harness: local and GitHub Actions

The 500-page hard/rescue experiment is intentionally **not** a GitHub-Actions-only
implementation. GitHub Actions is an orchestration layer over the same Python
contracts that can be executed on a local machine.

Canonical entry points:

```text
benchmark/normalization/prepare_scj_ocr_hard_rescue.py
benchmark/normalization/run_open_source_ocr_engine.py
benchmark/normalization/merge_scj_ocr_hard_rescue_shards.py
benchmark/normalization/aggregate_scj_ocr_hard_rescue.py
benchmark/normalization/run_scj_ocr_hard_rescue_local.sh
.github/workflows/scj-ocr-hard-rescue-500.yml
```

The local wrapper supports `prepare`, `ocr`, `aggregate`, and `all`.
Preparation needs the same `JURISNEXO_S3_*` credentials as CI because the
canonical census evidence lives in object storage. The OCR and aggregate phases
can then run entirely from the frozen local work directory.

A local machine must provide the three candidate runtimes:

- Tesseract 5 with Spanish and English language data;
- RapidOCR 3.9.2 + ONNX Runtime;
- PaddleOCR 3.7.0 + PaddlePaddle 3.2.2.

The default local wrapper runs shards sequentially. That is deliberate: laptops
vary widely in CPU/RAM and blindly launching the GitHub 15-job topology locally
can cause memory pressure or thermal throttling. Parallel local orchestration may
be added only with an explicit resource limit.

Example after installing dependencies and exporting S3 credentials:

```bash
OCR_HARD_PAGE_LIMIT=60 benchmark/normalization/run_scj_ocr_hard_rescue_local.sh all
OCR_HARD_PAGE_LIMIT=500 benchmark/normalization/run_scj_ocr_hard_rescue_local.sh all
```

Use 60 pages as a local installation/thermal smoke before spending time on 500.

### Evidence identity contract

Every candidate observation is self-identifying. `predictions.jsonl` records:

```text
observation_id
sample_id
engine
engine_version
engine_config_id
source_pdf_sha256
page_index
image_sha256
text
elapsed_ms
error
```

`observation_id` is deterministic over engine identity/version/configuration and
the exact source/render identity. It therefore changes if the engine,
configuration, source PDF, page, or rendered image changes.

Blind adjudication does not discard that provenance. Each `candidate-A/B/C.json`
contains the stable `observation_id`, source/page/image identity, and blind
label, while deliberately withholding the engine name. The separately stored
`candidate-reveal.json` maps each blind label to engine, version,
configuration ID, and observation ID after adjudication is frozen.

The aggregator rejects engine-label mismatches and source/page/image provenance
mismatches. The portable shard merger rejects missing counts, duplicate sample
IDs, duplicate observation IDs, malformed observation IDs, and mixed-engine
shards.

This gives local runs and GitHub Actions the same evidence semantics rather than
two subtly different benchmarks.
