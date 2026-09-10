# JurisNexo — Benchmark Annotation and Evaluation Protocol

## 1. Purpose

Metrics are only meaningful if relevance judgments and legal conclusions are produced consistently. This document defines how JurisNexo should build and maintain its Dominican legal research benchmark.

## 2. Benchmark unit

Each benchmark item should represent a real research task, not an isolated trivia question.

Required fields where available:

- benchmark item ID;
- research question/fact pattern;
- legal domain;
- jurisdiction/court scope;
- temporal scope;
- expected critical authorities;
- relevant authorities;
- known adverse authorities;
- expected legal issues;
- material factual distinctions;
- supporting source passages;
- reviewer notes;
- provenance of the benchmark question.

## 3. Sources of benchmark questions

Prioritize:

1. recently completed research tasks supplied by practicing lawyers;
2. historical matters where the lawyer knows which authorities proved material;
3. deliberately adversarial variants created from real tasks;
4. synthetic questions only for targeted coverage gaps.

Do not allow the evaluation set to become mostly easy lookup questions.

## 4. Relevance grades

Use graded case relevance:

- `4` — controlling or materially outcome-changing authority;
- `3` — directly on-point/highly persuasive authority;
- `2` — useful supporting/comparative authority;
- `1` — tangential/background;
- `0` — irrelevant.

The annotation should explain why grade 4 or 3 was assigned.

## 5. Critical authority annotation

A case is `critical` when omission could materially change the research conclusion, risk assessment, or professional strategy.

Criticality is separate from generic relevance.

Examples:

- binding higher-authority case directly contrary to the proposed position;
- later decision expressly limiting a leading authority;
- decision establishing a material exception matching the supplied facts.

This label feeds Critical Miss Rate.

## 6. Adverse authority annotation

A case may be adverse because it:

- reaches the opposite result on materially similar facts;
- creates an exception;
- limits/rejects a proposition;
- supplies higher-authority contrary reasoning;
- reveals a procedural distinction that weakens the user's theory.

Annotators should not label every negative-sounding case as adverse.

## 7. Passage/evidence annotation

For critical material propositions, annotate the smallest practical primary-source passage supporting the judgment.

Capture:

- case ID;
- page(s);
- paragraph/section when available;
- role (`holding`, `reasoning`, `party_argument`, `facts`, `dispositive`);
- exact source artifact/version.

This permits citation/evidence evaluation independently of report prose.

## 8. Double review

High-stakes benchmark items should receive at least two independent legal reviews where feasible.

Disagreements should be recorded and adjudicated rather than erased.

Track inter-reviewer agreement for:

- relevance grade;
- critical authority label;
- adverse authority label;
- proposition support.

## 9. Train/dev/test separation

Once domain tuning begins, separate:

- development set for prompt/retrieval iteration;
- validation set for model/parameter selection;
- locked test set for comparable reporting.

Do not repeatedly tune against the same public leaderboard-like set and then call improvements generalization.

## 10. Leakage controls

If a benchmark question came from a user research job, ensure private matter content is not moved into a shared benchmark without explicit permission and suitable anonymization/review.

Public jurisprudence citations can remain public; client facts may not.

## 11. Required evaluation runs

For every meaningful retrieval/agent change, compare at least:

- lexical baseline;
- semantic baseline when enabled;
- current production/best baseline;
- proposed change.

For agent changes, also compare end-to-end report outcomes when practical.

## 12. Retrieval metrics

Track:

- Recall@20/50/100;
- nDCG@10/20;
- MRR;
- Precision@K;
- Critical Authority Recall;
- Adverse Authority Recall.

Report per legal domain and globally. A high average must not hide failure in one domain.

## 13. Evidence/report metrics

Track:

- citation correctness;
- evidence completeness;
- authority accuracy;
- temporal validity accuracy;
- legal relationship precision/recall/F1 when available;
- Critical Miss Rate;
- human-rated usefulness;
- additional research required;
- time saved.

## 14. Statistical caution

Small pilot sets have high variance.

Report:

- sample size;
- confidence intervals or bootstrap intervals where useful;
- number of unique reviewers;
- domain distribution;
- corpus snapshot/version.

Do not present a 10-question improvement as evidence of production reliability.

## 15. Regression gate

Once a minimum benchmark exists, define protected metrics.

A candidate release should be blocked or reviewed if it materially worsens:

- Critical Miss Rate;
- critical/adverse authority recall;
- citation correctness;
- tenant/security invariants.

Small ranking gains do not justify regressions in critical-authority discovery.

## 16. Failure taxonomy

Every evaluated miss should be classified when possible:

- source absent from corpus;
- source ingested but unsearchable;
- query decomposition failure;
- candidate retrieval failure;
- reranking failure;
- subagent relevance error;
- citation traversal failure;
- temporal/authority interpretation failure;
- evidence verifier failure;
- report synthesis error.

This makes metrics actionable.

## 17. MVP benchmark milestone

Initial target:

- 25–50 high-quality real research tasks for development;
- grow toward 100+ before strong reliability claims;
- include supporting, adverse, temporal, fact-pattern, and exact-citation tasks;
- keep a small locked test subset as early as practical.

Quality of annotation matters more than raw benchmark size.
