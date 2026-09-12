# JurisNexo

JurisNexo is an early-stage legal-intelligence project focused first on Dominican judicial decisions and other public legal materials.

The MVP goal is to ingest messy historical/current legal sources, preserve their provenance, normalize them into a trustworthy corpus, expose that corpus through stable APIs, and support evidence-grounded legal research workflows that can be measured against real lawyer tasks.

## Current architectural direction

JurisNexo uses a clear separation between **agent runtime infrastructure** and **domain-owned legal intelligence**.

For the MVP, the default agent runtime is **OpenAI Agents SDK**. It provides generic agent mechanics such as tool loops, structured outputs, agents-as-tools, handoffs, guardrail hooks, tracing, and model invocation plumbing. This does **not** mean JurisNexo is restricted to OpenAI models; model/provider choice remains task- and benchmark-driven.

JurisNexo continues to own the components that define product quality and trust:

- source acquisition and immutable artifact preservation;
- canonical identity, checksums, and page provenance;
- document/case tools;
- ingestion stage orchestration;
- Corpus API contracts;
- evidence and verification records;
- tenant/security boundaries;
- retrieval/search behavior;
- legal research completion contracts;
- benchmarks and release gates.

The ingestion pipeline is intentionally explicit rather than an uncontrolled agent swarm:

```text
source artifact
    -> Structure Agent
    -> Structure Auditor
    -> Extraction Agent
    -> Extraction Auditor
    -> Corpus API commit
    -> optional enrichment
```

The research system operates later over the normalized corpus through stable APIs and can use bounded specialist agents for case analysis, citation tracing, adverse-authority research, and claim verification.

## Documentation

Start with:

- `docs/00-product-vision-and-mvp.md` — product goal and MVP scope;
- `docs/01-system-architecture.md` — overall platform architecture;
- `docs/03-research-agent-and-report-contract.md` — legal research-agent contract;
- `docs/11-benchmark-annotation-and-evaluation-protocol.md` — evaluation methodology;
- `docs/13-agent-runtime-and-multi-agent-orchestration.md` — agent runtime decision and role boundaries;
- `docs/14-agent-runtime-decision-record.md` — architecture decision record for OpenAI Agents SDK;
- `docs/15-ingestion-agent-pipeline.md` — structure/audit/extraction/audit ingestion design;
- `docs/16-corpus-api-agent-contract.md` — stable API boundary between agents and the corpus.

The repository documentation is the architectural source of truth. Experiments and benchmarks may challenge those decisions, but changes should be documented explicitly rather than accumulating as implicit harness behavior.
