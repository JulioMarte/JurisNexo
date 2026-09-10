# JurisNexo — Research Agent and Report Contract

## 1. Purpose

The research agent is the core user-facing intelligence of JurisNexo.

Its job is not to answer immediately. Its job is to plan, investigate, challenge, verify, and only then synthesize.

The agent should be outcome-driven:

> produce a defensible research memo or explicitly state why the available evidence is insufficient.

## 2. Research lifecycle

```text
Research request
    -> legal issue decomposition
    -> research plan
    -> candidate search
    -> case analysis
    -> citation expansion
    -> adverse-authority search
    -> later-treatment search
    -> evidence aggregation
    -> gap assessment
    -> additional search if needed
    -> claim verification
    -> final report
```

A single retrieval pass is insufficient for deep research.

## 3. Input contract

Accepted MVP inputs may include:

- a legal question;
- a factual scenario;
- a legal proposition to test;
- a pasted excerpt from a pleading or decision;
- optional supporting documents uploaded privately by the organization.

The runtime should derive a structured research brief containing at least:

- primary legal question;
- sub-issues;
- relevant facts supplied by the user;
- court/jurisdiction constraints if known;
- time range if relevant;
- desired output depth;
- unresolved ambiguities.

The MVP should prefer making a reasonable research interpretation and disclose it rather than blocking every run with clarification questions.

## 4. Research plan

The agent should create an internal research plan before expensive analysis.

A plan may include:

- exact legal-reference search;
- lexical search using terms of art;
- semantic search using paraphrased fact patterns;
- search by legal issue;
- search for supporting authorities;
- search for opposite outcomes;
- search for later citing decisions;
- traversal of authorities cited by important cases;
- search for higher-authority cases;
- temporal comparison.

The plan is allowed to change as evidence is discovered.

## 5. Candidate funnel

The runtime should narrow candidates cheaply before expensive model analysis.

Illustrative funnel:

```text
100,000 cases
    -> metadata + exact + lexical + semantic retrieval
1,000 candidates
    -> rank fusion / reranking
100 candidates
    -> bounded subagent review
20-40 materially relevant cases
    -> deep comparison and verification
5-15 authorities in final report
```

These values are illustrative, not hard-coded requirements.

## 6. Subagent roles

The MVP can implement roles logically without requiring different model providers.

### Case analyst

Given one or a few bounded cases, determine:

- relevance;
- issue addressed;
- material facts;
- court reasoning;
- holding;
- outcome;
- cited authority;
- exact evidence location;
- relation to the research proposition.

### Citation tracer

For important cases:

- resolve cited authorities;
- identify frequently cited foundations;
- find later citing decisions;
- flag possible subsequent treatment.

### Adverse researcher

Actively seek evidence that weakens the current working conclusion.

It should search for:

- opposite outcomes;
- exceptions;
- limiting language;
- distinctions;
- later disagreement;
- higher-authority contrary decisions.

### Auditor

The auditor should not expand the argument. It should verify whether proposed report claims are actually supported by cited evidence.

## 7. Structured evidence record

Every material candidate finding should be persisted in a structured form.

Example:

```json
{
  "research_job_id": "...",
  "case_id": "...",
  "claim_type": "holding",
  "proposition": "...",
  "relationship": "supporting",
  "authority_level": "...",
  "page_start": 17,
  "page_end": 18,
  "source_excerpt_ref": "...",
  "analysis_model": "...",
  "confidence": 0.91,
  "verification_status": "pending"
}
```

The final report should consume verified evidence records rather than regenerate claims from raw search results.

## 8. Research completion contract

The agent should not stop merely because it has found supporting cases.

For a standard deep-research run, the completion checklist should include, when applicable:

- legal issue identified;
- multiple search formulations attempted;
- strongest apparent authority identified;
- supporting authorities reviewed;
- adverse/contrary search performed;
- later treatment of key authority checked;
- important cited precedents checked;
- court hierarchy considered;
- temporal relevance considered;
- material factual distinctions identified;
- material report claims verified;
- unresolved conflicts explicitly documented.

If one or more required checks cannot be satisfied, the report should state the gap.

## 9. Research sufficiency

Research sufficiency is not a vague model feeling.

The runtime should combine:

- completion checklist state;
- number and diversity of search attempts;
- authority coverage;
- adverse-authority coverage;
- unresolved evidence conflicts;
- source quality;
- verification status.

Possible terminal states:

- `SUFFICIENT_HIGH_CONFIDENCE`;
- `SUFFICIENT_WITH_LIMITATIONS`;
- `INSUFFICIENT_EVIDENCE`;
- `SOURCE_QUALITY_BLOCKED`;
- `BUDGET_LIMIT_REACHED`;
- `FAILED`.

## 10. Python workspace

The root agent may use a sandboxed Python environment for deterministic or aggregate tasks such as:

- grouping candidate decisions by year;
- identifying citation frequency;
- creating a local citation graph;
- comparing structured legal factors;
- deduplicating candidates;
- calculating overlap between supporting and adverse authority;
- constructing timelines;
- sorting by authority/date/relevance;
- generating intermediate tables.

Python should complement, not replace, stable search and data APIs.

## 11. Report contract

The default MVP report should contain:

### A. Research question

The question JurisNexo actually investigated.

### B. Short conclusion

A concise answer with calibrated confidence and no unsupported certainty.

### C. Controlling or highest-authority decisions

For each:

- case identifier;
- court/chamber;
- date;
- why it matters;
- relevant holding;
- source location.

### D. Supporting line

Relevant decisions supporting the working conclusion.

### E. Adverse or conflicting authority

Cases that contradict, limit, or materially weaken the conclusion.

### F. Material distinctions

Key factual or procedural differences that may explain different outcomes.

### G. Evolution of the jurisprudence

Only when supported and material.

### H. Unresolved issues and limitations

What the research could not establish reliably.

### I. Evidence table

Every material proposition should point to an accessible primary-source location.

## 12. Citation requirements

A final legal proposition should not be presented as established unless:

- its source has been retrieved;
- the cited page/passage exists;
- the evidence actually supports the proposition;
- the proposition is not merely a party's argument unless labeled as such;
- relevant authority and temporal status have been considered where material.

The interface should make it easy to open the original source.

## 13. Confidence semantics

Confidence should describe evidence quality, not model self-confidence.

Inputs may include:

- source quality;
- number of directly relevant authorities;
- agreement among authorities;
- authority hierarchy;
- recency/later treatment;
- verification completeness;
- unresolved conflicts.

Suggested user-facing bands:

- High;
- Moderate;
- Low;
- Insufficient evidence.

## 14. Research trace

JurisNexo may expose a factual research trace such as:

```text
Searched: "..."
Found: 64 candidates
Reviewed deeply: 18
Followed citations from: 4 key decisions
Later decisions checked: 11
Adverse search performed: yes
Material claims verified: 9/9
```

Do not expose private model chain-of-thought. The trace should show actions and evidence, not hidden reasoning tokens.

## 15. Cost controls

Every job should have resource budgets:

- maximum candidate pool;
- maximum subagent calls;
- maximum deep-normalization promotions;
- token/cost budget;
- wall-clock timeout;
- retry policy.

Budget exhaustion should produce a partial report with limitations rather than silently lower evidence standards.

## 16. Non-negotiable behavior

The agent must never optimize only for finding authority that supports the user's desired answer.

For material legal questions, adverse-authority search is part of the product contract.
