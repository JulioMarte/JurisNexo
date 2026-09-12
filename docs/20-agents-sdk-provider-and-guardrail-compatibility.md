# JurisNexo — OpenAI Agents SDK Provider and Guardrail Compatibility

## 1. Purpose

OpenAI Agents SDK is the default MVP runtime, but JurisNexo must not assume that every model provider supports every SDK capability with identical semantics.

This document makes provider/runtime compatibility an explicit engineering contract rather than an implicit promise of interchangeability.

## 2. Provider portability is capability-based

Model/provider selection is benchmark- and configuration-driven, but a provider is eligible for a role only if it satisfies that role's required capabilities.

The OpenAI Agents SDK supports third-party provider adapters, but adapter/provider feature coverage can differ. At the time of this decision, official SDK documentation describes Any-LLM and LiteLLM integrations as best-effort/beta and warns that structured outputs, multimodal inputs, hosted tools, and other features vary by provider.

Therefore:

> "provider configurable" does not mean "providers are feature-equivalent."

Before assigning a model/provider to an agent role, validate the exact pinned SDK + adapter + provider combination.

## 3. Capability profile per role

Each agent role should declare required and optional capabilities.

Example conceptual profile:

```text
Structure Agent
  required:
    - function/tool calling
    - structured output reliability
    - sufficient context
  optional/conditional:
    - image/PDF multimodality

Structure Auditor
  required:
    - function/tool calling
    - structured output reliability
    - independent source access

Extraction Agent
  required:
    - function/tool calling
    - structured output reliability
  source-dependent:
    - multimodal page inspection

Research Agent
  required:
    - function/tool calling
    - agents-as-tools or equivalent bounded delegation
  optional:
    - larger context

Claim/Evidence Auditor
  required:
    - structured output reliability
    - evidence retrieval tools
```

A model that cannot meet required capabilities must not be selected merely because it is cheaper.

## 4. Compatibility matrix

Maintain an implementation-level tested matrix containing at least:

```text
SDK version
adapter/provider implementation
model identifier
structured outputs: pass/fail/degraded
function tools: pass/fail/degraded
multimodal input: pass/fail/degraded
agents-as-tools: pass/fail/degraded
handoffs: pass/fail/degraded
usage accounting: pass/fail/degraded
tracing visibility: pass/fail/degraded
known request/response limitations
benchmark result by JurisNexo task class
```

The matrix must be based on tests, not marketing/API-name similarity.

## 5. Structured output policy

Persisted legal artifacts should use Pydantic/JurisNexo schemas independent of provider response objects.

If a provider lacks reliable native structured output:

1. do not silently lower validation standards;
2. evaluate whether SDK/schema validation plus bounded retry is adequate;
3. benchmark invalid-output and semantic-error rates;
4. use a different model/provider for that role if reliability is insufficient.

Valid JSON is not equivalent to legally/evidentially correct output; independent auditors and benchmarks remain necessary.

## 6. Multimodal policy

Messy legal documents may require page-image/PDF inspection when extracted text is insufficient.

A text-only provider may still serve roles that consume normalized text, but it must not be used for a stage requiring visual evidence unless JurisNexo supplies an equivalent upstream visual/OCR artifact whose loss has been benchmarked acceptable.

Visual inspection should be invoked when needed rather than forcing all pages through expensive multimodal analysis.

## 7. Handoffs and agents-as-tools

Use agents-as-tools when a parent should retain control and request a bounded specialist result.

Use handoffs when transferring responsibility is genuinely the clearer interaction model.

Mandatory ingestion gates remain explicit application orchestration and are not encoded solely as handoffs.

Provider compatibility with nested agent/model usage must be tested per role; a parent and specialist may use different models/providers when supported and benchmarked.

## 8. Guardrail execution semantics

Do not assume that attaching an input/output guardrail to every agent means it executes around every step.

Current OpenAI Agents SDK semantics distinguish:

- **input guardrails** — apply at the workflow boundary/first agent;
- **output guardrails** — apply to the agent producing the final workflow output;
- **tool guardrails** — apply around supported custom function-tool invocations.

Important limitations must be accounted for in design:

- tool guardrails do not automatically protect the handoff operation itself;
- agents exposed through `Agent.as_tool()` do not automatically gain the same tool-guardrail behavior as an ordinary guarded function tool;
- hosted/built-in tools may have different guardrail behavior;
- parallel input guardrails can allow model/tool work to begin before a tripwire result; blocking/preflight behavior must be selected when execution must not start first.

Therefore mandatory authorization, provenance, evidence membership, state transitions, and commit rules remain JurisNexo application/API invariants.

## 9. Guardrail placement rule

For every safety/quality rule classify it explicitly:

```text
workflow-boundary guardrail
function-tool guardrail
specialist/auditor agent
Pydantic/schema validation
Corpus API/application invariant
database constraint
authorization policy
benchmark/release gate
```

Do not label a requirement merely as "guardrail" without identifying where and how it executes.

Examples:

```text
User request classification
  -> workflow input guardrail

Tool argument shape
  -> schema + function-tool guardrail

May this organization read this case?
  -> Corpus API authorization, never LLM guardrail

Does evidence_id actually belong to artifact/page?
  -> application/database invariant

Does this passage support the claimed holding?
  -> Evidence Auditor + benchmark

Can an extraction become canonical?
  -> persisted workflow state + Corpus API commit gate
```

## 10. Tracing and privacy

SDK tracing is useful for model turns, function tools, handoffs, guardrails, and operational debugging.

However:

- JurisNexo durable job/evidence records remain the system of record;
- tracing configuration must follow privacy/data-retention policy;
- sensitive tenant content must not be sent to an external trace destination without the required product/privacy decision and controls;
- non-OpenAI model tracing behavior must be tested with the selected adapter/provider path.

## 11. Upgrade discipline

Pin SDK and provider-adapter versions for reproducible benchmark runs.

Before a material runtime/adapter upgrade:

1. rerun capability contract tests;
2. rerun protected agent benchmarks;
3. compare token/cost/latency and failure taxonomy;
4. verify guardrail/handoff/tool behavior did not change in a way that weakens product invariants;
5. record the new runtime version in reproducibility metadata.

Do not assume a minor SDK upgrade is behaviorally irrelevant for agent workflows.

## 12. Decision rule

OpenAI Agents SDK remains the default MVP runtime while it reduces generic harness work without weakening JurisNexo's evidence, security, portability, or benchmark requirements.

If a required provider or capability cannot be supported reliably, prefer a bounded adapter or role-specific fallback before rebuilding a general-purpose harness. A future runtime migration remains acceptable because the Document Workspace, Corpus API, evidence schemas, job states, and benchmarks are framework-independent.
