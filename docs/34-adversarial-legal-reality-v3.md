# JurisNexo — Adversarial Legal Reality V3

## Status

Normative pre-ingestion refinement of `28-legal-reality-v2.md`, `31-comprehensive-legal-semantics.md`, and `33-extensible-judicial-semantics-and-disposition-targets.md`.

Alembic revisions: `0036_legal_reality_v3`, `0037_harden_legal_reality_v3`, `0038_cleanup_v3_backfill`, and `0039_remove_v3_legacy`.

This revision implements the adversarial review of the database against difficult real litigation rather than against a one-row-per-case abstraction. Revision `0039` closes the pre-ingestion normalization boundary by removing compatibility mirrors instead of carrying duplicate legal truth into the long-lived schema.

## 1. A litigation family is not procedural ancestry

`controversy_proceedings` answers: **which proceedings belong to the same litigation family and in what broad family role?**

It does not answer: **which proceeding appealed, reviewed, cassated, reopened, enforced, consolidated with, or was remanded from which other proceeding?**

Canonical procedural ancestry is:

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

`legal_claims.parent_claim_id` remains an intra-proceeding hierarchy. It must not be abused to connect first-instance claims with appeal or cassation grounds.

Canonical cross-instance lineage is:

```text
legal_claim
    -> claim_relations
        -> legal_claim
```

The database deliberately permits the two claims to belong to different proceedings while requiring the same corpus scope.

## 3. Judicial decision is an identity; juridical act form is a concept

A court may issue a judgment, interlocutory judgment, order, resolution, decree, advisory opinion, or a jurisdiction-specific form that JurisNexo has not yet observed.

Canonical type identity is therefore:

```text
judicial_decisions.act_type_concept_id
    -> adjudicative_act_type_concepts
```

There is no compatibility text column and no default that silently means `decision`. When the juridical act form is known, ingestion stores its concept identity explicitly. When the evidence is not yet sufficient to classify the act, `act_type_concept_id` is `NULL`; JurisNexo must preserve that epistemic uncertainty rather than manufacture a generic classification through a database default.

Adding a newly observed act form is data, not a schema migration.

## 4. Judicial events are extensible; states remain separate

`decision_legal_status_events` remains a point-event ledger whose canonical type is only:

```text
event_type_concept_id -> judicial_event_type_concepts
```

The former `status_type` mirror and its synchronization trigger are removed.

Durative states such as finality, res judicata, stay, suspension, and enforceability remain in `decision_legal_states`. V3 does not collapse events and states back together.

## 5. A dispositive clause is not the same thing as its legal actions

A single textual dispositive clause may say, in substance:

```text
partially cassates the prior decision,
preserves the remaining dispositions,
remands the damages issue,
and awards costs.
```

The canonical structure is:

```text
judicial_decision_disposition          # textual clause
    -> judicial_disposition_actions    # normalized legal actions/effects
        -> disposition_targets         # one or more typed targets
```

The legal effect lives only on `judicial_disposition_actions.effect_concept_id`. `disposition_targets` no longer duplicates that effect. The pre-V3 model did not have action identity; `0038` removes redundant textless inferred actions created during migration, and `0039` removes the compatibility mirror and trigger once canonical action identity exists.

The claim-only compatibility views `claim_effect_concepts` and `disposition_claim_effects` are also removed. Their names encode the superseded assumption that a disposition can only affect a claim; retaining them would keep that obsolete model discoverable as if it were still supported.

## 6. Controversy membership is intentionally narrower and extensible

A broad role inside a litigation family is not procedural ancestry, but it is still a legal classification. It therefore must not be frozen in a jurisdiction-sensitive `CHECK` list.

Canonical family-role identity is:

```text
controversy_proceedings.relation_concept_id
    -> controversy_membership_role_concepts
```

The former `relation_type` text column and closed `CHECK` are removed. New observed family roles can be added as data. Exact proceeding-to-proceeding ancestry remains exclusively in `proceeding_relations`.

## 7. Canonical-only legal category policy

For legal categories generalized by Legal Reality V3, the concept FK is the only writable truth. The following compatibility surfaces are intentionally removed before mass ingestion:

- `judicial_opinions.opinion_type`;
- `judicial_vote_stances.stance_type`;
- `judicial_authority_assertions.authority_type`;
- `decision_legal_status_events.status_type`;
- `disposition_targets.effect_concept_id`;
- `controversy_proceedings.relation_type`;
- compatibility views `precedential_authority_assertions`, `claim_effect_concepts`, and `disposition_claim_effects`;
- synchronization triggers/functions whose only purpose was to keep those mirrors aligned;
- the compatibility default for `judicial_decisions.act_type_concept_id`.

Removing the act-type default does **not** mean inventing a type is mandatory. Unknown classification is represented by `NULL`; a known classification is represented only by `act_type_concept_id`.

Rule: if a category exists because a legal system can classify an act, role, relation, event, stance, authority effect, or disposition differently, represent it through an extensible concept identity. `CHECK` constraints remain appropriate for JurisNexo-controlled workflow states and structural invariants such as positive ordinals, coherent intervals, exactly-one-target rules, code syntax, and same-scope integrity.

## 8. What V3 deliberately keeps

The adversarial review did **not** discard the strongest parts of the existing model:

- source artifact/page/document identity remains separate from legal identity;
- legal propositions remain separate from source text and system assertions;
- legal validity time remains separate from JurisNexo knowledge time;
- parties remain separate from procedural roles and representation;
- judges, panel membership, opinions, authorship, votes and scoped stances remain separate;
- legal norms remain contextual and bitemporal;
- judicial authority remains contextual rather than a global precedent score.

The correct response to the review was normalization, not a ground-up replacement.

## 9. Pre-ingestion baseline policy

The exploratory migration history is preserved while this model is being verified. Before the first irreversible mass-ingestion release, JurisNexo should create a clean installation baseline representing the verified canonical schema and archive the exploratory chain in Git history/tagging.

That baseline operation must happen only after:

1. the full PostgreSQL integration suite passes from an empty database;
2. schema invariants are inspected against the migration head;
3. no production corpus depends on the exploratory revision chain;
4. no deprecated compatibility mirrors or aliases remain in the canonical schema;
5. legal-domain open vocabularies are represented as concept identities rather than jurisdiction-sensitive `CHECK` lists.

Squashing earlier would make adversarial comparison and regression diagnosis harder; squashing after mass ingestion would be unnecessarily dangerous.
