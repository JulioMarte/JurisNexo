# Comprehensive legal semantics

Status: normative architecture for the current schema, refined by `28-legal-reality-v2.md` where that document defines later pre-ingestion identity/cardinality rules.

This document closes the remaining structural gaps between a document corpus and a legal system of record. The core rule is that JurisNexo must model distinct legal facts as distinct identities instead of compressing them into convenient strings or document edges.

## Two clocks, not one

Legal validity and JurisNexo knowledge are independent dimensions.

- `valid_from` / `valid_to`: when a proposition about law is legally applicable.
- `known_from` / `known_to`: when JurisNexo possessed that proposition.

A later correction appends a new knowledge interval. It does not rewrite what JurisNexo knew yesterday. Knowledge intervals for the same version cannot overlap, so an as-of query has one coherent answer.

`legal_instrument_version_knowledge` and `legal_provision_version_knowledge` are the canonical bitemporal history layer. The stable version tables identify the juridical version; the knowledge tables preserve changing knowledge about it.

## Source authority is evidence, not a magic rank

`legal_version_authority_assessments` records whether a particular source/version is an official primary text, official gazette publication, official consolidation, official correction, editorial consolidation, historical copy, or unknown source, and records the assessment basis.

JurisNexo must not silently choose an editorial consolidation over an official source because of a numeric score. If authoritative sources conflict, the conflict remains explicit until resolved.

## Institutions

`legal_authorities` identifies legislatures, executive bodies, ministries, regulators, municipalities, courts, constitutional bodies and international bodies. `legal_instrument_authority_roles` records typed relationships such as `enacted_by`, `promulgated_by`, `issued_by`, `published_by` and `administered_by`.

Source-native wording remains provenance. It is not the canonical institution identity. `legal_entities` is the shared real-world identity layer used when the same person or institution appears through more than one specialized legal role.

## Provision lineage and amendment reconstruction

A stable provision may be renumbered, replaced, split, merged or transferred. `legal_provision_lineage` represents those facts explicitly.

`legal_amendment_operations` records ordered operations against a specific target provision version. Character offsets or an explicit anchor make reconstruction auditable. JurisNexo must never simulate legislative history by destructively replacing the current text and discarding the previous state.

## Taxonomies are DAGs

Matter and procedure concepts are not restricted to one parent. `legal_matter_concept_edges` and `procedure_concept_edges` permit multiple broader concepts. Database triggers reject hierarchical cycles.

A concept can therefore legitimately belong to several branches without duplicating the concept or inventing an arbitrary single parent. A judicial decision may also carry multiple matter and procedure classifications through `decision_legal_matters` and `decision_procedures`; singular compatibility fields are not the canonical cardinality.

## Parties, claims and representation

These are separate identities:

1. participant/person/organization;
2. procedural role in a proceeding;
3. representation of that role by counsel or another representative;
4. claim, exception, request, counterclaim or appeal/review ground asserted in that proceeding.

`proceeding_participants` keeps source-native capture. Canonical procedural meaning belongs in `proceeding_party_roles`; representation belongs in `party_representations`; requested relief and grounds belong in `legal_claims`.

A person may be appellant in one proceeding, respondent in another, and represented by different counsel over time. A claim's parent claim and asserting party role must belong to the same proceeding as the claim. `disposition_claim_effects` may connect a disposition to a claim only when that claim's proceeding is explicitly related to the judicial decision.

## Dispositive targets are first-class relations

A dispositive clause and the thing it legally affects are different identities. Canonical target membership lives in `judicial_disposition_targets`, not in one nullable target column on the disposition.

One disposition may therefore target zero, one or many of the following, with one target identity per row:

- `claim`: a `legal_claim` or ground/request;
- `party_role`: a party in a specific procedural capacity;
- `proceeding`: a court-specific proceeding/expediente;
- `judicial_decision`: another judicial decision affected, reviewed, vacated, affirmed or otherwise addressed;
- `proposition`: a legal/factual proposition explicitly adopted, rejected or otherwise targeted by the dispositive clause.

`party_role` deliberately targets `proceeding_party_roles`, not a bare person or organization. A dispositive order generally operates on a party in procedural context; the underlying participant and shared `legal_entity` remain reachable through that role.

Targets of type `claim`, `party_role` and `proceeding` must belong to a proceeding explicitly related to the source judicial decision. A proposition explicitly scoped only to another judicial decision cannot be borrowed as a target. Same tenant/scope is necessary but is not sufficient legal membership.

The historical singular fields `judicial_decision_dispositions.affected_case_id` and `affected_proceeding_id` are compatibility conveniences. Writes through them are projected into `judicial_disposition_targets` and stale compatibility-originated projections are removed on change without deleting independently verified richer targets.

`disposition_claim_effects` remains the richer specialized assertion describing what happened to a claim. Every claim-effect row is projected into the general target layer as a `claim` target, so generic target traversal does not need a separate special case for claims.

