# JurisNexo production-code agent rules

Applies to `backend/src/jurisnexo/**` in addition to the repository-wide `AGENTS.md`.

This file is an operational map. Durable architecture belongs in `docs/`.

Before changing production code, identify the owning capability, affected guarantee IDs from `docs/testing/current-guarantees.toml`, the real authority boundary, and the proof that should catch a regression.

## Non-negotiable boundaries

- Primary legal sources and durable provenance are authoritative; model output is not.
- Agent/model runtimes do not own database authority, tenant identity, provenance validation, or canonical-write permission.
- Provider SDK types and Agents SDK runtime objects are infrastructure details and must not become durable corpus/evidence contracts.
- Corpus access crosses explicit application/corpus capabilities. Do not hand agents unrestricted SQL connections or production credentials.
- Canonical persistence must remain behind deterministic authorization, source/evidence validation, and required audit gates.
- Do not bypass mandatory ingestion stages by moving their authority into prompts, handoffs, or provider callbacks.

## Ownership and abstraction

Prefer capability/domain names over generic buckets. Do not create `utils.py`, `helpers.py`, `common.py`, `services.py`, `managers.py`, generic repositories, or a second generic agent framework merely to make dependencies easier.

A new abstraction must make ownership, authority, failure handling, or testability clearer. A forwarding wrapper that only hides coupling is not an improvement.

## Provider/model changes

When touching `model_providers` or agent-runtime integration, verify the role actually requires and supports the relevant capabilities: structured outputs, tool calling, multimodal input, accounting, retry/error semantics, tracing, latency, and cost.

Provider compatibility is not inferred from API similarity. Keep provider-specific mechanics behind adapters and preserve model/provider/configuration metadata needed for reproducibility.

## Corpus and ingestion changes

For corpus/provenance/canonical-write changes, read the relevant current docs, especially:

- `docs/02-legal-corpus-and-data-model.md`
- `docs/15-ingestion-agent-pipeline.md`
- `docs/16-corpus-api-agent-contract.md`
- `docs/testing/current-guarantees.toml`
- `docs/testing/evidence-authoring-guide.md`

For a correctness-sensitive change, state the plausible defect and add/adapt the proof at the real execution boundary. Do not use a mock for the mechanism whose correctness is being claimed.

## Completion discipline

Run the narrowest relevant tests first, then the canonical CI-owned lane. Never report a proof as passing unless it actually ran on the intended code/environment. If a HARD guarantee is not fully proven, report the evidence gap explicitly rather than implying completion.
