# Normalization control plane — implementation status

Status: CURRENT IMPLEMENTATION EVIDENCE INDEX.

This document tracks implementation and proof status for the V3 normalization control plane. It does not replace docs 39-41; it prevents implementation claims from drifting beyond the evidence that actually exists.

## Status vocabulary

- IMPLEMENTED: code/persistence exists.
- PROVEN: intended evidence has run successfully in CI or an integration/benchmark lane.
- PENDING EVIDENCE: implementation exists but the required live/semantic/operational proof has not passed yet.
- OPEN: design/provider/promotion decision intentionally remains unresolved.

## Workstream status

| Workstream | Implementation | Evidence status |
| --- | --- | --- |
| 0. Substrate/provenance | IMPLEMENTED | PostgreSQL integration, baseline equivalence and lineage invariants exist; exact-head CI remains the merge authority |
| 1. Docling + Tika spike | IMPLEMENTED | Engine spike covers born-digital/scanned/mixed PDF, DOCX, RTF, HTML and corrupt PDF |
| 2. Replaceability boundaries | IMPLEMENTED | Architecture fitness + protocol/unit proof |
| 3. Gold Set/contracts | IMPLEMENTED IN PART | Generic fixtures plus legal-critical CER/WER/token/order scoring, an extended Dominican legal-identifier detector and document-level worst-page/critical-loss scoring exist. A bounded real-source SCJ Principales judgment-page calibration/holdout exists for the born-digital PDF-aware route (6 documents × 2 pages); a stratified/adversarial gold set remains PENDING EVIDENCE |
| 4. Planner/durable execution | IMPLEMENTED | deterministic planning, idempotency, durable checkpoints, retry classes, circuit breaker and interrupted-run resume exist |
| 5. Docling/Tika production adapters | IMPLEMENTED | object-storage derivatives, lineage, PDF-aware OCR, language configuration and optional isolated Docling subprocess exist |
| 6. Deterministic QA | IMPLEMENTED | text health/legal-critical signals exist; page/region OCR behavior uses Docling PDF-aware OCR; semantic quality thresholds remain benchmark-owned |
| 7. JEV shadow | PROVEN IN BOUNDED LIVE BENCHMARK | DecisionProvider + OpenRouter decisions adapter + DecisionTextQualityJudge + shadow persistence exist. A 4-source Principales live benchmark passed with 0 calibration/holdout false negatives and false positives on the bounded corruption task, Brier ≈ 0.0153, claim argmax accuracy 1.0, 373 ms quality-batch latency and total observed OpenRouter cost US$0.000660282. Promotion remains blocked by insufficient sample size. |
| 8. Visual verification | IMPLEMENTED | provider-neutral verifier, DeepSeek V4.1 Flash visual adapter path, correction proposals and bounded two-call smoke exist. The bounded live smoke could not obtain a structured visual response and is NOT PROVEN: the model returned reasoning prose instead of the requested JSON object (see provider-capability finding) |
| 9. Resolved views/sentinel/workspace | IMPLEMENTED | evidence/search separation, stable workspace, deterministic sentinel sampling and read-only GC audit exist |
| 10. Reconciliation | IMPLEMENTED | fail-closed plan/DB/lineage/storage/quality reconciliation and immutable normalization manifest exist; PostgreSQL + S3-compatible integration proof exists |
| 11. SCJ Principales rollout | IMPLEMENTED IN PART | real-source canary/smoke infrastructure exists and the bounded born-digital PDF-aware production holdout passes on real judgment pages with document-level gates (run `35815391234`: holdout WER ≈0.020, content recall ≈0.990 / precision ≈0.999, order-preservation ≈0.986, legal-critical recall 1.0, 0/3 holdout documents with critical loss); adversarial sample, broader canary/full rollout and OOD promotion evidence remain PENDING |
| 12. Second source | PROVEN | Official TC/0001/26 passed the same Tika + Docling normalization core; source-specific logic remains confined to acquisition |

## Current engine policy

- Docling is the primary structural normalizer.
- Apache Tika is format/metadata/fallback support, not canonical legal text.
- PDF OCR uses Docling PDF-aware layout-region routing so native PDF cells are not blindly rasterized.
- OCR languages are source/jurisdiction configuration, not normalization-core identity. Dominican SCJ/TC canaries use `iso:es`.
- The optional isolated Docling worker enforces timeout, source/output byte limits, temp cleanup and strips DB/S3/OpenRouter credentials from the parser subprocess. Container/job isolation remains responsible for kernel/network-level sandboxing.

