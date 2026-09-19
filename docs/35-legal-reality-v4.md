# JurisNexo — Legal Reality V4

## Status

This document is the current normative refinement of the persisted legal model after `34-adversarial-legal-reality-v3.md`.

Read the legal-model documents in this order:

`02` -> `28` -> `31`/`33` -> `34` -> **`35`**.

V4 preserves the identities and cardinalities established by V3 unless this document explicitly changes them.

## Why V4 exists

V3 fixed major false singularities: controversy versus proceeding versus decision, cross-instance claim lineage, partial judicial stances, open legal vocabularies, and canonical disposition actions. The remaining problem was not lack of normalization. It was that several legally different things were still represented by the same primitive.

V4 therefore makes four targeted changes:

1. a legal question/issue becomes distinct from a legal proposition or procedural claim;
2. a party allegation or judicial factual finding becomes distinct from a legal proposition;
3. a dispositive action carries typed semantic arguments rather than one undifferentiated target type;
4. entity identity resolution becomes auditable history rather than destructive merging or name similarity.

V4 also establishes a shared concept substrate for **new** cross-jurisdiction vocabularies without attempting a risky big-bang migration of every mature specialized concept registry.

## Non-negotiable model principles

### Source evidence is not canonical truth

Source artifacts, observations, interpretive assertions and canonical resolutions remain distinct. A model confidence score never upgrades a claim into verified legal truth by itself.

### Unknown is not absent

`NULL` means unknown/unclassified unless a column's contract explicitly says otherwise. JurisNexo must not fabricate a classification merely to satisfy a schema shape.

### Legal classifications may be contextual

A similar label in two jurisdictions does not establish conceptual identity. Shared `legal_concepts` may be jurisdiction-specific and linked with relations such as `equivalent`, `close_match`, `broader`, `narrower` or `historical_successor`.

### Interpretive identity is immutable

A material change to a legal issue's question, a factual proposition's text/kind, or a legal proposition's semantic text creates a new identity. Corrections and changing knowledge are represented by supersession/resolution history rather than silent rewriting.

## Shared concept foundation

New cross-domain legal vocabularies should normally use:

- `concept_schemes`;
- `legal_concepts`;
- `legal_concept_aliases`;
- `legal_concept_edges`.

This is not permission to migrate every existing `*_concepts` table mechanically. Existing specialized registries remain canonical until a separate migration demonstrates that consolidation reduces complexity without losing domain invariants.

Concept identity is `(scheme, jurisdiction, code)`, not the English/Spanish label. Two concepts with similar wording may coexist in separate jurisdictions and be explicitly related.

Hierarchy edges must remain acyclic.

## Legal issues

`legal_issues` represents the legal question a tribunal, claim or proposition raises or answers.

A legal issue is **not**:

- a procedural claim;
- a topic tag;
- a holding;
- a legal proposition merely phrased as a question.

`legal_issue_subjects` relates one issue to decisions, proceedings, claims and propositions using typed concepts such as `raises`, `addresses`, `answers`, `qualifies` and `rejects`.

`legal_issue_evidence` records the source support for the issue formulation. A verified issue requires persisted evidence.

Example:

```text
Issue: ¿Es admisible este recurso de casación?
  raises     -> appeal/cassation claim C1
  addressed  -> judicial decision D1
  answers    <- legal proposition P1: "El recurso es inadmisible..."
```

## Factual propositions

`factual_propositions` stores source-grounded factual assertions without pretending that every assertion is a judicial finding.

Its kind is an open concept. Baseline kinds include:

- allegation;
- denial;
- admission;
- stipulation;
- judicial finding;
- presumption;
- background fact;
- evidentiary fact.

`factual_proposition_subjects` records who/what the fact is connected to: judicial decision, proceeding, claim or procedural party role.

`factual_proposition_evidence` preserves source support.

The following are intentionally different rows/entities even when their natural-language text is identical:

```text
Party A alleges: "no fui notificado"
Court finds:     "no fue notificado"
```

A factual allegation must never be promoted into a judicial finding merely because an extractor is confident in the text extraction.

`legal_propositions` no longer accepts `issue`, `material_fact` or `procedural_fact` as proposition types at the V4 head. Those concepts have first-class homes.

## Confidence dimensions

Where V4 stores confidence, it distinguishes:

- `extraction_confidence`: confidence that source material was read/extracted correctly;
- `semantic_confidence`: confidence in the legal/semantic classification of that material.

A high extraction confidence does not imply a high semantic confidence, and neither is a substitute for verification evidence.

## Dispositive actions and arguments

V3 represented:

```text
disposition clause
  -> action(effect)
      -> typed target
```

