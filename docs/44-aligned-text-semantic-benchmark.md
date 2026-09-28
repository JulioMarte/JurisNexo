# Aligned-text semantic benchmark

Status: IMPLEMENTED — live provider evidence pending.

## Purpose

This benchmark answers a narrower question than the visual benchmark: given text that has already passed independent rendered-page OCR ↔ native-text admission, how accurately and cheaply can a model extract explicit legal facts in one call?

It does **not** claim to measure whole-judgment understanding. Whole-judgment extraction remains blocked on trustworthy decision segmentation and a document-level gold set.

## Gold authority

The input pages come from the same SCJ Principales corpus admission path used by the visual benchmark. A page is eligible only when its native PDF text agrees with independent Tesseract OCR of a rendered page under the existing alignment thresholds. The manifest freezes object key, page index and reference SHA.

The semantic oracle is deterministic and independent of the model under test. `jurisnexo.normalization.legal_fact_benchmark` extracts the currently measurable explicit categories from the admitted reference text. Model output never becomes gold.

Current categories: dates, amounts, articles, laws, decrees, resolutions, RNC, cédulas, matrículas, cadastral references, case identifiers and SCJ/TC citations.

This oracle is intentionally bounded. A high score means the model recovered the explicit facts recognized by this versioned detector; it does not mean every legally important proposition on the page was understood.

## Metrics

Every run preserves per-page expected and predicted values, exact multiset matches, misses, hallucinations, precision, recall and F1, plus provider/model, routed provider, latency, input/output/reasoning/total tokens and observed provider cost.

Aggregate evidence includes pages with any miss, pages with any hallucination, p50/p95 latency, total cost and observed cost per 1,000 completed pages. Duplicate values count independently so a model cannot satisfy two occurrences by returning one value.

## Execution ladder

The workflow is manual-only and therefore cannot spend provider money on ordinary pushes or pull requests.

1. 10-page smoke: validate schema/provider behavior and obvious prompt failures.
2. 50-page calibration: compare DeepSeek V4.1 Flash high, GPT-6 Luna high, and Ling 3 Flash low/medium/high.
3. 290-page benchmark: run only after calibration evidence identifies the configurations worth paying to compare. The workflow supports 290 pages but dispatching it is an explicit operator decision.

The comparison report is descriptive. Promotion policy must be decided separately; benchmark code must not silently select a winner.

## Separation from JEV

JEV remains a classification/verification system, not a direct competitor in this extraction benchmark. A later benchmark should measure JEV on bounded candidate-first decisions such as whether an extracted value is supported, contradicted or unsupported by supplied evidence, and on deterministic page-routing labels where an independent oracle exists.

Do not manufacture a subjective `needs_deep_processing` gold label merely to benchmark routing. Until that label has an independent contract, JEV routing stays a separate experiment.

## Whole-judgment benchmark

After normalization can reliably segment individual judgments, build a document-level benchmark with document-isolated calibration/holdout/adversarial splits. The experiment should compare one-call whole-judgment structured extraction against any staged JEV + larger-model pipeline on final correctness, critical legal loss, hallucination, latency and cost per correctly processed judgment.

Page-level results must never be reported as proof of whole-judgment understanding.
