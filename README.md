# JurisNexo

JurisNexo is an experimental legal research system focused on Dominican jurisprudence.

The MVP is not intended to be a general-purpose legal chatbot. Its initial purpose is narrower: accept a legal question or fact pattern, investigate relevant Dominican case law through structured retrieval and agentic research, verify the evidence behind material claims, and deliver a concise, auditable research report with source citations.

JurisNexo will first be validated as a QuisqueyaTech experimental product. The initial demo may be offered free or with limited usage to trusted testers and early legal professionals. Only after measuring real value, research quality, time saved, and willingness to pay should the project evolve into a standalone commercial product.

## MVP thesis

A lawyer should be able to describe a legal issue and receive a report that answers:

- What is the current jurisprudential position?
- Which decisions are the strongest authorities?
- Which decisions support the position?
- Which decisions cut against it?
- What material facts distinguish the cases?
- Has the doctrine changed over time?
- What is the strongest adverse authority?
- Where, exactly, does each material proposition appear in the source decision?

The system should continue researching until its evidence checklist is satisfied or explicitly report the gaps that remain.

## Initial scope

The MVP should prioritize a carefully selected corpus from the Dominican Supreme Court of Justice (SCJ) and Constitutional Court (TC), starting with a tractable legal area rather than attempting the entire Dominican legal system at once.

The first commercial unit of value is a **Precedent & Adverse Authority Report**, not chat access.

## Design principles

1. Primary legal sources are authoritative; model interpretations are not.
2. Retrieval is a tool used by the research agent, not the entire product architecture.
3. Deterministic systems should handle deterministic work: filtering, indexing, citation resolution, metadata, counting, grouping, and provenance.
4. LLMs should handle semantic work: legal issue extraction, case comparison, holding identification, distinctions, and synthesis.
5. Every material claim in a final report must be traceable to source evidence.
6. Supporting and adverse authority must both be searched.
7. Multi-tenant boundaries must exist from the MVP even if early access is free.
8. Expensive normalization should be incremental and reusable.
9. The project must be evaluated by outcomes, not by how impressive the generated prose appears.
10. JurisNexo is a research assistant, not a substitute for professional legal judgment.

## Agent runtime direction

For the MVP, JurisNexo will use **OpenAI Agents SDK** as the default agent runtime instead of continuing to expand a custom general-purpose agent harness. The SDK is infrastructure, not the product architecture and not a commitment to use only OpenAI models.

Model/provider choice is **capability- and benchmark-driven**. Third-party provider adapters are not assumed to be feature-equivalent: structured outputs, multimodal input, tool behavior, usage accounting, tracing, and nested-agent behavior must be tested for the exact SDK/adapter/provider/model combination before a role is assigned to it.

JurisNexo continues to own source preservation, provenance, evidence records, document/case tools, mandatory ingestion/research stage orchestration, Corpus API contracts, authorization, persistence, and benchmarks.

The ingestion path is intentionally explicit:

```text
source artifact
    -> Structure Agent
    -> Structure Auditor
    -> Extraction Agent
    -> Extraction Auditor
    -> Corpus API commit
    -> optional enrichment
```

Dynamic handoffs or agents-as-tools are reserved for bounded specialist work such as difficult OCR, citation resolution, boundary investigation, case analysis, later-treatment research, or adverse-authority search. They must not bypass mandatory business gates.

## Documentation

See [`docs/`](./docs/) for product scope, architecture, research runtime, data model, validation strategy, security, and roadmap.

Key documents for the current agent architecture:

- `docs/13-agent-runtime-and-multi-agent-orchestration.md` — runtime, roles, handoffs, guardrails, evidence, and research-agent architecture;
- `docs/14-agent-runtime-decision-record.md` — ADR selecting OpenAI Agents SDK for the MVP;
- `docs/15-ingestion-agent-pipeline.md` — structure/audit/extraction/audit ingestion pipeline;
- `docs/16-corpus-api-agent-contract.md` — stable API boundary between agents and the system of record;
- `docs/17-agent-methodology-and-benchmark-map.md` — complete mapping of the documented research methodologies to specific layers and metrics;
- `docs/18-migration-plan-custom-harness-to-agents-sdk.md` — comparative migration and retirement criteria;
- `docs/19-documentation-crosswalk.md` — precedence rules between existing architecture documents and the new runtime decision;
- `docs/20-agents-sdk-provider-and-guardrail-compatibility.md` — provider capability, guardrail, tracing, and SDK-upgrade constraints.
