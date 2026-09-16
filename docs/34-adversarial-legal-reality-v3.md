# JurisNexo — Adversarial Legal Reality V3

## Status

Normative pre-ingestion refinement of `28-legal-reality-v2.md`, `31-comprehensive-legal-semantics.md`, and `33-extensible-judicial-semantics-and-disposition-targets.md`.

Alembic revisions: `0036_legal_reality_v3` and `0037_harden_legal_reality_v3`.

This revision implements the adversarial review of the database against difficult real litigation rather than against a one-row-per-case abstraction.

## 1. A litigation family is not procedural ancestry

`controversy_proceedings` answers: **which proceedings belong to the same litigation family and in what broad family role?**

It does not answer: **which proceeding appealed, reviewed, cassated, reopened, enforced, consolidated with, or was remanded from which other proceeding?**

Canonical procedural ancestry is now:

```text
legal_proceeding
    -> proceeding_relations
        -> legal_proceeding
```

`proceeding_relation_concepts` is extensible. Seed concepts are examples observed across legal systems, not a universal ontology.

This makes histories such as the following losslessly representable:

```text
P2 appeal_of P1
P4 cassation_of P2
P6 remand_from P4
P3 incident_to P1
P5 appeal_of P3
```

`consolidated_with` and `related_to` are symmetric concepts. Canonical UUID ordering prevents storing both directions as duplicate facts.

## 2. Claims have lineage across instances

`legal_claims.parent_claim_id` remains an intra-proceeding hierarchy. That is correct for a principal claim and subsidiary requests within one proceeding, but it must not be abused to connect first-instance claims with appeal or cassation grounds.

Canonical cross-instance lineage is:

```text
legal_claim
    -> claim_relations
        -> legal_claim
```

Examples include `challenges`, `reviews`, `derives_from`, `renews`, `narrows`, `expands`, and `abandons`.

The database deliberately permits the two claims to belong to different proceedings while requiring the same corpus scope.

## 3. Judicial decision is an identity; juridical act form is a concept

A court may issue a judgment, interlocutory judgment, order, resolution, decree, advisory opinion, or a jurisdiction-specific form that JurisNexo has not yet observed.

Canonical type identity is therefore `judicial_decisions.act_type_concept_id -> adjudicative_act_type_concepts`.

The compatibility default is `decision`, meaning only that the precise juridical form has not yet been classified. Extraction should replace that default when primary evidence supports a more specific type.

Adding a newly observed act form is data, not a schema migration.

## 4. Judicial events are extensible; states remain separate

`decision_legal_status_events` remains a point-event ledger. The old `status_type` string is now a compatibility mirror of `event_type_concept_id -> judicial_event_type_concepts`.

The registry can grow with observed events such as clarification, correction, supplementation, reconsideration, remittance, or jurisdiction-specific acts without changing database CHECK lists.

Durative states such as finality, res judicata, stay, suspension, and enforceability remain in `decision_legal_states`. V3 does not collapse events and states back together.

## 5. A dispositive clause is not the same thing as its legal actions

A single textual dispositive clause may say, in substance:

```text
partially cassates the prior decision,
preserves the remaining dispositions,
remands the damages issue,
and awards costs.
```

Therefore the canonical structure is now:

```text
judicial_decision_disposition     # textual clause
    -> judicial_disposition_actions   # normalized legal actions
        -> disposition_targets        # one or more typed targets
```

`disposition_targets.effect_concept_id` remains temporarily as a compatibility mirror, but the canonical action semantic is `judicial_disposition_actions.effect_concept_id` through `action_id`.

This permits one clause to contain several actions and one action to operate on multiple targets without duplicating the clause text.

## 6. Controversy membership is intentionally narrower

`controversy_proceedings.relation_type` no longer pretends that values such as `appeal`, `cassation`, `consolidated`, or `severed` identify ancestry. Existing pre-ingestion values are normalized to broad family roles (`review` or `related`).

The exact relationship belongs in `proceeding_relations`.

## 7. What V3 deliberately keeps

The adversarial review did **not** discard the strongest parts of the existing model:

- source artifact/page/document identity remains separate from legal identity;
- legal propositions remain separate from source text and system assertions;
- legal validity time remains separate from JurisNexo knowledge time;
- parties remain separate from procedural roles and representation;
- judges, panel membership, opinions, authorship, votes and scoped stances remain separate;
- legal norms remain contextual and bitemporal;
- judicial authority remains contextual rather than a global precedent score.

The correct response to the review was therefore normalization, not a ground-up replacement.

## 8. Pre-ingestion baseline policy

The migration history records how JurisNexo discovered the domain and is intentionally preserved during verification. Before the first irreversible mass-ingestion release, the project should produce a clean installation baseline representing the verified post-V3 schema and archive the exploratory chain in Git history/tagging.

That baseline operation must happen only after:

1. the full PostgreSQL integration suite passes from an empty database;
2. schema invariants are inspected against the migration head;
3. no production corpus depends on the exploratory revision chain;
4. application callers no longer treat compatibility mirrors as canonical truth.

Squashing earlier would make adversarial comparison and regression diagnosis harder; squashing after mass ingestion would be unnecessarily dangerous.