## Bounded SCJ Principales benchmark evidence

- The born-digital Principales production route (extract the native vector-text page, run `PDF_AWARE_LAYOUT_REGIONS`, resolve evidence text) was measured on real judgment pages, not front matter.
- Live run `35811462583` (head `cc6eb85`): 6 judgment pages across 6 volumes, split calibration/holdout by case order. Holdout mean WER ≈0.022, token content recall ≈0.993, precision ≈0.998, mean order-preservation ≈0.987 and legal-critical recall 1.0; the gate passed.
- Live run `35815391234` (head `0c16144`): benchmark v2 samples 2 spread pages per document (6 documents, 12 pages) and gates on document-level critical loss. Holdout mean WER ≈0.020, content recall ≈0.990, precision ≈0.999, order-preservation ≈0.986, legal-critical recall 1.0 and 0/3 holdout documents with critical loss; the gate passed. Sampling spread pages reduces (but does not remove) the earlier "first clean page" selection bias.
- The full-page OCR fallback diagnostic on the same pages did not pass its thresholds: holdout WER ≈0.120, content recall ≈0.924, legal-critical recall ≈0.857. This supports keeping born-digital native/PDF-aware extraction ahead of rasterizing native text; full-page OCR remains diagnostic for scanned material.
- `score_text_fidelity` reports `token_order_preservation` (longest-common-subsequence ratio of content tokens) so reordering can be distinguished from content loss or edits. `score_document_fidelity` aggregates page scores into worst-page WER and any-critical-loss so a good page average cannot hide a damaged dispositive identifier.
- The legal-critical detector now covers dates, money, articles, laws, decrees, resolutions, `Gaceta Oficial`, RNC, cédula, matrícula, cadastre, case/expediente and citation patterns. It remains an incremental detector, so `legal-critical recall = 1.0` means "all spans the current detector recognises", not "every legally important datum".

### Live provider-capability finding (DeepSeek structured output)

- The bounded JEV + DeepSeek smoke (run `35815391187`) and the two-call visual smoke (run `35815391241`) both failed to obtain a structured response from `deepseek/deepseek-v4.1-flash` through OpenRouter `/chat/completions`. The model returned reasoning prose in `message.content` instead of the requested JSON object, so JSON-schema structured output could not be parsed. The serialized payload records `runtime_status = provider_structured_output_failed` and the raw preview.
- The JEV path is unaffected: the same run resolved `typesafe/jev-1.13-20260917` through `/api/alpha/decisions`, produced typed Choice/Noul/Score answers and cost US$0.0000794. On the sampled judged pages JEV reported high uncertainty (`legal_critical_damage ≈0.48`, `needs_visual_review ≈0.82`), i.e. it would route to review.
- Consequence: DeepSeek structured-output and visual-verification capability is **not established** in this configuration. Do not claim DeepSeek challenger or visual verification as proven; a provider/model/parameter change is required and must be re-benchmarked. Failed calls are recorded as evidence rather than crashing the lane silently.

### Benchmark-validity correction

- An earlier PDF-policy holdout run selected the first page with ≥800 native characters. In these compiled volumes that page is cover/credits/ISBN/library catalog-card front matter or a table of contents, so the earlier `mean_word_error_rate ≈0.575` failure measured block ordering of non-legal front matter, not normalization of legal text. That run is retained as historical context, not as a quality verdict on the route.
- Both holdout lanes now select pages that expose real adjudicative structure (reject ISBN/catalog/`ÍNDICE` front matter; require adjudicative markers) through `benchmark/normalization/scj_page_selection.py`, and export reference/candidate text for direct reading-order adjudication. The visual/JEV smokes reuse the same selector.
- Still open: a stratified/adversarial gold set (tables, footnotes, dissents, signatures, mixed/scan pages, older/failed layouts), per-document coverage of every page rather than a spread sample, and a human-reviewed subset for legal-critical verification.

## Current model policy

### JEV

See `43-jev-system-one-engineering-guidelines.md` for the canonical System One design/calibration contract.

