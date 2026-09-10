# JurisNexo — Validation, Metrics, and Market Test

## 1. Objective

The MVP exists to test whether JurisNexo creates enough measurable value for legal professionals to justify continued development and payment.

The product must be evaluated on research outcomes, not on fluency.

## 2. Validation questions

The first market test should answer:

1. Does JurisNexo materially reduce research time?
2. Does it find the precedents users expected?
3. Does it find adverse authority users had missed?
4. Are its citations and descriptions accurate?
5. Can lawyers use the report after verification rather than redo the research?
6. Which legal domains produce the strongest value?
7. How frequently do users return?
8. What depth of research is worth paying for?
9. Do firms value team workspaces, API access, or integrations enough to pay more?
10. Is the product trustworthy enough to become part of a professional workflow?

## 3. Private pilot

The first pilot should involve a small group of trusted legal professionals.

Recommended process:

- ask each tester to provide real or recently completed research questions;
- avoid only synthetic demo questions;
- have the tester independently identify important authorities when possible;
- run JurisNexo;
- ask the tester to verify the report;
- record missing authorities, incorrect interpretations, useful discoveries, and time saved;
- conduct a short structured interview after each research job.

## 4. Core evaluation dataset

Create a Dominican legal research benchmark from real questions.

Each benchmark item should contain, where available:

- research question;
- legal domain;
- expected relevant cases;
- critical/controlling authorities;
- known adverse authority;
- graded relevance judgments;
- material legal factors;
- expected source passages;
- notes from a legal reviewer.

Do not rely exclusively on public foreign legal benchmarks to judge Dominican jurisprudential performance.

## 5. Retrieval metrics

### Recall@K

Measures whether the system retrieves relevant cases.

High recall matters because missing the controlling or adverse precedent can invalidate an otherwise polished report.

Track at minimum:

- Recall@20;
- Recall@50;
- Recall@100.

### nDCG@K

Primary ranking-quality metric.

Use graded relevance, for example:

- 4 = controlling/directly material;
- 3 = highly relevant;
- 2 = useful supporting context;
- 1 = tangential;
- 0 = irrelevant.

Track nDCG@10 and nDCG@20.

### MRR

Useful for questions where finding the first strong precedent quickly matters.

### Precision@K

Measures noise in the candidate set.

## 6. Legal-specific metrics

### Critical Miss Rate (CMR)

The most important safety/product metric.

A critical miss occurs when JurisNexo fails to surface a precedent or authority that a qualified reviewer believes would materially change the research conclusion or legal strategy.

```text
CMR = research jobs with at least one critical miss / total reviewed jobs
```

This metric must be tracked explicitly rather than hidden inside average recall.

### Adverse Authority Recall

Measures whether the system identifies materially contrary, limiting, or distinguishing authority known to the evaluation set.

### Citation Correctness

For each material claim:

- does the cited source exist?
- does the cited page/passage exist?
- does the passage support the claim?
- is the passage the court's reasoning/holding rather than merely a party argument?

### Evidence Completeness

Measures how many material report claims carry adequate source support.

### Authority Accuracy

Measures whether the system appropriately recognizes court hierarchy and stronger authority when ranking/synthesizing.

### Temporal Validity Accuracy

Measures whether later treatment or doctrinal change is handled correctly when relevant.

### Legal Relationship F1

For structured relationships such as:

- follows;
- reiterates;
- distinguishes;
- limits;
- contradicts;
- overrules.

## 7. Report-level human evaluation

Every pilot report should receive simple reviewer scores.

Suggested 1–5 scales:

- usefulness;
- completeness;
- citation trustworthiness;
- quality of case comparison;
- quality of adverse-authority research;
- clarity;
- amount of additional research required.

Ask a decisive question:

> If this report had been available at the beginning, how much of your original research would you still have needed to perform?

Possible responses:

- almost all;
- more than half;
- roughly half;
- limited follow-up only;
- source verification only.

The MVP should aim to move users toward the last two categories.

## 8. Time-saved metric

For real tasks, record:

- estimated manual research duration;
- JurisNexo runtime;
- human verification/follow-up duration;
- total time with JurisNexo.

Calculate:

```text
Time Saved = manual baseline - (JurisNexo wait + human review)
```

A product that saves little professional time has weak commercial value even if technically sophisticated.

## 9. Cost metrics

Track per research job:

- retrieval cost;
- embedding/reranking cost;
- subagent token cost;
- root-agent cost;
- OCR/normalization cost triggered by the run;
- verification cost;
- total compute/provider cost;
- p50 and p95 latency.

Separate ingestion cost from per-query research cost.

## 10. MVP commercial experiment

### Free access

Use free access to reduce friction during early validation, but apply explicit quotas so usage patterns remain measurable.

Possible model:

- free account: small monthly number of standard research jobs;
- limited number of deep-research jobs;
- public corpus only;
- feedback prompt after completed reports.

### Paid hypothesis

Do not lock the final pricing model yet.

Potential monetization dimensions:

- research credits;
- deep-research credits;
- team seats;
- organization-private corpus;
- larger uploads;
- API access;
- integrations;
- export formats;
- priority processing;
- longer retention/history.

The pricing model should be selected after observing which features users repeatedly value.

## 11. Multi-company validation

The product must support more than one organization during the demo so that early architecture does not confuse a single-user prototype with the real commercial boundary.

For each organization track:

- active users;
- research jobs;
- repeated use;
- average cost/job;
- completion rate;
- feedback;
- private upload usage;
- requested integrations;
- willingness-to-pay signal.

## 12. Product analytics

Capture product events such as:

- account created;
- organization created/joined;
- research started;
- research completed;
- report opened;
- citation source opened;
- report exported;
- feedback submitted;
- research rerun/refined;
- quota reached;
- upgrade intent;
- integration requested.

Do not collect unnecessary sensitive content for analytics.

## 13. Go / no-go criteria

Before investing in a large-scale standalone platform, require evidence such as:

- repeat usage from multiple independent legal professionals;
- consistent material time savings;
- high citation correctness;
- acceptable Critical Miss Rate on a growing benchmark;
- users reporting limited follow-up rather than complete redo;
- clear willingness to pay from at least some organizations;
- a credible path from provider cost to positive unit economics.

Exact thresholds should be established after the first pilot establishes a baseline.

## 14. What should not count as validation

Do not mistake the following for product-market evidence:

- friends saying the demo looks impressive;
- high LLM answer scores without legal review;
- indexing a very large number of documents;
- a single lawyer using it once;
- generated reports that are long but unauditable;
- retrieval benchmark gains that do not reduce real research work;
- social-media interest without repeated professional usage.

## 15. Validation principle

The decisive question is not:

> "Is JurisNexo technologically advanced?"

It is:

> "Does JurisNexo reliably save legal professionals enough time or reduce enough research risk that they choose to use it again and eventually pay for it?"
