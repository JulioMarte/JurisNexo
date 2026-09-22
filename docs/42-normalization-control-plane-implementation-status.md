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
| 3. Gold Set/contracts | IMPLEMENTED IN PART | Generic fixtures and legal-critical CER/WER/token scoring exist; real SCJ calibration/holdout semantic gold remains PENDING EVIDENCE |
| 4. Planner/durable execution | IMPLEMENTED | deterministic planning, idempotency, durable checkpoints, retry classes, circuit breaker and interrupted-run resume exist |
| 5. Docling/Tika production adapters | IMPLEMENTED | object-storage derivatives, lineage, PDF-aware OCR, language configuration and optional isolated Docling subprocess exist |
| 6. Deterministic QA | IMPLEMENTED | text health/legal-critical signals exist; page/region OCR behavior uses Docling PDF-aware OCR; semantic quality thresholds remain benchmark-owned |
| 7. JEV shadow | PROVEN IN BOUNDED LIVE BENCHMARK | DecisionProvider + OpenRouter decisions adapter + DecisionTextQualityJudge + shadow persistence exist. A 4-source Principales live benchmark passed with 0 calibration/holdout false negatives and false positives on the bounded corruption task, Brier ≈ 0.0153, claim argmax accuracy 1.0, 373 ms quality-batch latency and total observed OpenRouter cost US$0.000660282. Promotion remains blocked by insufficient sample size. |
| 8. Visual verification | IMPLEMENTED | provider-neutral verifier, DeepSeek V4.1 Flash visual adapter path, correction proposals and bounded two-call smoke exist; live benchmark remains PENDING EVIDENCE |
| 9. Resolved views/sentinel/workspace | IMPLEMENTED | evidence/search separation, stable workspace, deterministic sentinel sampling and read-only GC audit exist |
| 10. Reconciliation | IMPLEMENTED | fail-closed plan/DB/lineage/storage/quality reconciliation and immutable normalization manifest exist; PostgreSQL + S3-compatible integration proof exists |
| 11. SCJ Principales rollout | IMPLEMENTED IN PART | real-source canary/smoke infrastructure exists; calibration, holdout, adversarial sample, broader canary/full rollout and OOD promotion evidence remain PENDING |
| 12. Second source | PROVEN | Official TC/0001/26 passed the same Tika + Docling normalization core; source-specific logic remains confined to acquisition |

## Current engine policy

- Docling is the primary structural normalizer.
- Apache Tika is format/metadata/fallback support, not canonical legal text.
- PDF OCR uses Docling PDF-aware layout-region routing so native PDF cells are not blindly rasterized.
- OCR languages are source/jurisdiction configuration, not normalization-core identity. Dominican SCJ/TC canaries use `iso:es`.
- The optional isolated Docling worker enforces timeout, source/output byte limits, temp cleanup and strips DB/S3/OpenRouter credentials from the parser subprocess. Container/job isolation remains responsible for kernel/network-level sandboxing.

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
- downstream workspace APIs do not expose parser/provider internals.

## Claims that must NOT be made yet

Do not claim any of the following until the corresponding evidence has passed:

- all SCJ Principales are normalized;
- OCR quality is calibrated for the full Principales distribution;
- JEV thresholds are production-ready;
- JEV has a production-representative acceptable false-negative rate beyond the bounded 4-source smoke;
- visual-verifier false-correction rate is acceptable beyond the bounded smoke;
- the worker is a complete security sandbox;
- the full Principales Definition of Done in doc 41 is complete.

## Remaining closure sequence

1. obtain exact-head deterministic CI green;
2. execute the labeled OCR calibration/holdout lane on real Principales pages;
3. expand JEV calibration/holdout to promotion-sized source-verified samples while preserving split independence;
4. run one explicitly labeled JEV + DeepSeek challenger smoke;
5. run one explicitly labeled two-call visual verifier smoke;
6. persist/analyze model probabilities, false negatives, calibration, token/cost/latency evidence and durable observation lineage;
7. execute broader Principales canary, interruption/resume drill and reconciliation audit;
8. run OOD SCJ sample;
9. reconcile docs/testing proof map and remove only gaps actually closed by evidence;
10. mark PR merge-ready only after exact-head required gates pass.