- JEV is a System One decisions model.
- Runtime endpoint: OpenRouter `/api/alpha/decisions`.
- JurisNexo exposes it through `DecisionProvider`.
- Current normalization questions use typed Choice/Noul/Score decisions rather than free-form generation.
- Context batching targets ~24k estimated tokens inside the 32k model window, reserving headroom for state/question serialization instead of filling the hard limit.
- Oversized records fail closed; JurisNexo does not silently truncate a decision record to make it fit.
- Quality routing and claim/evidence verification are treated as different capabilities: JEV cannot infer that a plausible identifier is wrong unless the reference evidence is provided.
- Routing thresholds live in a provider-independent policy and remain calibration-owned rather than hard-coded as a property of JEV.
- JEV remains shadow/advisory. Live run 35763120423 resolved to model `typesafe/jev-1.13-20260917`; the quality batch used 8,905 input tokens / 9,677 total tokens, stayed inside the 24k target budget, and cost US$0.00037401. Evidence-backed claim verification cost US$0.000286272. The benchmark selected a candidate material-error threshold of 0.75 with zero observed false negatives/positives in its tiny calibration and holdout splits, but `promotion_assessment.eligible=false` because each split had only two positive and two negative quality cases.

### DeepSeek

- Model: `deepseek/deepseek-v4.1-flash`.
- Default reasoning effort: `high`.
- `xhigh` is comparison-only until measured evidence justifies a policy change.
- Benchmarks preserve requested/effective model, token usage, reasoning tokens, latency and provider-reported cost where available.
- The same model can accept images and is the current bounded visual-verifier candidate; this does not make it legal ground truth.
- Structured-output capability is NOT established for the chat-completions path in this configuration: the model returned reasoning prose instead of the JSON object requested by `response_format: json_schema` (see the provider-capability finding). The adapter keeps parsing tolerant of content-part lists, code fences and surrounding prose, but it cannot invent a JSON object the provider did not return. The model/parameter/provider choice must be revisited before claiming DeepSeek challenger or visual verification.

## Hard claims that are currently supported

- acquisition and normalization are separate;
- normalization core does not own source discovery;
- preserved bytes/hash remain source authority;
- derived artifacts and provenance are durable and append-oriented;
- cross-scope normalization lineage is rejected;
- lineage cycles are rejected, including concurrent opposite-edge attempts;
- equivalent resolved evidence artifacts can be reused without confusing them with structural Docling JSON;
- interrupted running items can be resumed against the same manifest/pipeline/config identity;
- terminal success is gated behind reconciliation and manifest publication;
- source adapters do not own parser/OCR engines;
- downstream workspace APIs do not expose parser/provider internals;
- the born-digital PDF-aware Principales route passed a bounded real judgment-page calibration/holdout while full-page OCR did not.

## Claims that must NOT be made yet

Do not claim any of the following until the corresponding evidence has passed:

- all SCJ Principales are normalized;
- OCR quality is calibrated for the full Principales distribution;
- the legal-critical detector covers every legally important datum;
- the born-digital Principales route is validated beyond the bounded spread sample;
- JEV thresholds are production-ready;
- JEV has a production-representative acceptable false-negative rate beyond the bounded 4-source smoke;
- live JEV/visual observations are persisted in a real provider run (the persistence contract is proven with provider doubles and real PostgreSQL);
- DeepSeek structured output or visual verification works (the bounded smoke recorded a provider structured-output failure);
- visual-verifier false-correction rate is acceptable beyond the bounded smoke;
- the worker is a complete security sandbox;
- the full Principales Definition of Done in doc 41 is complete.

## Remaining closure sequence

1. obtain exact-head deterministic CI green;
2. build a stratified/adversarial Principales gold set (tables, footnotes, dissents, signatures, mixed/scan and older/failed layouts) and cover every page of selected documents rather than a spread sample;
3. expand JEV calibration/holdout to promotion-sized source-verified samples while preserving split independence;
4. resolve the DeepSeek structured-output capability gap (model/parameters/provider) and re-run one explicitly labeled JEV + DeepSeek challenger smoke and one two-call visual verifier smoke; the current bounded smokes recorded `provider_structured_output_failed`;
5. analyze model probabilities, false negatives, calibration, token/cost/latency evidence and durable observation lineage (the persistence contract is already proven with provider doubles and real PostgreSQL);
6. execute broader Principales canary, interruption/resume drill and reconciliation audit;
7. run OOD SCJ sample;
8. reconcile docs/testing proof map and remove only gaps actually closed by evidence;
9. mark PR merge-ready only after exact-head required gates pass.
