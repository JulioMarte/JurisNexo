# JurisNexo — Engineering Quality Signals

Status: normative policy for maintainability and architecture-review signals.

## Purpose

JurisNexo needs mechanical visibility into structural drift without confusing measurements with product correctness or architecture law.

The Request Engine-inspired quality layer covers two complementary views:

```text
CURRENT SNAPSHOT
  Python effective LOC
  current component graph
  fan-in / fan-out
  concrete import sites
  largest files
  C901 complexity candidates

BASE -> HEAD DIFF
  added / removed component edges
  changed import sites
  component eLOC / file-count / fan-in / fan-out deltas
  changed-file eLOC deltas
  suppression growth
  navigation / forwarding / re-export shape deltas
```

The implementation lives in:

- `backend/scripts/ci/quality_metrics.py`
- `backend/scripts/ci/build_engineering_quality_report.py`
- `backend/scripts/ci/build_architecture_diff.py`
- `backend/tests/architecture/test_engineering_quality_signals.py`
- `backend/tests/architecture/test_engineering_quality_diff.py`

## Component model

JurisNexo does not copy Request Engine's `modules/<name>` layout. A current architecture component is discovered from the first package level below:

```text
backend/src/jurisnexo/<component>/
```

The scanner is open-world. Adding a new first-level package containing Python automatically adds a component to the graph. There is no fixed component allowlist or expected file count.

## Connection graph

A directed edge:

```text
A -> B
```

means Python owned by component `A` imports Python owned by component `B`, through an absolute `jurisnexo.*` import or a resolvable relative import.

For every component the snapshot records:

```text
python_files
effective_loc
fan_in
fan_out
inbound_components
outbound_components
```

For every edge it records the concrete import sites.

The architecture diff compares the base tree with the tested tree and records:

```text
added_edges
removed_edges
import_site_deltas
component metric deltas
```

A new edge is `QR-COUPLING-001 REVIEW_CANDIDATE`. It is not automatically a defect. Review whether the dependency reflects real ownership/capability need and whether it crosses persistence, provider, trust, tenant, legal-data, or other authority boundaries.

Never hide a dependency behind a generic helper, service locator, runtime import, re-export, shared bucket, or wrapper solely to improve the graph.

## File-size signal

Effective LOC (`eLOC`) counts lines containing meaningful Python tokens and excludes whitespace/comment-only lines.

Current calibration:

```text
effective file LOC > 120 -> QR-FSIZE-001 REVIEW_CANDIDATE
```

For PRs, active candidates are calculated from changed Python files. The global snapshot still measures all Python files so reviewers retain repository-wide context.

This is deliberately not a blocking architecture limit. A large cohesive or declarative file can be healthier than several tiny forwarding layers.

## Complexity signal

Ruff `C901`/McCabe is used as a reasoning-load sensor with current calibration:

```text
McCabe complexity > 10 -> QR-CPLX-001 REVIEW_CANDIDATE
```

The score identifies a function worth semantic review. It does not prove that extraction is correct. Review whether complexity comes from branching, state, ordering, effects, or genuinely separate responsibilities.

Do not distribute one decision across many helpers merely to lower C901.

## Navigation / indirection signal

For newly added Python files, the scanner observes whether the file is effectively:

```text
only one-call forwarding functions
or
only imports/re-exports (+ optional __all__)
```

Such a file becomes:

```text
QR-NAV-001 REVIEW_CANDIDATE
```

The review asks whether the indirection establishes a real ownership/substitution boundary or only lengthens the reasoning path.

Forwarders and re-exports can be legitimate. They are not rejected numerically.

## Suppression signal

The diff counts recognized comment suppressions:

```text
noqa
type: ignore
nosec
pragma: no cover
```

Growth on a changed file becomes:

```text
QR-SUPPRESS-001 REVIEW_CANDIDATE
```

A suppression can be justified. The question is whether it documents a real tool limitation or hides a defect from lint/type/security/coverage evidence.

The scanner only counts comment tokens so strings containing these words are not treated as suppressions.

## Architecture diff provenance

The diff records:

```text
base_ref
base_sha
source_head_sha
tested_sha
test_mode
```

For pull requests, CI may test GitHub's synthetic merge tree while preserving the actual source-head SHA separately. This prevents a report generated from one tree from being represented as evidence for another.

## Authority semantics

Engineering-quality output distinguishes:

```text
INVARIANT FAILURE
  deterministic architecture/correctness violation; blocking

REVIEW_CANDIDATE
  maintainability evidence requiring semantic interpretation; non-blocking
```

Current review triggers:

```text
QR-FSIZE-001      changed file eLOC > 120
QR-CPLX-001       changed function C901 > 10
QR-COUPLING-001   new cross-component dependency edge
QR-NAV-001        new forwarding-only / re-export-only indirection
QR-SUPPRESS-001   increased recognized suppression count
```

These are calibration triggers, not architecture cliffs.

There is intentionally no synthetic architecture score.

HARD security, provenance, tenant, legal-quality, database, agent-authority and other deterministic fitness/invariant rules remain independently blocking.

## CI behavior

`.github/workflows/engineering-quality.yml` builds the same pinned backend quality environment used by repository tests and emits two artifacts:

```text
.ci/engineering-quality.json
.ci/architecture-diff.json
```

The GitHub Actions summary exposes current graph/totals, largest files, review candidates, base/head provenance, added/removed edges, component deltas and changed-file eLOC deltas.

The artifacts are evidence for review, not a replacement for canonical `CI aggregate`.

## Executable proof

The architecture suite proves more than file existence.

`test_engineering_quality_signals.py` verifies the live repository snapshot:

- component discovery matches the real tree;
- graph endpoints are real components;
- `fan_in` / `fan_out` exactly match detected edges;
- all measured files exist;
- file-size candidates are complete for the scanned scope;
- thresholds remain review calibration rather than merge law;
- the full workflow emits both snapshot and diff evidence.

`test_engineering_quality_diff.py` creates a temporary real Git repository with a base commit and a head commit. It proves that the production scripts detect:

- a newly introduced component edge;
- matching fan-in/fan-out deltas;
- changed-file eLOC growth;
- suppression growth;
- a new forwarding-only file;
- C901 complexity;
- coupling/navigation/suppression signals as `REVIEW_CANDIDATE` rather than invariant failures.

This synthetic Git proof is deliberately independent of the current JurisNexo graph so the suite can fail when the diff implementation is wrong even if the production tree happens not to contain a given signal.

## Agent review protocol

When a signal appears, agents must review in this order:

```text
1. identify the real owner/responsibility
2. inspect reasoning complexity and side effects
3. inspect dependency/trust/authority implications
4. inspect whether the metric changed because of the PR
5. decide one of:
     HEALTHY_AS_IS
     REVIEW_CONCERN
     REFACTOR_RECOMMENDED
     ARCHITECTURE_CONCERN
     INSUFFICIENT_CONTEXT
6. refactor only when a better responsibility boundary exists
7. rerun deterministic architecture and behavioral proof after structural changes
```

Metric gaming is prohibited. Examples include wrapper-only files, one-call forwarding layers, generic shared/service buckets, hidden runtime imports, re-export facades, moving code solely to reduce eLOC, or replacing one visible dependency with an opaque locator.

A green quality report proves that the repository can observe these structural signals consistently. It does not prove semantic/legal correctness.