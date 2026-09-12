# JurisNexo — Testing and Guarantee Evidence

## Purpose

JurisNexo separates **what must remain true** from **which test currently proves it**.

The normative inventory is:

`docs/testing/current-guarantees.toml`

It names durable guarantees, their severity/classification, and the kinds of evidence required. It intentionally does not map guarantees to exact test filenames because test organization can change without changing the protected property.

## Evidence classes

### `fitness`

Deterministic repository/architecture evidence. Appropriate for dependency direction, supported connection surfaces, CI/governance contracts, provider/runtime isolation, and other statically inspectable boundaries.

### `invariant`

Behavioral evidence that a durable correctness property holds at the real authority boundary. Use the actual database/application boundary when that is what owns the guarantee.

### `contract`

Typed/API/schema/state-machine evidence showing that supported callers receive the promised semantics. Contract evidence alone is not enough for a critical behavioral invariant unless the guarantee is purely structural.

### `adversarial`

Negative evidence designed around a plausible defect: wrong tenant, wrong page/artifact membership, unsupported evidence, stale/replayed state, missing audit gate, contradictory source, gold leakage, and similar failure modes.

### `benchmark`

Independent task-quality evidence over frozen or otherwise controlled inputs/gold. Use for stochastic/semantic claims such as structure discovery, extraction accuracy, adverse-authority recall, or verifier value.

### `integration`

Evidence spanning multiple real components/stages, such as Structure -> Audit -> Extraction -> Audit -> canonical commit.

### `security`

Evidence run against the real authorization/tenant/credential boundary rather than an LLM guardrail or mock that cannot exercise the security claim.

## Adding or changing a guarantee

Before editing tests, answer:

```text
What exact risk is protected?
Is the guarantee HARD, CONTROLLED, FLEXIBLE, or HISTORICAL?
What plausible defect must fail?
Which evidence classes are actually necessary?
Which part can be proven statically?
Which part requires PostgreSQL/application execution?
Which part requires an independent semantic benchmark?
```

Then:

1. update the owning architecture/product/security/benchmark document if semantics changed;
2. update `current-guarantees.toml` when the durable guarantee/evidence contract changed;
3. add/adapt the smallest useful fitness test for the structural portion;
4. add the required behavioral/adversarial/benchmark proof at the real execution boundary;
5. ensure the canonical CI lane executes the proof that is intended to block regressions.

Do not add a test merely to mirror a sentence from a document. Protect a real failure mode.

## Interpreting failures

A failure has two valid architectural dispositions:

```text
UNINTENTIONAL DRIFT
  implementation violated accepted architecture -> repair implementation

INTENTIONAL EVOLUTION
  accepted architecture changed -> update docs + guarantee/evidence contract + tests coherently
```

Making CI green by weakening the assertion without resolving the protected risk is invalid.

## Current CI

`backend/tests/architecture/` contains blocking deterministic fitness functions.

The backend-quality job runs them explicitly as:

```text
pytest tests/architecture
```

The full PostgreSQL-backed backend test job also executes them with the repository root mounted read-only. This redundancy is intentional: the explicit architecture step keeps the gate visible, while the broader backend suite makes accidental removal of that one CI line easier to detect through the governance fitness test itself.

Tests that inspect root-level governance/docs receive `JURISNEXO_REPO_ROOT` from CI instead of assuming the backend container contains the entire repository checkout. Pull-request topology tests also receive the actual `GITHUB_BASE_REF` and `GITHUB_HEAD_REF` values.

Other guarantees are proven through integration/PostgreSQL tests and benchmark/scorer lanes. A green architecture suite means the tested structural boundaries remain intact; it does **not** mean every semantic guarantee in the inventory is fully implemented or verified.

## External governance controls

Repository tests can validate the committed CI workflow, observed pull-request topology, branch-cleanup logic, documentation policy, and dependency boundaries. They cannot by themselves configure GitHub branch protection/rulesets or prevent a direct push when the hosting platform still allows one.

Controls such as required status checks, pull-request-only merge policy, force-push prohibition, and default-branch deletion protection must therefore be verified/configured at the GitHub repository/ruleset layer in addition to repository tests. Do not claim a pytest proves those remote settings.

If the connected automation cannot mutate those settings, report the external enforcement gap explicitly rather than weakening the repository contract or pretending the control exists.
