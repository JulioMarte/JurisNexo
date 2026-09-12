# JurisNexo — ADR: Adopt OpenAI Agents SDK for MVP Agent Runtime

## Status

Accepted for MVP implementation and comparative migration.

## Context

JurisNexo needs agentic behavior in two distinct domains:

1. ingestion of messy historical/legal source documents;
2. downstream legal research over a normalized corpus.

Recent historical-bulletin work demonstrated that the project was accumulating custom implementations for generic agent concerns: model loops, retries, token budgeting, context governance, structured generation, delegation, and tracing. Those mechanisms were useful experiments, but they are not intended to become a bespoke general-purpose agent framework.

At the same time, JurisNexo requires domain behavior that no agent framework should own: canonical source identity, page/provenance semantics, evidence ledgers, tenant authorization, corpus persistence, legal research completion rules, and benchmark/release gates.

## Decision

Use **OpenAI Agents SDK** as the default MVP agent runtime.

Use its native primitives where appropriate for:

- agents;
- tool loops;
- structured outputs;
- agents-as-tools;
- handoffs;
- guardrail hooks;
- tracing;
- model/provider invocation.

Do not bind domain architecture to a single model provider. Model selection remains task- and benchmark-driven.

Keep mandatory ingestion/research stage ordering in JurisNexo application code rather than encoding all product flow as free-form handoffs.

## Consequences

### Positive

- removes pressure to maintain a custom general-purpose harness;
- gives a standard vocabulary for tools, specialists, handoffs, tracing, and guardrails;
- allows engineering effort to concentrate on corpus/evidence quality and legal workflows;
- creates a cleaner replacement boundary if a better runtime is adopted later;
- makes multi-agent experiments easier to benchmark against the current baseline.

### Negative / risks

- framework behavior and provider adapters can change independently of JurisNexo;
- some non-OpenAI provider capabilities may not map perfectly to every SDK feature;
- SDK tracing cannot be treated as the durable legal/evidence system of record;
- poorly designed handoffs could hide important business-state transitions;
- adopting the SDK does not solve document understanding, extraction quality, or legal verification by itself.

## Non-negotiable retained components

The migration must preserve or improve:

- original artifact preservation;
- checksum/canonical source identity;
- physical/view/printed-page provenance where applicable;
- structured evidence records;
- authorization/tenant boundaries;
- deterministic job state transitions;
- independent benchmarks;
- ability to distinguish provider failure, runtime failure, semantic failure, and evidence-verification failure.

## Migration rule

Do not remove the current harness until an SDK-based implementation demonstrates at least parity on frozen benchmark tasks and preserves equivalent or better trace/evidence guarantees.

The current harness becomes a baseline and source of reusable document-domain tools, not the long-term runtime architecture.
