# Comprehensive legal semantics

Status: normative architecture for the current schema.

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

Source-native wording remains provenance. It is not the canonical institution identity.

## Provision lineage and amendment reconstruction

A stable provision may be renumbered, replaced, split, merged or transferred. `legal_provision_lineage` represents those facts explicitly.

`legal_amendment_operations` records ordered operations against a specific target provision version. Character offsets or an explicit anchor make reconstruction auditable. JurisNexo must never simulate legislative history by destructively replacing the current text and discarding the previous state.

## Taxonomies are DAGs

Matter and procedure concepts are not restricted to one parent. `legal_matter_concept_edges` and `procedure_concept_edges` permit multiple broader concepts. Database triggers reject hierarchical cycles.

A concept can therefore legitimately belong to several branches without duplicating the concept or inventing an arbitrary single parent.

## Parties and representation

These are separate identities:

1. participant/person/organization;
2. procedural role in a proceeding;
3. representation of that role by counsel or another representative.

`proceeding_participants` keeps source-native capture. Canonical procedural meaning belongs in `proceeding_party_roles`; representation belongs in `party_representations`.

A person may be appellant in one proceeding, respondent in another, and represented by different counsel over time.

## Judges, panel membership, votes and opinions

These are also separate:

- `judicial_officers`: person identity;
- `judicial_officer_positions`: temporal court career/position;
- `decision_panel_members`: who sat on a decision and structural panel role;
- `decision_votes`: how a panel member voted;
- `judicial_opinions`: majority, plurality, per curiam, concurring, dissenting or separate opinion;
- `judicial_opinion_joiners`: who joined an opinion and to what extent.

`dissenting` and `concurring` are deliberately invalid as panel roles. They describe stance, not membership.

## Decision legal status is not corpus quality

`decision_legal_status_events` records events such as notification, finality, res judicata, stay, suspension, vacatur, annulment, reversal and enforcement.

Those facts must never be inferred from or stored in extraction/review status. A perfectly extracted decision can still be appealable; a final judgment can still have poor OCR.

## Authority is contextual

`precedential_authority_assertions` represents binding, persuasive or other authority in an explicit context: jurisdiction, court and/or legal matter, with a basis and validity interval.

There is intentionally no global `authority_score` and no timeless `is_binding` flag. The same decision can be binding in one context and persuasive in another.

## Judicial treatment is contextual

Document-level `legal_relations` is restricted to structural/citation relations such as citation, implementation, amendment, repeal, supersession and requirements.

Substantive treatments live in `legal_treatment_assertions`. `follows`, `distinguishes`, `applies`, `declines_to_apply`, `limits`, `questions`, `criticizes`, `overrules`, `abrogates`, `conflicts_with` and `consistent_with` are legal assertions about an issue, not universal properties of two documents.

Except for simple `cites` and `references`, a treatment requires an `issue_proposition_id`.

## What this model refuses to pretend

The schema does not pretend that:

- a current consolidated text is the historical text;
- the date JurisNexo learned something is the date it became law;
- an amending statute is merely a new row version of the amended statute;
- one taxonomy parent can express every legal classification;
- a party name is the same as its procedural role;
- a lawyer is the party they represent;
- sitting on a panel means concurring or dissenting;
- corpus review status means a judgment is final;
- precedent has one global strength value;
- `Case A distinguishes Case B` is meaningful without identifying the issue;
- later corrections may erase earlier system knowledge.

These distinctions are database invariants, not conventions left to an LLM prompt.
