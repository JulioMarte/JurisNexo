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

## Documentation

See [`docs/`](./docs/) for product scope, architecture, research runtime, data model, validation strategy, security, and roadmap.
