# SCJ Principales text legal-fact extraction benchmark v1

Status: IMPLEMENTED BENCHMARK CONTRACT; LIVE MODEL RESULTS PENDING.

## Question

Given text that has already passed the independent native-text ↔ rendered-page OCR admission gate, how reliably and cheaply can one model call extract explicit legal facts without inventing values?

This benchmark is deliberately separate from:

- visual transcription quality;
- JEV classification/verification;
- whole-decision semantic extraction.

A page-level result must not be reported as whole-sentence or whole-decision understanding.

## Frozen corpus

The benchmark reuses the frozen prepared artifact from successful visual benchmark run `36294070183` at commit `bb8226b7c42751c9167546b6f3aa67cbe466b3df`. The exact artifact ID, name and digest are pinned in `benchmark/normalization/scj_text_legal_fact_benchmark_v1.json`.

That run audited 600 real SCJ `principales-sentencias` pages. A page entered the pool only when native PDF text and an independent Tesseract reading of the rendered page satisfied the existing strict alignment policy. Exactly 290 pages were admitted.

The prepared visual artifact freezes, for each admitted page:

- source object key and source PDF SHA-256;
- page index;
- native-text SHA-256;
- rendered-image SHA-256;
- visual-OCR SHA-256;
- alignment metrics;
- admitted native text.

The text benchmark verifies every native-text SHA before inference. `benchmark/normalization/legal_fact_gold_v1.py` is a benchmark-owned deterministic oracle that extracts the exact spans to score; changing that oracle requires a benchmark version change.

The model never receives gold values. It receives only the admitted page text and the output schema.

## Split discipline

The corpus is source-separated:

- calibration: 50 pages from 3 PDFs;
- holdout: 240 pages from 24 different PDFs.

No source PDF appears in both splits. The first 10 calibration pages form the cheap smoke phase. Reasoning/profile selection may use calibration. Comparable quality claims should emphasize the untouched holdout after configuration selection.

## Extraction contract

One model call returns arrays for:

- dates;
- money;
- articles;
- laws;
- decrees;
- resolutions;
- Gaceta Oficial mentions;
- RNC;
- cédulas;
- matrículas;
- cadastral references;
- case/sentence/expediente identifiers;
- SCJ/TC citations.

The v1 oracle intentionally tracks explicit, mechanically identifiable values. It does not claim to cover parties, holdings, issues, procedural posture, disposition or legal propositions. Those require decision-level gold after segmentation is trustworthy.

## Metrics

Every profile records independently:

- provider/schema completion rate;
- exact-page rate;
- micro precision, recall and F1;
- false positives (invented values);
- false negatives (omitted values);
- the same counts and metrics per field;
- median and p95 latency;
- input/output/thinking/total tokens when reported;
- observed provider cost;
- cost per 1,000 completed pages;
- cost per exact page.

The first live executions establish baselines. Semantic thresholds must not be invented before evidence exists.

## CI phases

`.github/workflows/scj-principales-text-legal-fact-benchmark.yml` has two distinct modes:

1. PR synchronization runs only offline contract tests and spends no provider credits.
2. `workflow_dispatch` runs paid benchmarks explicitly.

Manual phases are:

- `smoke`: first 10 calibration pages;
- `calibration`: all 50 calibration pages;
- `full`: all 290 pages, while reporting calibration and holdout separately.

Available profiles are `deepseek-high`, `luna-high`, `ling-low`, `ling-medium`, and `ling-high`. A full run requires explicitly naming the desired finalists rather than silently running every configuration.

## JEV boundary

JEV is not a competitor in this extraction benchmark. JEV remains appropriate for typed classification and candidate verification:

```text
deterministic facts / candidates
    -> JEV classify or verify
    -> code owns threshold, routing and persistence
    -> stronger generative model only where needed
```

A later experiment may compare the total cost/quality of that funnel against "send every normalized decision to DeepSeek/Luna/Ling", but only after decision boundaries and decision-level gold exist.

## Retention caveat

The source prepared artifact currently expires on 2026-12-26 under GitHub Actions retention. Before that date, the reduced text-only corpus should be promoted to a durable benchmark snapshot (repository or benchmark object storage) without changing page identities or hashes. Until that promotion happens, the benchmark contract is implemented and reproducible from the pinned artifact, but not indefinitely self-contained.
