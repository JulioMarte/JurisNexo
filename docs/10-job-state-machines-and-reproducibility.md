# JurisNexo — Job State Machines and Reproducibility

## 1. Purpose

JurisNexo contains long-running ingestion and research workflows. Their state must be explicit so jobs are retryable, observable, auditable, and reproducible enough for professional review.

The OpenAI Agents SDK may execute individual agent runs, tools, handoffs, guardrails, and traces, but it is **not** the durable workflow state machine or legal system of record. JurisNexo application/worker state remains authoritative for mandatory product stages.

## 2. Ingestion job states

The ingestion state machine must expose the mandatory proposal/review gates introduced by the agent pipeline.

Suggested states:

```text
PENDING
  -> ACQUIRING
  -> SOURCE_ACQUIRED
  -> WORKSPACE_PREPARING
  -> STRUCTURE_DISCOVERY_RUNNING
  -> STRUCTURE_REVIEW_REQUIRED
  -> STRUCTURE_APPROVED
  -> EXTRACTION_RUNNING
  -> EXTRACTION_REVIEW_REQUIRED
  -> EXTRACTION_APPROVED
  -> PERSISTING
  -> LINKING
  -> INDEXING
  -> QUALITY_CHECK
  -> READY
```

Optional OCR/rendering work may occur while preparing the workspace or during agent investigation and should be represented as child-stage attempts/events when it is not itself a business gate.

Review alternatives may include:

- `STRUCTURE_MORE_INVESTIGATION_REQUIRED`;
- `STRUCTURE_REJECTED`;
- `EXTRACTION_MORE_INVESTIGATION_REQUIRED`;
- `EXTRACTION_REJECTED`.

Terminal/exception states:

- `BLOCKED_SOURCE`;
- `SOURCE_QUALITY_BLOCKED`;
- `BUDGET_LIMIT_REACHED`;
- `PARTIAL`;
- `FAILED`;
- `CANCELLED`.

No SDK handoff or specialist call may skip `STRUCTURE_APPROVED` before canonical extraction or `EXTRACTION_APPROVED` before canonical persistence.

State transitions must be persisted rather than inferred from logs or SDK traces.

## 3. Research job states

Suggested states:

```text
QUEUED
 -> BRIEFING
 -> SEARCHING
 -> REVIEWING_CASES
 -> EXPANDING_CITATIONS
 -> SEARCHING_ADVERSE_AUTHORITY
 -> ASSESSING_GAPS
 -> VERIFYING_EVIDENCE
 -> SYNTHESIZING
 -> COMPLETED
```

Terminal alternatives:

- `COMPLETED_WITH_LIMITATIONS`;
- `INSUFFICIENT_EVIDENCE`;
- `SOURCE_QUALITY_BLOCKED`;
- `BUDGET_LIMIT_REACHED`;
- `FAILED`;
- `CANCELLED`.

A job may loop from `ASSESSING_GAPS` back to search/review phases. Dynamic specialist agents may run inside these states without replacing the top-level research state machine.

## 4. State transition rules

Each transition should record:

- previous state;
- new state;
- timestamp;
- worker/execution identity;
- attempt number;
- reason/event;
- relevant error code when applicable;
- agent role/runtime/model configuration when the transition resulted from an agent stage;
- stage artifact or audit result identifiers where applicable.

Invalid transitions should be rejected deterministically.

## 5. Idempotency and retries

Network/model/OCR failures are expected.

Every expensive or externally visible step should define:

- idempotency key;
- retry policy;
- retryable versus permanent errors;
- maximum attempts;
- deduplication behavior.

Examples:

- repeated source acquisition must not create duplicate artifacts for identical bytes;
- repeated structure/extraction attempts create versioned stage outputs rather than silently replacing approved evidence;
- repeated evidence extraction should create a versioned attempt or update a deterministic job artifact rather than duplicate report claims silently;
- report finalization must not create multiple user-visible reports from one successful job unless versioning is explicit.

SDK/provider retries are subordinate to this job-level retry policy. Exhaustion of an SDK retry path must surface as an actionable stage failure, not as an implicit workflow restart.

## 6. Reproducibility snapshots

Every completed ingestion or research output should be tied to a reproducibility snapshot containing what is relevant to that workflow, including:

- job/organization identifiers;
- source artifact IDs, versions, and checksums;
- corpus/index generation when research is involved;
- search implementation/config version;
- agent role and instruction/prompt version;
- model/provider/version where obtainable;
- runtime/SDK version and provider-adapter path;
- tools/capability contract version;
- structured-output schema version;
- evidence records used;
- audit/review result versions;
- start/completion timestamps;
- resource-budget configuration;
- failure/retry metadata when material.

Perfect bit-for-bit reproduction is not guaranteed with nondeterministic models, but the evidence, configuration, and stage outputs used to produce a result must remain inspectable.

## 7. Evidence immutability within a version

Once a canonical case extraction or report version is finalized, its evidence set should not silently change when:

- source normalization improves;
- a new model re-extracts a field or holding;
- citation resolution changes;
- the corpus receives new cases;
- an agent framework/runtime changes.

Instead, reruns create a new extraction/report version or a separate job.

## 8. Corpus/index versions

Search behavior changes when the corpus or index changes.

Maintain enough version metadata to answer:

- which cases were searchable when this job ran?
- which retrieval configuration produced these candidates?
- was a later-discovered case absent from the corpus at that time?

For the MVP, a monotonic corpus/index generation ID plus per-source freshness metadata is sufficient.

## 9. Cancellation and budget exhaustion

Cancellation should stop future expensive work without corrupting completed artifacts.

Budget exhaustion must lead to an explicit terminal/limited state. It must never silently lower evidence standards, skip a mandatory ingestion audit, skip adverse-authority search, or skip claim verification.

Already completed stage artifacts may remain available for diagnosis or explicit later resume when policy permits.

## 10. Progress reporting

User-visible progress should derive from persisted state and counts, for example:

```text
Searching jurisprudence
82 candidates found
17 decisions reviewed
4 key citation chains inspected
Adverse search complete
8/9 report claims verified
```

For ingestion, internal/operator progress may similarly expose factual state such as structure discovered, boundaries under review, extraction in progress, or audit blocked.

Do not expose hidden chain-of-thought.

## 11. Failure taxonomy

At minimum distinguish:

- source unavailable;
- parser/workspace failure;
- OCR/source-quality failure;
- identity unresolved;
- structure semantic failure;
- structure audit rejection/conflict;
- extraction semantic failure;
- extraction audit rejection/conflict;
- search service failure;
- model/provider transport failure;
- incomplete model generation;
- SDK/runtime failure;
- tool/subagent/handoff failure;
- provider capability incompatibility;
- authorization failure;
- sandbox failure;
- evidence verification conflict;
- budget exhaustion;
- internal invariant violation.

Actionable error classes are required for reliable retries and operations. Provider/runtime failure must remain distinguishable from a completed agent result that fails a semantic or evidence benchmark.

## 12. MVP Definition of Done

The workflow is operationally ready when:

- every long-running job has an explicit persisted state;
- mandatory Structure/Audit/Extraction/Audit gates cannot be bypassed;
- retries do not duplicate or corrupt artifacts;
- stage attempts and approvals are versioned and inspectable;
- partial and failed states are distinguishable;
- a completed report identifies its corpus, sources, evidence, and model/runtime configuration;
- a completed canonical extraction identifies its source, evidence, agent/auditor versions, and approval path;
- a later corpus/model/runtime update cannot silently rewrite an old extraction or report.
