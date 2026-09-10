# JurisNexo — Job State Machines and Reproducibility

## 1. Purpose

JurisNexo contains long-running ingestion and research workflows. Their state must be explicit so jobs are retryable, observable, auditable, and reproducible enough for professional review.

## 2. Ingestion job states

Suggested top-level states:

```text
PENDING
  -> ACQUIRING
  -> EXTRACTING
  -> OCR_PROCESSING (when required)
  -> NORMALIZING
  -> LINKING
  -> INDEXING
  -> QUALITY_CHECK
  -> READY
```

Terminal/exception states:

- `BLOCKED_SOURCE`;
- `BLOCKED_QUALITY`;
- `PARTIAL`;
- `FAILED`;
- `CANCELLED`.

State transitions must be persisted rather than inferred from log text.

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

A job may loop from `ASSESSING_GAPS` back to search/review phases.

## 4. State transition rules

Each transition should record:

- previous state;
- new state;
- timestamp;
- worker/execution identity;
- attempt number;
- reason/event;
- relevant error code when applicable.

Invalid transitions should be rejected.

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
- repeated evidence extraction should create a versioned attempt or update a deterministic job artifact rather than duplicate report claims silently;
- report finalization must not create multiple user-visible reports from one successful job unless versioning is explicit.

## 6. Research snapshot

Every completed report should be tied to a reproducibility snapshot containing at least:

- research request/brief version;
- organization/job identifiers;
- corpus coverage snapshot or index version;
- search implementation/config version;
- models and model versions where obtainable;
- prompts/instruction template versions;
- tool/runtime version;
- source artifact IDs/versions cited;
- evidence records used;
- report generator version;
- start/completion timestamps;
- resource-budget configuration.

Perfect bit-for-bit reproduction is not guaranteed with nondeterministic models, but the evidence and configuration used to produce the report must remain inspectable.

## 7. Evidence immutability within a report version

Once report version N is finalized, its evidence set should not silently change when:

- source normalization improves;
- a new model re-extracts a holding;
- citation resolution changes;
- the corpus receives new cases.

Instead, a rerun produces report version N+1 or a separate research job.

## 8. Corpus/index versions

Search behavior changes when the corpus or index changes.

Maintain enough version metadata to answer:

- which cases were searchable when this job ran?
- which retrieval configuration produced these candidates?
- was a later-discovered case absent from the corpus at that time?

For the MVP, a monotonic corpus/index generation ID plus per-source freshness metadata is sufficient.

## 9. Cancellation and budget exhaustion

Cancellation should stop future expensive work without corrupting completed artifacts.

Budget exhaustion must lead to an explicit terminal state and a partial/limited report only when evidence standards allow it.

Never silently skip adverse search or claim verification because a budget was reached.

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

Do not expose hidden chain-of-thought.

## 11. Failure taxonomy

At minimum distinguish:

- source unavailable;
- parser failure;
- OCR quality failure;
- identity unresolved;
- search service failure;
- model/provider timeout;
- tool/subagent failure;
- authorization failure;
- sandbox failure;
- verification conflict;
- budget exhaustion;
- internal invariant violation.

Actionable error classes are required for reliable retries and operations.

## 12. MVP Definition of Done

The workflow is operationally ready when:

- every long-running job has an explicit persisted state;
- retries do not duplicate/corrupt artifacts;
- partial and failed states are distinguishable;
- a completed report identifies its corpus, sources, evidence, and model/runtime configuration;
- a later corpus/model update cannot silently rewrite an old report.
