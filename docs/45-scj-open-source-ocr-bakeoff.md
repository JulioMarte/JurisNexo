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

The initial reproducible matrix contains:

| Engine | Pinned package/runtime | Why included |
| --- | --- | --- |
| Tesseract | Ubuntu Tesseract 5 package, `spa+eng` | Current independent OCR baseline |
| PaddleOCR | `paddleocr==3.7.0`, `paddlepaddle==3.2.2` | PP-OCRv6 generation; modern Latin multilingual OCR with CPU support |
| RapidOCR | `rapidocr==3.9.2` + ONNX Runtime | Lightweight offline Paddle-derived inference path |
| EasyOCR | `easyocr==1.7.2`, CPU PyTorch | Mature multilingual neural OCR baseline |
| docTR | `python-doctr==1.1.0`, CPU PyTorch | General document detection + recognition baseline |
| Surya OCR 2 | `surya-ocr==0.22.1` + CPU `llama-server` | Strong modern document OCR, but materially heavier than classical OCR |

Every job records `pip freeze`, runtime version, page failures, wall time, mean
latency, and peak resident memory.

### Surya caveat

Current Surya OCR 2 is a VLM-backed document OCR system. On CPU it requires a
`llama-server` runtime. The benchmark pins `llama.cpp` release `v0.5.0` rather
than following its moving default branch. Its code is Apache-2.0, while model weights
carry Datalab's model license conditions. It is included because its quality may
justify the additional complexity, but resource use and licensing are part of
the production decision rather than afterthoughts.

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