That was insufficient for real dispositive grammar. A payment order, for example, can have an obligor, beneficiary, amount, currency and affected claim. A remand can have both a proceeding/object and a destination tribunal.

V4 therefore represents:

```text
disposition clause
  -> judicial_disposition_action(effect)
      -> judicial_disposition_action_argument(role, object/value)
```

Baseline argument roles include:

- object;
- obligor;
- beneficiary;
- destination;
- claim;
- legal provision;
- amount;
- scope;
- condition;
- other.

Argument object/value kinds include legal references and typed literals:

- claim;
- procedural party role;
- proceeding;
- decision;
- proposition;
- legal provision;
- court/court organ;
- text;
- number;
- money;
- date;
- duration;
- percentage.

The old `disposition_targets` table and `disposition_effect_concepts.target_type` are removed at the V4 head. Existing V3 targets are migrated losslessly as `object` arguments before removal.

`disposition_effect_argument_rules` describes baseline expected argument grammar for known effects. It is intentionally a validation aid, **not** a general legal reasoning engine. New jurisdiction-specific effects may add data rather than DDL.

The procedural-context protections from V3 remain mandatory: a dispositive action cannot borrow a claim or party role from an unrelated proceeding, and a proposition bound to another decision cannot silently become the source decision's dispositive object.

## Entity identity resolution

`legal_entities` continues to preserve legal-world entity identities and role specializations.

V4 adds:

- `entity_identity_assertions`;
- `entity_identity_assertion_evidence`;
- `entity_identity_resolutions`.

Name similarity is only candidate evidence. A verified identity assertion requires persisted evidence. A canonical resolution must point to a matching verified positive identity assertion.

Observed entities remain addressable after resolution. JurisNexo must not delete an observed `J. Pérez` row merely because it later resolves that row to canonical `Juan Pérez Gómez`.

Resolutions are bitemporal in system knowledge (`known_from` / `known_to`), so later corrections do not erase what JurisNexo previously believed.

## Evidence and verification

For V4 legal issues, factual propositions and entity identity assertions, `verification_status='verified'` requires persisted evidence. Human review may be the evidence/verification method, but a magic string in `verification_method` is not itself evidence.

Confidence and verification are separate dimensions.

## Trigger policy

Triggers introduced by V4 are limited to semantic invariants that ordinary FK/UNIQUE/CHECK constraints cannot express cleanly, including:

- immutability of interpretive identity;
- same-case/proceeding context of action arguments;
- evidence requirements for verified interpretive identities;
- non-overlapping entity-resolution knowledge history;
- concept hierarchy acyclicity.

V4 does not introduce synchronization triggers or duplicate writable compatibility mirrors.

## Migration safety boundary

The repository is still before mass canonical legal ingestion. Nevertheless, V4 refuses to silently reinterpret existing `legal_propositions` whose type is `issue`, `material_fact` or `procedural_fact`. Migration `0046` aborts if such rows exist. A populated deployment must explicitly transform those rows into `legal_issues` / `factual_propositions` with evidence before upgrading.

That failure is intentional. Silent coercion would destroy the epistemic distinction V4 is designed to protect.

## Required adversarial behavior

The canonical V4 schema must be able to represent and test at least:

1. multiple proceedings linked by appeal/cassation/remand;
2. cross-instance claim lineage;
3. one decision connected to multiple proceedings;
4. partial/mixed judicial stances;
5. a dispositive clause with multiple actions and one action with multiple semantic arguments;
6. allegation versus judicial finding without truth collapse;
7. one legal issue with competing/qualifying propositions;
8. entity identity candidates and later corrected resolution;
9. contradictory source observations without destructive overwrite;
10. historical validity time distinct from JurisNexo knowledge time.

## What V4 deliberately does not build

V4 is not:

- an RDF/OWL rewrite;
- a universal nodes/edges store;
- a Neo4j migration;
- a general theorem prover;
- a complete legal-rule DSL;
- a reason to replace PostgreSQL;
- a big-bang consolidation of every specialized concept registry.

The relational PostgreSQL core, explicit graph-like relation tables, provenance and bitemporal assertions remain the system of record.

## Definition of done

V4 is ready for large-scale canonical judicial ingestion only when:

- fresh PostgreSQL -> `alembic upgrade head` succeeds;
- all existing V3 guarantees that V4 does not supersede remain green;
- V4 legal-model tests are green;
- no old disposition target compatibility surface remains;
- issue/fact identity does not leak back into `legal_propositions`;
- verified V4 interpretive identities require evidence;
- same-proceeding/same-decision dispositive context constraints are enforced by PostgreSQL;
- documentation and the current guarantee inventory describe the same canonical model.
