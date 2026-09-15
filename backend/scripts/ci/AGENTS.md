# JurisNexo CI/quality agent rules

Applies to `backend/scripts/ci/**` in addition to repository-wide `AGENTS.md`.

Read `docs/24-engineering-quality-signals.md` before changing the engineering-quality scanner, thresholds, architecture diff, or review-candidate semantics.

## Authority split

The quality module has two distinct responsibilities:

```text
DETERMINISTIC EVIDENCE COLLECTION
  must be correct and is protected by architecture fitness tests

SEMANTIC REVIEW SIGNALS
  may identify REVIEW_CANDIDATE but are not defects by themselves
```

Never turn eLOC, C901, fan-in, fan-out, suppression counts, forwarding counts, or a composite of them into a blocking score without an explicit normative policy change plus evidence that the blocker protects a real invariant.

HARD architecture/security/provenance/database/legal-quality fitness functions remain independently blocking.

## Required observability

The quality module must preserve visibility into:

- all current top-level JurisNexo component edges and their import sites;
- per-component file count, effective LOC, fan-in and fan-out;
- base-to-tested-tree added/removed edges and changed import sites;
- component and changed-file eLOC deltas;
- changed-file C901 candidates;
- new forwarding-only or re-export-only files;
- recognized suppression growth;
- provenance identifying base SHA, source-head SHA, tested SHA and test mode.

Prefer open-world discovery over fixed component/file inventories.

## Review triggers

Current calibration IDs are:

```text
QR-FSIZE-001      changed file eLOC > 120
QR-CPLX-001       Ruff C901 complexity > 10
QR-COUPLING-001   new cross-component dependency edge
QR-NAV-001        new forwarding-only or re-export-only module
QR-SUPPRESS-001   recognized suppression count increased
```

These triggers produce `REVIEW_CANDIDATE`, not invariant failure.

If calibration changes, update the canonical policy, executable proof, workflow summary/artifact semantics, and guarantee inventory coherently.

## Anti-gaming rules

Do not improve metrics by:

- splitting cohesive code solely to lower eLOC or C901;
- moving dependencies into runtime imports;
- introducing generic `utils`, `helpers`, `services`, `common`, registries, or service locators solely to hide coupling;
- adding wrapper-only/forwarder-only files solely to reduce apparent file size;
- replacing direct imports with re-export facades solely to hide edges;
- suppressing lint/type/security/coverage diagnostics solely to make a scanner green.

The sensor must report the real structure rather than reward cosmetic indirection.

## Evidence integrity

When modifying graph/diff logic, add or adapt a falsifiable architecture proof. Prefer a temporary real Git repository with base/head commits when the claim is about diff behavior; do not prove a diff algorithm only by asserting against hard-coded current-repository numbers.

A valid test should fail for plausible defects such as:

- an added edge omitted from the diff;
- fan-in/fan-out inconsistent with edges;
- base and tested trees accidentally conflated;
- strings counted as suppressions;
- a new forwarding-only layer missed;
- C901 diagnostics dropped or promoted to blocking failures;
- stale source-head provenance represented as the tested tree.

Never weaken the proof merely because the current scanner fails it.
