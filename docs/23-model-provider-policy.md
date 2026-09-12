# JurisNexo — Model Provider Policy

## Purpose

JurisNexo uses OpenAI Agents SDK as the agent orchestration runtime, but it does not standardize on OpenAI-hosted models.

For the MVP and ingestion benchmarks, the intended model providers are:

- Google Gemini;
- DeepSeek.

The exact model must be selected explicitly for each benchmark or production run. Agent constructors and run entry points must not silently fall back to an OpenAI SDK default model.

## Runtime versus model provider

These are separate architectural choices:

```text
OpenAI Agents SDK
    -> agent loop
    -> tools
    -> structured outputs
    -> orchestration primitives
    -> usage/tracing hooks

Model provider
    -> Gemini or DeepSeek
    -> explicitly selected model/version
    -> provider-specific credentials/configuration
```

Using OpenAI Agents SDK does not imply using an OpenAI model.

## Provider integration

Use the Agents SDK provider integration points for non-OpenAI models. The concrete provider adapter may be selected per benchmark/runtime configuration and must remain outside durable legal-domain records.

If a provider is exposed through an OpenAI-compatible endpoint, a compatible SDK client/model-provider path may be used. If broader routing is needed, a provider adapter such as LiteLLM may be used after its exact tool-calling, structured-output, token-usage, and error semantics are benchmarked for the selected Gemini or DeepSeek model.

Do not hide provider selection behind an implicit fallback.

## Benchmark policy

Every agent benchmark must record at minimum:

- provider;
- exact model identifier/version;
- relevant provider configuration;
- token usage when reported reliably;
- latency;
- estimated or measured cost;
- tool-call behavior;
- structured-output validity;
- benchmark quality metrics.

Gemini and DeepSeek should be compared on the same frozen gold cases where practical. Model choice should be driven by measured quality/cost/latency rather than by framework defaults.

## Current agent stages

The following Agents SDK stages require explicit model selection:

- Structure Agent;
- Structure Auditor;
- Extraction Agent;
- Extraction Auditor.

Future research agents and specialist agents should follow the same rule.

## Non-goal

`gpt-5.6-luna` is not a JurisNexo runtime default. If an OpenAI-hosted model is ever benchmarked, it must be an explicit experiment rather than an accidental SDK fallback.
