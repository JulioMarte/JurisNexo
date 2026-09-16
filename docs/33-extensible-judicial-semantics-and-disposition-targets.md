# JurisNexo — Extensible judicial semantics and disposition targets

## Status

This document is the canonical refinement of `28-legal-reality-v2.md` and `31-comprehensive-legal-semantics.md` for judicial opinion type, judicial stance type, contextual judicial authority, and judicial-disposition targets.

The goal is not to invent a universal ontology of world law. The goal is to prevent the database from treating one jurisdiction's vocabulary as the legal universe while retaining deterministic, queryable identities.

## Principle: concepts are extensible identities, source language is evidence

Closed `CHECK (... IN (...))` lists are appropriate for implementation states whose universe JurisNexo controls. They are not appropriate for open-ended legal concepts whose vocabulary varies by jurisdiction, court system, historical period, language, or procedural tradition.

For opinion type, judicial stance and judicial-authority effect, canonical persistence therefore uses concept registries with stable UUID identity and stable internal `code` values. Registry rows may carry jurisdiction metadata and a broader concept. New legally observed concepts can be added without a schema migration.

Compatibility text columns may remain temporarily for existing callers, but they are mirrors of the concept identity. PostgreSQL rejects a compatibility value that contradicts the referenced concept. New code must use the concept FK as canonical truth.

## Judicial opinion type

Canonical registry:

- `judicial_opinion_type_concepts`

Canonical relation:

- `judicial_opinions.opinion_type_concept_id`

The historical `judicial_opinions.opinion_type` field remains a compatibility mirror only. The seeded values such as `majority`, `plurality`, `concurring` and `dissenting` are useful known concepts, not an exhaustive ontology.

A jurisdiction-specific form such as a local `voto razonado`, chamber-specific separate opinion, historical opinion form, or future observed category is represented by a new concept row, not by adding another database enum value.

## Judicial stance

Canonical registry:

- `judicial_stance_concepts`

Canonical relation:

- `judicial_vote_stances.stance_concept_id`

`judicial_vote_stances.stance_type` remains a compatibility mirror. A stance concept is independent from panel membership and from the coarse `decision_votes.vote_type` compatibility summary.

This preserves the existing rule that one judicial officer may have different stances on different propositions, opinions, dispositions, or the whole decision while making the semantic vocabulary extensible.

## Judicial authority is contextual and not intrinsically "precedent"

Canonical registry:

- `judicial_authority_effect_concepts`

Canonical assertion table:

- `judicial_authority_assertions`

Compatibility view:

- `precedential_authority_assertions`

The physical table name no longer assumes that every legal system expresses judicial authority through a common-law precedent ontology. The existing seeded concepts `binding`, `persuasive`, `nonbinding`, `superseded`, `abrogated`, and `unknown` remain available because they describe real contexts, but they are not exhaustive.

A jurisdiction may add concepts representing its actual doctrine, for example an authority effect tied to jurisprudencia constante, doctrina legal, constitutional erga-omnes effect, chamber unification, plenary doctrine, or another system-specific category. JurisNexo must model the observed legal effect rather than force it into `binding` or `persuasive` merely because those values already exist.

Authority remains an assertion in context. Jurisdiction, court, legal matter, proposition, legal-validity interval, system-knowledge interval, basis, and verification metadata remain distinct from the authority-effect concept itself.

The compatibility column `authority_type` mirrors `authority_effect_concept_id`; it is not the canonical identity.

## Judicial disposition targets

A dispositive clause may legally act on more than a claim. Canonical persistence is:

```text
disposition_targets
 ├── target_claim_id
 ├── target_party_role_id
 ├── target_proceeding_id
 ├── target_decision_id
 └── target_proposition_id
```

Exactly one target is present in each row, selected by `target_type`.

### Why `target_party_role_id`, not a bare participant

A dispositive order applies to a legal party in procedural context. A person or organization can participate in different proceedings and in different procedural roles. Therefore `target_type='party'` references `proceeding_party_roles`, not merely `participants` or `legal_entities`.

This prevents statements such as "orders Company X" from losing whether Company X was appellant, respondent, intervenor, accused, prosecutor, or another procedural role in the proceeding being decided.

### Target-specific effects

`disposition_effect_concepts` is the canonical extensible registry of what the disposition does to its target. Every effect concept declares a `target_type`.

Examples include:

- claim: granted, denied, partially granted, inadmissible;
- party: orders, restrains, awards costs against;
- proceeding: remands, terminates, stays;
- decision: affirms, reverses, vacates, annuls, modifies, cassates;
- proposition: adopts, rejects, limits.

These are seed concepts, not an exhaustive list. Adding a newly observed legal effect is data, not a schema migration.

PostgreSQL enforces that an effect concept and its target have the same target type. An effect declared for a claim cannot silently be attached to a decision target.

## Context invariants

The database rejects the following contradictory states:

- a claim target from a proceeding unrelated to the decision containing the disposition;
- a party target whose procedural role belongs to an unrelated proceeding;
- a proposition explicitly bound only to another judicial decision;
- a target row containing zero targets or multiple targets;
- an effect concept whose declared target type differs from the row's target type;
- a compatibility opinion/stance/authority text value that contradicts its canonical concept FK.

Proceeding and decision targets are not overconstrained to a same-proceeding rule. An appellate decision may legitimately remand to another proceeding or act on another judicial decision. Those cross-proceeding/cross-decision legal relationships require correct scope and evidence, but they must not be prohibited merely because they are not the source proceeding itself.

## Compatibility without double truth

The migration preserves transitional compatibility surfaces:

- `judicial_opinions.opinion_type` mirrors the opinion concept code;
- `judicial_vote_stances.stance_type` mirrors the stance concept code;
- `precedential_authority_assertions` is an updatable compatibility view over `judicial_authority_assertions`;
- `claim_effect_concepts` is a claim-only compatibility view over `disposition_effect_concepts`;
- `disposition_claim_effects` is a claim-only compatibility view over `disposition_targets`.

These are not parallel systems of record. The physical canonical records live in the generalized tables and compatibility writes are routed to that same storage.

## What this model deliberately does not claim

This change does **not** claim that JurisNexo now has a completed ontology for every judicial tradition. It removes the schema-level assumption that the current seed vocabulary is complete.

The concept registries should grow from observed primary legal sources, official court metadata, verified jurisdictional doctrine, and reviewed corpus evidence. New concepts should not be invented merely to make the registry look comprehensive.

The same discipline still applies to other compatibility-era fields such as the coarse `decision_votes.vote_type`: if corpus evidence demonstrates that it creates false legal identities, the canonical richer model should be extended rather than expanding another closed enum indefinitely.
