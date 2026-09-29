# JurisNexo GitHub Actions agent rules

Applies to `.github/**` in addition to repository-wide `AGENTS.md`.

GitHub Actions in this repository have two distinct roles: automatic quality gates and explicit experiments. Do not blur them.

## Automatic CI versus explicit experiments

Automatic PR/push CI is for deterministic, bounded checks that are safe to execute on every relevant change.

Live, paid, rate-limited, long-running, corpus-scale, provider-backed, or exploratory benchmarks are **opt-in**. They must not call external model providers merely because a normal commit or PR synchronization occurred.

Preferred pattern:

1. expose the experiment through `workflow_dispatch` with explicit, reviewable inputs;
2. run local/offline contract validation before external calls;
3. prepare/freeze the exact benchmark corpus once;
4. fan the same frozen inputs out to compared models/providers;
5. upload per-model outputs plus a summary/artifacts for audit;
6. keep full/corpus-scale runs manual.

## API/tool-driven smoke fallback

GitHub only permits `workflow_dispatch` through the normal dispatch endpoint when the workflow is available from the repository's default-branch workflow surface. Tooling/connectors may also omit the dispatch mutation entirely.

When an experiment workflow is being developed on a work branch and cannot be dispatched directly, use a dedicated trigger ref/branch:

```yaml
on:
  push:
    branches: ["benchmark-smoke/visual-10"]
  workflow_dispatch:
```

The trigger-ref path must:

- match only a dedicated execution ref such as `benchmark-smoke/visual-10`, never the ordinary work branch;
- be created or moved explicitly to the exact commit that should be tested;
- use fixed bounded smoke inputs rather than full-scale defaults;
- use deterministic selection where applicable;
- create no workflow run at all for ordinary work-branch commits;
- never be copied to `development`, `main`, or ordinary feature branches as an unconditional trigger.

The current reference is `.github/workflows/scj-principales-visual-smoke.yml`: creating or moving `benchmark-smoke/visual-10` to a target commit deliberately triggers a bounded 10-page comparison. Ordinary commits on `benchmark/space-bunny-alpha` do not trigger that workflow.

## Provider-backed benchmark requirements

For every provider/model lane, preserve enough evidence to distinguish:

```text
workflow/runtime success
provider/rate-limit behavior
coverage/completion
latency and throughput
token/cost usage
semantic benchmark quality
```

Rate limiting and provider failures are operational results, not semantic quality scores. Add pacing/concurrency controls when required by a provider instead of allowing throttling to bias a comparison.

Do not weaken scorers, change frozen inputs between models, or make an expensive workflow automatic merely to simplify execution.