## Judges, panel membership, votes and opinions

These are also separate:

- `judicial_officers`: specialized judicial role over a shared `legal_entity` identity;
- `judicial_officer_positions`: temporal court career/position;
- `decision_panel_members`: who sat on a decision and structural panel role;
- `decision_votes`: participation/coarse compatibility summary for one panel member;
- `judicial_vote_stances`: one or more scoped positions on the whole decision, an opinion, proposition or disposition;
- `judicial_stance_concepts`: extensible semantic identities for those positions;
- `judicial_opinions`: opinion identity;
- `judicial_opinion_type_concepts`: extensible semantic identities for opinion forms/types;
- `judicial_opinion_authors`: zero, one or multiple identified authors;
- `judicial_opinion_joiners`: who joined an opinion and to what extent.

`dissenting` and `concurring` are deliberately invalid as panel roles. They describe stance, not membership. A stance cannot borrow a vote, opinion or disposition from another decision. If a proposition is explicitly bound to judicial-decision subjects, a proposition-scoped stance cannot target a proposition whose decision subjects exclude the stance's decision.

Opinion and stance semantics are not closed global enums. The compatibility strings `judicial_opinions.opinion_type` and `judicial_vote_stances.stance_type` are deterministic mirrors of their concept IDs. New jurisdiction-specific concepts may be added without a schema migration; callers must not treat the seed vocabulary as exhaustive or universal.

`decision_votes.vote_type`, `judicial_opinions.author_officer_id`, and the singular decision classification columns are compatibility conveniences, not canonical truth where the normalized relation is richer.

## Decision events are not decision states

Point-in-time judicial acts and durative legal states are distinct persisted facts.

`decision_legal_status_events` is the point-event ledger for acts such as issuance, notification, vacatur, annulment, reversal and enforcement. New writes must not encode finality, res judicata, appealability, stay or suspension as point events.

`decision_legal_states` is the durative state ledger for facts such as appealability, finality, res judicata, stay, suspension, enforceability and supersession. States carry legal-validity time and JurisNexo knowledge time, and overlapping knowledge intervals for the same decision/state identity are rejected.

Those legal facts must never be inferred from or stored in extraction/review status. A perfectly extracted decision can still be appealable; a final judgment can still have poor OCR.

## Judicial authority is contextual and jurisdiction-extensible

Canonical persistence lives in `judicial_authority_effect_assertions`. Each assertion identifies a decision (and optionally a proposition), an explicit jurisdiction/court/legal-matter context, a validity interval, an evidenced basis and a `judicial_authority_effect_concepts` identity.

There is intentionally no global `authority_score` and no timeless `is_binding` flag. The same decision can carry different authority effects in different contexts.

The seed concepts `binding`, `persuasive`, `nonbinding`, `superseded`, `abrogated` and `unknown` preserve compatibility with the vocabulary that existed before this normalization. They are not claimed to be a universal hierarchy or a complete civil-law/common-law ontology. Jurisdiction-specific authority concepts can be added without changing the schema.

`precedential_authority_assertions` is retained only as an updatable compatibility view exposing the historical `authority_type` name. New persistence logic should use `judicial_authority_effect_assertions` and `authority_effect_concept_id`.

## Judicial treatment is contextual

Document-level `legal_relations` is restricted to structural/citation relations such as citation, implementation, amendment, repeal, supersession and requirements.

Substantive treatments live in `legal_treatment_assertions`. `follows`, `distinguishes`, `applies`, `declines_to_apply`, `limits`, `questions`, `criticizes`, `overrules`, `abrogates`, `conflicts_with` and `consistent_with` are legal assertions about an issue, not universal properties of two documents.

Except for simple `cites` and `references`, a treatment requires an `issue_proposition_id`.

## What this model refuses to pretend

The schema does not pretend that:

- a current consolidated text is the historical text;
- the date JurisNexo learned something is the date it became law;
- an amending statute is merely a new row version of the amended statute;
- one taxonomy parent or one singular matter/procedure field can express every legal classification;
- a party name is the same as its procedural role;
- a lawyer is the party they represent;
- an argument is the same thing as a requested claim or ground of appeal;
- one dispositive clause can affect only one legal target;
- a party target can be represented safely as a context-free person identity;
- sitting on a panel means concurring or dissenting;
- one coarse vote value captures every position a judge may take within a decision;
- one closed opinion/stance vocabulary is universal across jurisdictions;
- one author field captures every judicial opinion;
- a point-in-time judicial act is interchangeable with a durative legal state;
- corpus review status means a judgment is final;
- common-law `binding/persuasive` vocabulary exhausts judicial authority effects worldwide;
- precedent has one global strength value;
- `Case A distinguishes Case B` is meaningful without identifying the issue;
- later corrections may erase earlier system knowledge.

These distinctions are database invariants, not conventions left to an LLM prompt.