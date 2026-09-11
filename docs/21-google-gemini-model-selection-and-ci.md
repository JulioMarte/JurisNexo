# JurisNexo — Google Gemini Model Selection and CI Contract

## 1. Decision date and scope

This decision reflects the Google Gemini Developer API offering available in September 2026. Model availability, pricing, and inference tiers are operational facts and must be re-checked periodically; they are not permanent JurisNexo invariants.

The purpose of the model integration is **document-structure discovery and benchmark work**, not ordinary pull-request CI and not direct canonical data generation.

---

## 2. Default model

### Gemini 3.8 Flash

Model ID:

```text
gemini-3.8-flash
```

JurisNexo uses Gemini 3.8 Flash as the primary structure-discovery benchmark model because it supports long context, structured output, multimodal input, tools/function calling, and configurable reasoning while remaining materially cheaper than the Pro tier.

Current standard introductory pricing through 2026-12-31 is approximately:

```text
input:  USD 0.75 / 1M tokens
output: USD 3.75 / 1M tokens, including thinking tokens
```

The benchmark default is now:

```text
LLM_PROVIDER=google
LLM_MODEL=gemini-3.8-flash
LLM_SERVICE_TIER=flex
LLM_THINKING_LEVEL=medium
```

---

## 3. Interactions API is the transport contract

Google made the Interactions API its default Gemini interface in June 2026 and recommends it for new projects and agentic workloads. `generateContent` remains supported but is considered legacy for new development.

JurisNexo therefore uses:

```text
POST https://generativelanguage.googleapis.com/v1beta/interactions
```

with API-key authentication in the `x-goog-api-key` header.

Structured responses use:

```json
{
  "response_format": {
    "type": "text",
    "mime_type": "application/json",
    "schema": {}
  }
}
```

Reasoning and output limits are supplied through `generation_config`.

The provider parses the current Interactions response shape:

```text
steps[].type == model_output
steps[].content[].type == text
usage.total_input_tokens
usage.total_output_tokens
usage.total_thought_tokens
usage.total_tokens
```

The provider sets `store=false` for benchmark requests; model output remains benchmark evidence, not canonical legal data.

---

## 4. Flex inference decision

For offline document-discovery benchmarks, JurisNexo defaults to:

```text
service_tier = flex
```

Flex is an inference tier, not a different hostname. It is selected in the Interactions request body.

Google currently prices Flex at a 50% discount to the standard tier. For Gemini 3.8 Flash during the current introductory period this is approximately:

```text
input:  USD 0.375 / 1M tokens
output: USD 1.875 / 1M tokens, including thinking tokens
```

Flex is appropriate for JurisNexo benchmark/discovery workloads because they are asynchronous from the user's point of view and can tolerate minutes of latency.

However, Flex has deliberately weaker availability characteristics:

- best-effort / sheddable capacity;
- target latency can be roughly 1–15 minutes;
- `429` and `503` are expected capacity signals under load;
- Google does not automatically upgrade Flex requests to Standard;
- clients are responsible for bounded retry/backoff;
- client timeouts should allow approximately 10 minutes or more for queued Flex work.

Therefore a `503` from a Flex request does **not** by itself mean the Gemini API or API key is broken. It can simply mean Flex capacity was unavailable at that moment.

JurisNexo uses a 15-minute per-request transport timeout for Flex and bounded retries. A benchmark may explicitly choose `standard` or `priority` through the workflow input when availability/latency is more important than cost.

---

## 5. Benchmark comparability policy

A benchmark intended to compare structure quality should not silently switch model families after an availability error. Mixing models makes accuracy and cost attribution ambiguous.

Therefore the default benchmark keeps a single requested model for the full run and records:

```text
provider
model
service_tier
response_id
input tokens
output tokens
thinking tokens
total tokens
```

Retries may repeat the same request/model/tier only for transient transport/capacity errors.

If a different model or tier is tested, it must be a separate benchmark run.

---

## 6. Other model candidates

### Gemini 3.1 Flash-Lite

Role:

- page/document triage;
- simple classification;
- high-volume low-complexity subtasks;
- cost baseline against 3.8 Flash.

Approximate standard pricing:

```text
input:  USD 0.25 / 1M text/image/video tokens
output: USD 1.50 / 1M tokens
```

### Gemini 3.1 Pro Preview

Role:

- difficult-artifact benchmark;
- quality-ceiling comparison;
- not the production/default discovery model while it remains preview and substantially more expensive.

Approximate standard pricing up to the lower prompt tier:

```text
input:  USD 2.00 / 1M tokens
output: USD 12.00 / 1M tokens
```

---

## 7. What JurisNexo measures

Model selection must be based on measured legal-document performance, not model reputation alone.

Required dimensions:

- boundary/structure precision and recall;
- schema-valid response rate;
- unresolved-anomaly rate;
- robustness to OCR noise;
- input/output/thinking tokens;
- wall-clock latency;
- cost per artifact;
- tool calls/model calls needed to reach a valid hypothesis;
- provider/tier availability failure rate.

A cheaper call is not cheaper if it creates materially more review work or additional calls.

---

## 8. GitHub secret and workflow policy

The API key must never be committed to the repository.

GitHub Environment:

```text
llm-benchmark
```

Environment secret:

```text
GEMINI_API_KEY
```

Paid model calls run only from explicit `workflow_dispatch`; they are not triggered by push, pull request, merge, Dependabot, or ordinary CI.

The workflow runs with `contents: read` and receives no Supabase service-role/database credential.

The benchmark exposes `service_tier` as an explicit input with:

```text
flex       # default: cheaper, variable latency/best effort
standard   # ordinary service tier
priority   # higher-cost low-latency tier when available
```

---

## 9. Provider-data policy

Public jurisprudence may be suitable for external-model processing subject to provider terms and project policy.

Tenant-private material is a different data class. It must not be sent to Gemini merely because public-corpus discovery supports Gemini.

Before private artifacts are sent to a model provider, JurisNexo needs an explicit tenant/provider-data policy covering retention, training use, jurisdiction, contractual terms, access controls, and user disclosure where applicable.

---

## 10. Model-selection policy

Current defaults:

```text
structure discovery: gemini-3.8-flash / flex / medium
simple triage candidate: gemini-3.1-flash-lite
hard-case comparison: gemini-3.1-pro-preview / benchmark only
```

No model or service tier has permanent preferred status.

A replacement should win on a measured combination of:

```text
legal-document structural accuracy
+ robustness to OCR noise
+ structured-output/tool reliability
+ availability
+ latency
+ cost
+ provider/data-policy suitability
```
