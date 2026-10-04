# SCJ hard-page OCR engine comparison — 2026-10-01

Status: BENCHMARK EVIDENCE + PROVISIONAL ENGINE DECISION. This selects the base
OCR engine for the new SCJ normalization lane. It is **not** a semantic claim
that either engine is correct on a given page, and it does not change any frozen
census generation.

## Purpose

Choose a base OCR engine for the hard SCJ Principales pages (the census
`misaligned` / `no_native_text` strata) instead of defaulting to Tesseract.

## Corpus and method

The `scj-ocr-hard-rescue-500` lane sampled 500 pages across the 36 SCJ
Principales PDFs from the census failure strata and rendered every page once to
the same PNG. Each engine then produced one text observation per page with the
same input images.

Engines (as run by workflow run `36890735401`, 2026-10-01):

| Engine | Version | Configuration |
| --- | --- | --- |
| Tesseract | `5.3.4` | `lang=spa+eng`, `psm=6` |
| RapidOCR | ONNX (PP-OCR family) | library defaults |
| PaddleOCR | `3.7.0` (PaddlePaddle 3.2.2) | `lang=es`, orientation/unwarping off |

## Provenance

- Workflow: `.github/workflows/scj-ocr-hard-rescue-500.yml`
- Run: `36890735401` (2026-10-01)
- Artifacts: `ocr-hard-{tesseract,rapidocr,paddleocr}-shard-{0..4}-36890735401`,
  `ocr-hard-candidate-reveal-36890735401`, `ocr-hard-prepared-36890735401`
- Observations: `predictions.jsonl` per shard (`observation_id`, `source_pdf_sha256`,
  `page_index`, `image_sha256`, `text`, `elapsed_ms`, `error`).

## Results (500 pages per engine)

| Metric | Tesseract | RapidOCR | PaddleOCR |
| --- | ---: | ---: | ---: |
| Pages | 500 | 500 | 500 |
| Failed pages | 0 | 0 | 0 |
| Mean wall seconds/page | 2.63 | 2.38 | 15.57 |
| Peak RSS (MiB) | 28 | 594 | 2871 |

Pairwise mean text similarity on the same page (whitespace-normalized):

| Pair | Mean | Median | Exact matches |
| --- | ---: | ---: | ---: |
| PaddleOCR ~ RapidOCR | 0.9799 | 0.9969 | 79 / 500 |
| PaddleOCR ~ Tesseract | 0.9567 | 0.9872 | 24 / 500 |
| RapidOCR ~ Tesseract | 0.9385 | 0.9819 | 18 / 500 |

Per-page centrality (which engine is closest to the other two): PaddleOCR
321/500, RapidOCR 137/500, Tesseract 42/500.

## Interpretation (brutally honest)

- **Tesseract is the outlier.** The two PP-OCR-family engines agree with each
  other (0.98) far more than either agrees with Tesseract (~0.94–0.96), and
  Tesseract is the least central engine.
- **Agreement is not accuracy.** This run has no adjudicated gold reference, and
  RapidOCR uses PP-OCR-derived models, so PaddleOCR↔RapidOCR agreement is partly
  **correlated lineage**, not independent evidence of being more correct.
  Independent confirmation requires the blind adjudication in
  `docs/45-scj-open-source-ocr-bakeoff.md` (Stage B, >=100 adjudicated hard pages).
- **Cost matters.** PaddleOCR is ~7x slower and uses ~2.9 GiB RSS per worker;
  RapidOCR delivers the same family of results at ~2.4 s/page and ~0.6 GiB.

## Decision

Adopt **RapidOCR** as the base OCR engine for the new SCJ normalization lane,
**provisionally**, pending independent Stage B adjudication. Rationale: it is in
the same PP-OCR family that dominates this comparison, at ~1/7 the cost of
PaddleOCR and far above Tesseract's agreement/centrality.

- PaddleOCR: rejected as the default base (latency/RSS), retained as a research
  candidate.
- Tesseract: retained as the historical census baseline. Existing frozen
  Tesseract census evidence is **not** recomputed or reinterpreted by this
  decision.
- This is a routing/base-engine decision, not a legal-evidence conclusion.

## Reproduction

```bash
gh run download 36890735401 --pattern "ocr-hard-*-shard-*" -D shards
gh run download 36890735401 -n ocr-hard-candidate-reveal-36890735401 -D shards
# merge predictions.jsonl per engine and compute pairwise whitespace-normalized
# similarity over shared sample_ids (method in this document).
```

## Known limitations

- No independent adjudicated gold; metrics are agreement/centrality only.
- Tesseract version differs from the earlier frozen census (`5.3.4` here).
- RapidOCR reports `engine_version=unknown` in this run; the library is pinned
  (`rapidocr==3.9.2`) in `docs/45-scj-open-source-ocr-bakeoff.md`.
