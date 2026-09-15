# JurisNexo — Engineering Quality Signals

Status: normative policy for maintainability and architecture-review signals.

## Purpose

JurisNexo needs mechanical visibility into code size and component connections without confusing those measurements with product correctness or architecture law.

The repository therefore maintains a Request Engine-inspired engineering-quality report covering:

```text
Python file effective LOC
largest Python files
current top-level component graph
fan-in / fan-out by component
concrete cross-component import edges
import sites for each edge
review candidates for unusually large files
```

The implementation lives in:

- `backend/scripts/ci/quality_metrics.py`
- `backend/scripts/ci/build_engineering_quality_report.py`
- `backend/tests/architecture/test_engineering_quality_signals.py`

## Component model

JurisNexo does not copy Request Engine's `modules/<name>` layout. A current architecture component is discovered from the first package level below:

```text
backend/src/jurisnexo/<component>/
```

Examples include `corpus`, `ingestion`, `acquisition`, `entrypoints`, and `model_providers` when those packages contain Python code.

The scanner is open-world: adding a new first-level package automatically adds it to the graph. There is no fixed allowlist of component names or file counts.

## Connection graph

A directed edge:

```text
A -> B
```

means Python code owned by component `A` imports code from component `B` through either an absolute `jurisnexo.*` import or a resolvable relative import.

For every component the report records:

```text
python_files
effective_loc
fan_in
fan_out
inbound_components
outbound_components
```

For every edge it records the import sites that produced that connection.

The graph is evidence for review. A high fan-in or fan-out is not automatically a defect. New or surprising connections must be reviewed for ownership, trust boundaries, data authority, and whether the dependency is actually required.

Never hide a dependency behind a generic helper, service locator, re-export, runtime import, or shared bucket merely to improve the graph.

## File-size signal

Effective LOC (`eLOC`) counts lines containing meaningful Python tokens and ignores whitespace/comments-only lines.

The current calibration trigger is:

```text
effective file LOC > 120 -> QR-FSIZE-001 REVIEW_CANDIDATE
```

This is deliberately **not** a blocking architecture limit.

A file over 120 eLOC may be healthy when it is cohesive, linear, declarative, or easier to reason about in one place. The correct review asks:

```text
Does it contain independently changing responsibilities?
Would extraction reduce reasoning cost?
Would extraction create real ownership or only forwarding ceremony?
Is complexity caused by branching/state/effects rather than raw length?
```

Do not split a file solely to lower eLOC.

## Authority semantics

Engineering-quality output distinguishes two concepts:

```text
INVARIANT FAILURE
    deterministic architecture/correctness violation; blocking

REVIEW CANDIDATE
    maintainability evidence requiring semantic interpretation; non-blocking
```

File size and numeric fan-in/fan-out remain review signals. Existing architecture fitness functions, security/provenance guarantees, tenant isolation, legal-source integrity, and other HARD invariants remain independently blocking.

There is intentionally no synthetic architecture score.

## CI behavior

The canonical CI quality lane generates an engineering-quality JSON report and GitHub Actions summary. The summary should make visible:

- component files/eLOC/fan-in/fan-out;
- all detected cross-component connections;
- the largest current Python files;
- file-size review candidates.

`backend/tests/architecture/test_engineering_quality_signals.py` separately verifies that:

- component discovery is open-world;
- graph endpoints are real components;
- `fan_in` and `fan_out` exactly match the detected edges;
- every measured file exists;
- every file above the current review threshold appears as a review candidate;
- the policy remains explicitly non-blocking for maintainability metrics.

A green quality report does not prove semantic correctness. It proves that the repository can observe its current structural signals consistently.

## Agent protocol

When a signal appears, agents must not immediately refactor. Review in this order:

```text
1. identify the owner/responsibility
2. inspect real reasoning complexity and side effects
3. inspect connection/trust/authority implications
4. decide HEALTHY_AS_IS or a concrete concern
5. refactor only when a better responsibility boundary exists
6. rerun architecture and behavioral proof after structural changes
```

Metric gaming is prohibited. Examples include wrapper-only files, one-call forwarding layers, generic shared/service buckets, hidden runtime imports, or re-export facades created only to reduce file size or visible coupling.
