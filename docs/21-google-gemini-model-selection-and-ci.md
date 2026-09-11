# JurisNexo — Google Gemini Model Selection and CI Contract

## 1. Decision date and scope

This decision reflects the Google Gemini Developer API offering available in September 2026. Model availability and pricing are operational facts and must be re-checked periodically; they are not permanent JurisNexo invariants.

The purpose of the first model integration is **document-structure discovery and benchmark work**, not ordinary pull-request CI and not direct canonical data generation.

---

## 2. Models considered

### Gemini 3.8 Flash — default discovery model

Model ID:

```text
gemini-3.8-flash
```

Why it is the default:

- generally available for production use;
- Google's most capable current Flash model;
- designed for autonomous agents, long-horizon tasks, and complex workflows;
- 1,048,576-token input context and 65,536-token output limit;
- text, image, video, audio, and PDF input;
- structured output;
- function calling;
- code execution support;
- configurable `low`, `medium`, and `high` thinking levels;
- substantially cheaper than the Pro tier for repeated discovery experiments.

Current introductory standard pricing through 2026-12-31:

```text
input:  USD 0.75 / 1M tokens
output: USD 3.75 / 1M tokens, including thinking tokens
```

Google currently states that standard pricing rises on 2027-01-01, so costs must be re-evaluated before that date.

Initial JurisNexo default:

```text
LLM_PROVIDER=google
LLM_MODEL=gemini-3.8-flash
LLM_THINKING_LEVEL=medium
```

Use `low` for simple classification/triage benchmarks. Use `high` only when a measured hard case justifies the extra latency/output-thinking cost.

### Gemini 3.1 Flash-Lite — cheap triage candidate

Model ID:

```text
gemini-3.1-flash-lite
```

Current standard pricing:

```text
input:  USD 0.25 / 1M text/image/video tokens
output: USD 1.50 / 1M tokens
```

Role:

- page/document triage;
- simple classification;
- high-volume low-complexity sub-tasks;
- benchmark competitor against 3.8 Flash.

It is not the initial structure-discovery default because the primary risk is incorrect structural inference, not token cost.

### Gemini 3.1 Pro Preview — escalation benchmark only

Model ID:

```text
gemini-3.1-pro-preview
```

Current standard pricing for prompts up to 200k tokens:

```text
input:  USD 2.00 / 1M tokens
output: USD 12.00 / 1M tokens
```

For prompts above 200k tokens the published price is higher.

Role:

- occasional benchmark on difficult artifacts;
- quality ceiling comparison;
- not the default because it is preview and materially more expensive.

---

## 3. Illustrative request cost

For a bounded discovery experiment using approximately:

```text
100,000 input tokens
10,000 output/thinking tokens
```

rough standard cost at current prices is approximately:

```text
Gemini 3.8 Flash       USD 0.1125
Gemini 3.1 Flash-Lite  USD 0.0400
Gemini 3.1 Pro Preview USD 0.3200  (assuming <=200k prompt tier)
```

This is only an illustration. Real discovery cost must be recorded from provider usage metadata for every run.

JurisNexo should prefer selective RLM-style inspection over placing an entire 700-page OCR transcript into every model call even when the context window permits it.

---

## 4. Performance and speed interpretation

Google describes 3.8 Flash as its most intelligent Flash model and explicitly targets agentic/long-horizon work while retaining Flash-class cost and speed characteristics.

Google describes Flash-Lite as the cost-efficient high-volume option.

Google does not publish one universal latency number that would make a fair legal-document comparison across these models. JurisNexo therefore must benchmark latency itself using the same artifacts, prompts, thinking levels, and output schemas.

Required benchmark dimensions:

- boundary/structure accuracy;
- schema-valid response rate;
- unresolved-anomaly rate;
- input/output/thinking tokens;
- provider-reported model version;
- wall-clock latency;
- cost per artifact;
- number of follow-up calls required to reach a valid hypothesis.

A cheaper first call is not cheaper if it creates materially more review work or additional calls.

---

## 5. GitHub CI secret setup

The API key must not be committed to the repository.

Create a GitHub Environment named:

```text
llm-benchmark
```

Inside that Environment create this secret:

```text
GEMINI_API_KEY
```

The manual workflow references it as:

```yaml
env:
  GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

Recommended non-secret configuration remains workflow input or environment/repository variables:

```text
LLM_PROVIDER=google
LLM_MODEL=gemini-3.8-flash
LLM_THINKING_LEVEL=medium
```

The initial integration accepts either Google-supported API-key environment convention at the provider layer in the future, but GitHub standardizes on `GEMINI_API_KEY` to avoid ambiguous precedence.

---

## 6. Workflow security policy

Paid model calls run only from an explicit `workflow_dispatch` workflow.

They are not triggered by:

- push;
- pull request;
- merge;
- routine CI;
- Dependabot or other untrusted automation.

The job runs with:

```text
contents: read
```

and receives no database/service-role secret.

The first workflow performs exactly one bounded structured-generation request and has explicit input/output limits. Future recursive discovery workflows must add explicit request/token/cost budgets before being enabled.

If `GEMINI_API_KEY` is absent, the workflow fails closed.

---

## 7. Provider data policy

Public jurisprudence may be suitable for external-model processing subject to provider terms and project policy.

Tenant-private material is a separate data class. It must not be sent to Gemini merely because the public-corpus discovery workflow supports Gemini.

Before any private artifact is sent to a model provider, JurisNexo must have an explicit tenant/provider-data policy covering retention, training use, jurisdiction, contractual terms, and user disclosure where applicable.

---

## 8. Transport decision

The first implementation uses Google's documented Gemini REST `generateContent` endpoint for a bounded, non-interactive structured-output request.

Reason:

- no additional Python dependency or lockfile change;
- simple to fake in unit tests;
- sufficient for the one-call baseline;
- keeps the provider behind a JurisNexo interface.

Google currently recommends the Interactions API for richer agentic workflows. When JurisNexo implements the recursive discovery environment and multi-step tool loop, the Google provider should be benchmarked/migrated to Interactions without leaking provider-specific types into ingestion domain code.

---

## 9. Model-selection policy

Current default:

```text
structure discovery: gemini-3.8-flash / medium
simple triage candidate: gemini-3.1-flash-lite / low or minimal where supported
hard-case comparison: gemini-3.1-pro-preview / benchmark only
```

No model gains permanent preferred status.

A replacement model should win on a measured combination of:

```text
legal-document structural accuracy
+ robustness to OCR noise
+ tool/structured-output reliability
+ latency
+ cost
+ provider/data-policy suitability
```

not on leaderboard reputation alone.
