# JEV / System One engineering guidelines

Status: CURRENT DESIGN AND BENCHMARK CONTRACT.

This document defines how JurisNexo uses JEV. It is derived from the first-party TypeSafe Agent Skill and live TypeSafe/OpenRouter documentation, but JurisNexo remains the owner of its routing policy, evidence model, thresholds and promotion decisions.

Primary references:

- TypeSafe Agent Skill: https://github.com/typesafe-ai/skills/tree/main/skills/typesafe-ai
- TypeSafe live docs index: https://docs.typesafe.ai/llms.txt
- OpenRouter TypeSafe/JEV model page: https://openrouter.ai/typesafe

Live vendor docs are the source of truth for provider/API details. This document controls JurisNexo architecture and safety policy.

## 1. Mental model

JEV is not a generative reasoning model.

JEV supplies small typed semantic judgments that code composes:

- `Choice`: choose one mutually competing outcome;
- `Noul`: probability that one condition holds;
- `Score`: position on an explicitly ordered rubric.

Code owns:

- deterministic facts;
- calculations;
- authorization;
- thresholds;
- side effects;
- retries;
- persistence;
- escalation;
- acceptance of evidence.

JEV never becomes source-of-truth legal evidence.

## 2. What belongs in JEV

Good JurisNexo uses include:

- transcription-quality classification;
- OCR/normalization escalation routing;
- legal-critical-damage detection;
- deciding whether visual verification is warranted;
- selecting among already-extracted candidate values;
- verifying proposed extracted values against evidence;
- citation-support classification;
- document/section classification;
- retrieval reranking;
- semantic drift classification;
- low-cost sentinel checks.

Bad uses include:

- free-form legal analysis;
- summarization;
- drafting;
- open-ended extraction of arbitrary strings;
- arithmetic/counting;
- authorization;
- irreversible actions;
- replacing deterministic validation;
- treating probability as factual truth.

## 3. Context-window policy

OpenRouter currently exposes JEV with a 32k context window.

JurisNexo does not target the hard edge.

Default working policy:

- hard provider context: 32,000 tokens;
- target total request budget: 24,000 estimated tokens;
- reserved instruction/question/state headroom: at least 4,000 tokens;
- default max records per batch: 20;
- never silently truncate an oversized record;
- split/route oversized material before inference.

The target is deliberately conservative because token estimation, provider serialization and question definitions all consume context.

The batching implementation must measure only the questions that are actually sent with the records in each batch. It must not count every corpus question in every batch.

## 4. State design

Send the smallest state that preserves the judgment.

Prefer structured context such as:

- source/institution;
- document identifier;
- page/section identifier;
- deterministic QA observations;
- candidate values;
- evidence excerpt;
- relevant neighboring text;
- known relationships.

Do not fill the 32k window merely because it is available.

For long decisions:

1. preserve full source bytes;
2. normalize structure;
3. segment into meaningful regions;
4. identify deterministic risk/candidates;
5. batch only relevant regions into JEV;
6. aggregate judgments in code;
7. escalate unresolved cases.

## 5. Question design

Each question must ask one coherent semantic judgment.

Examples:

- `Choice`: acceptable / material_error / uncertain;
- `Noul`: does apparent damage affect legally critical tokens?;
- `Noul`: should this page be visually checked?;
- `Choice`: supported / contradicted / insufficient;
- `Score`: ordered risk rubric.

Question IDs are code identifiers, not semantic instructions. The question text/criteria must contain the complete meaning.

Independent questions over the same state should be sent together. They execute in parallel.

A second JEV call is justified only when the first result is needed to obtain new evidence, create new candidates or determine a materially different question set.

## 6. Candidate-first extraction

JurisNexo should prefer:

deterministic/parser/reasoning model generates candidates
→ JEV selects/verifies among known candidates
→ code validates and persists

over:

JEV invents an arbitrary value.

Examples:

- decision date;
- case number;
- article/law reference;
- court chamber;
- procedural outcome;
- citation relationship.

If the correct value may be absent, include an explicit no-match/insufficient option.

## 7. Probability policy

Raw distributions are durable observations.

Do not immediately collapse them to one boolean.

Persist where practical:

- model identity;
- requested model alias;
- probabilities;
- selected/argmax outcome;
- usage;
- cost;
- benchmark/run identity;
- policy/config hash.

Important distinctions:

- Noul near 0.5 means uncertainty between yes/no, not medium severity;
- Choice confidence reflects distribution concentration, not factual truth;
- typed output guarantees shape, not correctness.

## 8. Shadow-first promotion

JEV remains advisory until benchmark evidence supports promotion.

A routing threshold must be selected on calibration data and evaluated unchanged on holdout data.

Never:

- tune thresholds on holdout;
- promote based on HTTP success;
- promote from one or two examples;
- reuse demo/cookbook thresholds as production rules;
- choose 0.5 merely because it is intuitive.

Promotion evidence should include at minimum:

- corruption recall;
- false-negative rate;
- false-rejection/escalation rate;
- calibration/Brier-style error;
- legal-critical failure analysis;
- model/version;
- token usage;
- cost;
- latency;
- sentinel false negatives.

For legal evidence routing, false negatives are normally more important than unnecessary escalation.

## 9. Current normalization questions

The current first-layer quality judgment uses:

1. transcription quality:
   - acceptable
   - material_error
   - uncertain
2. legal-critical damage:
   - Noul probability
3. visual review needed:
   - Noul probability

These are intentionally separate dimensions.

A candidate that looks generally readable may still have high legal-critical risk.

## 10. Escalation funnel

Target architecture:

deterministic checks
→ JEV System One judgments
→ DeepSeek V4.1 Flash/high for difficult reasoning
→ visual verification for image-grounded uncertainty
→ human review for unresolved/high-risk cases

Do not send every document to every model.

JEV should be the high-volume low-cost semantic layer. DeepSeek and visual inference should see a much smaller selected subset.

## 11. Claim verification

JEV is especially useful after candidate extraction.

Given:

- evidence excerpt;
- field name;
- proposed value;

ask:

- supported;
- contradicted;
- insufficient.

This evaluates evidence/value consistency without asking JEV to generate the value.

Claim verification must use the same safe context-budget batching rules as quality routing.

## 12. Calibration and holdout discipline

For controlled corruption experiments, keep the clean record and its corrupted sibling in the same data split. Split by source case, not by individual transformed record.

The calibration set may be used to choose candidate thresholds.

The holdout set:

- must not influence threshold selection;
- evaluates the frozen candidate threshold;
- reports false negatives explicitly.

A source-derived born-digital reference is valid evidence for measuring OCR/transcription fidelity on that population, but it is not a substitute for human-verified gold on historical scans.

## 13. Sentinel policy

Even after promotion, keep permanent sampling of low-risk/autoaccepted cases.

Sentinel review estimates router false negatives under real distribution drift.

If sentinel false negatives rise materially:

- stop or narrow autoaccept;
- investigate source/model drift;
- recalibrate before restoring automatic routing.

## 14. Security and authority

JEV must never:

- receive unrestricted DB/storage credentials;
- authorize users;
- approve destructive mutations;
- overwrite primary evidence;
- become an implicit legal conclusion.

External-provider egress must pass JurisNexo provider/privacy policy.

## 15. Current promotion state

Current state: SHADOW / BENCHMARKING.

The existence of `JevRoutingPolicy` defaults does not mean those values are production-calibrated.

Active autoaccept requires explicit evidence-backed promotion and documentation update.
