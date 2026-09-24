# Normalization production-readiness contract

Status: CURRENT CLOSEOUT CONTRACT.

This document defines the evidence required before the universal normalization control plane can be described as production-ready. It does not replace docs 39-43. It converts their architecture and quality requirements into explicit release gates.

The governing rule is simple:

> A green workflow proves only the thing that workflow measures. Production readiness requires all applicable gates below to be supported by exact-head evidence.

## Gate A — deterministic exact-head integrity

Required:

- main CI green on the exact candidate SHA;
- normalization production-readiness workflow green;
- database baseline equivalence green;
- engineering-quality signals green;
- TC second-source normalization smoke green;
- no required deterministic job skipped because of a label/configuration mistake.

No live-provider result can override a deterministic failure.

## Gate B — corpus accounting and reproducible benchmark execution

The Principales corpus suite must:

- partition work deterministically by source SHA;
- use isolated shard checkpoints so parallel shards cannot overwrite each other;
- persist immutable per-run snapshots;
- version resume identity by parser/scorer/selector identity;
- emit an inventory for every PDF assigned to a shard;
- distinguish sampled, no native text, no qualifying reference page, and explicit limit exclusions;
- never treat S3/auth/network errors as an empty checkpoint;
- distinguish sampled-document metrics from full-document verdicts.

A full-corpus audit uses SUITE_DOCUMENT_LIMIT=0. Bounded PR runs are evidence about only the sampled subset.

## Gate C — stratified and adversarial gold

Before full Principales promotion, retain an independently reviewed gold corpus covering representative and difficult structure, including where available:

- judgment opening/headers;
- reasoning/considerandos;
- dispositive/fallo;
- citations and dense identifiers;
- footnotes;
- tables;
- signatures/seals;
- dissents/separate opinions;
- mixed text/image pages;
- scanned pages;
- older/problematic layouts;
- known historical failures.

Calibration and holdout must be separated by source document. Holdout evidence cannot be used to choose thresholds.

At least one human-reviewed subset must verify legal-critical values visually instead of treating the PDF text layer as absolute truth.

## Gate D — JEV remains shadow until promotion evidence

The promotion benchmark must use adjudicative pages rather than front matter.

Minimum evidence target:

- at least 25 positive and 25 negative quality examples in calibration;
- at least 25 positive and 25 negative examples in holdout;
- threshold selected only on calibration;
- frozen threshold evaluated on holdout;
- holdout false-negative rate within the declared policy;
- false-positive/escalation rate within policy;
- holdout calibration/Brier evidence;
- model identity, tokens, latency and cost persisted.

Benchmark eligibility does not automatically activate JEV. Runtime policy remains shadow until a separate policy change is explicitly reviewed.

Permanent sentinel sampling is required before any future autoaccept path.

## Gate E — structured reasoning and visual verification

DeepSeek/VLM promotion requires provider-specific evidence, not capability assumptions.

For every live benchmark persist where available:

- requested model;
- effective model;
- routed provider;
- structured-output mode;
- reasoning effort;
- parse success/failure;
- tokens/reasoning tokens;
- latency;
- cost.

Tool calling, JSON Schema and JSON-object modes may be compared. Provider pinning should be used for reproducibility when provider variance matters.

Visual verification must measure false corrections separately from successful corrections. A model response is never primary legal evidence.

## Gate F — real-provider evidence persistence

At least one successful real-provider run must prove:

OpenRouter response
→ durable observation
→ proposed correction/decision
→ resolved evidence representation
→ immutable derivation lineage.

Provider doubles remain valid contract evidence but do not satisfy this live gate.

## Gate G — interruption, resume and reconciliation

Before full rollout, execute an operational drill that interrupts work at meaningful boundaries and demonstrates:

- same manifest/pipeline/config identity resumes safely;
- completed work is not duplicated;
- partial work is not silently accepted;
- S3 and PostgreSQL state reconcile;
- missing objects fail closed;
- terminal success is impossible before reconciliation;
- immutable normalization manifest is published only after successful reconciliation.

## Gate H — security, observability and economics

Record enough evidence to estimate:

- seconds/page and pages/second;
- output bytes/page;
- CPU/memory where the production runtime exposes them;
- storage/network volume;
- JEV/VLM cost;
- provider cost/page and cost/document;
- total infrastructure cost once the worker runtime is chosen.

Production workers must have bounded source/output size, wall time, temporary storage and credentials. Parser subprocesses must not inherit database, storage or model-provider credentials. Kernel/network isolation remains a deployment responsibility.

Operational monitoring must expose at minimum:

- pending/succeeded/failed/unresolved;
- throughput;
- OCR/escalation/review rates;
- critical-error and correction rates;
- retries/circuit-breaker state;
- provider failures;
- storage growth;
- cost/page and cost/document when available.

## Gate I — staged rollout and out-of-distribution proof

Principales rollout order:

1. deterministic fixtures/contracts;
2. stratified calibration;
3. frozen holdout;
4. 10-20 full-document adversarial cases;
5. progressively larger canaries;
6. full Principales;
7. out-of-distribution SCJ sample;
8. broader-source decision.

A second-source regression corpus must prove that onboarding a new institution normally changes source acquisition/configuration, not the normalization control-plane architecture.

## Production-readiness workflows

Daily CI remains fast and deterministic.

The dedicated Normalization production readiness lane groups the deterministic normalization guarantees that must stay green together:

- source-agnostic architecture;
- benchmark/scoring contracts;
- isolation/operational controls;
- control-plane lineage;
- resume identity;
- PostgreSQL/S3 finalization and reconciliation;
- durable model-evidence persistence;
- structured-output contracts.

Live corpus/JEV/VLM lanes remain separate because they use real storage/providers and intentionally have different cost/failure semantics.

## Release rule

Do not mark PR #121 merge-ready merely because implementation exists.

The candidate can leave draft only when:

- deterministic exact-head gates are green;
- remaining live gaps are either proven or explicitly disabled/shadow with a safe fallback;
- Principales evidence meets the accepted rollout stage;
- docs 42/current-proof-map match the actual evidence;
- there is no silent degraded mode.

Safe baseline operation must not depend on JEV, DeepSeek or a visual model being available. The control plane must be able to fall back to deterministic QA plus explicit unresolved/manual review.
