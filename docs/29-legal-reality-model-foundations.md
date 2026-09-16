# JurisNexo — Legal Reality Model Foundations

## 1. Purpose

The corpus started with strong source/document provenance and has progressively
separated artifacts, legal documents, judicial decisions, proceedings, and
analysis observations. The next modeling step is to represent legal reality
without forcing distinct concepts into the judicial-decision table.

This document defines the first foundation block. It is intentionally smaller
than a full legal ontology: it introduces only identities that repeatedly occur
in real litigation and that are difficult to recover correctly once a large
corpus has already been loaded.

The governing rule is:

```text
controversy != proceeding != procedural event != judicial decision
judicial officer != court != court organ
source text != legal proposition != interpretation
provision label identity is hierarchical, not document-global
```

## 2. Legacy `cases` naming

`corpus.cases` is retained as the physical table name for compatibility, but its
domain meaning is one **judicial decision**. It does not represent the complete
litigation controversy and it does not represent the underlying expediente.

New documentation and domain APIs should use `judicial decision` when referring
to rows in `corpus.cases`. A future physical rename may use compatibility views
or a staged migration; this foundation change does not introduce a gratuitous
breaking rename.

## 3. Provision identity is hierarchical

Legal instruments commonly repeat child labels:

```text
Artículo 10
  └─ Párrafo I

Artículo 11
  └─ Párrafo I
```

The old uniqueness rule `(document_id, normalized_label)` incorrectly rejected
this structure. Provision label uniqueness is now scoped to siblings:

```text
(document, parent provision, normalized label)
```

Two `Párrafo I` provisions under different articles are legal. Two `Párrafo I`
children under the same article are a structural conflict that requires review.

This is a HARD corpus-integrity rule because silently rewriting labels to satisfy
a database constraint would corrupt the source structure.

## 4. Litigation controversy versus proceeding

A real dispute can pass through several separately numbered or separately
administered proceedings:

```text
legal controversy
  ├─ first-instance proceeding
  ├─ appellate proceeding
  ├─ cassation proceeding
  └─ constitutional proceeding
```

`corpus.legal_controversies` represents the real-world dispute/litigation family.
`corpus.legal_proceedings` remains the court-specific proceeding or expediente.

The relation is optional because source ingestion may establish a proceeding
before there is enough evidence to group it safely into a controversy.

Automatic grouping must remain conservative. Similar party names or subject
matter alone do not prove controversy identity.

Cross-scope links are rejected by PostgreSQL using composite foreign keys.

## 5. Procedural events

A proceeding is not merely a collection of decisions. It can contain filings,
hearings, evidence submissions, interlocutory orders, appeals, transfers,
settlements, stays, remands, execution events, and other acts.

`corpus.procedural_events` records those events independently from judicial
decisions.

The table preserves:

- normalized broad `event_type`;
- optional source-native `event_type_raw`;
- exact/raw description when available;
- event date plus explicit date confidence/status;
- source observation/evidence references;
- verification method/status and confidence.

Unknown dates remain unknown. A verified-date status cannot be stored without an
actual date.

`other` remains available because procedural vocabulary is jurisdiction- and
source-specific. Using `other` requires source-native event wording or a raw
description so normalization never erases the original meaning.

## 6. Judicial officers and decision panels

A court or chamber is an institution; a magistrate is a person. They are not the
same identity.

`corpus.judicial_officers` stores conservative officer identity candidates.
Normalized names are lookup aids, not automatic merge authority.

`corpus.decision_panel_members` links an officer to one judicial decision and
preserves both:

- raw role wording from the source;
- a broad normalized panel role.

This supports roles such as presiding member, rapporteur/ponente, ordinary panel
member, dissenting member, and concurring member without storing judge names in
fixed decision columns.

Separate-opinion text and richer judicial-career history remain later work; this
migration establishes the identities needed to add them safely.

## 7. Legal propositions

The document graph answers questions such as "what cites what". Lawyers also
need to know what a decision actually says about a legal question.

`corpus.legal_propositions` introduces a deliberately small proposition model
covering:

- issue;
- holding;
- legal rule;
- legal test;
- exception;
- material/procedural fact;
- argument/counterargument;
- reasoning;
- conclusion;
- dictum;
- other.

A proposition is not automatically a primary-source fact. `assertion_kind`
preserves its epistemic character:

```text
explicit_primary_text
  source states the proposition directly

derived_from_primary_text
  structured derivation closely tied to source text

synthesized_interpretation
  legal interpretation produced from one or more source passages

human_authored
  proposition supplied by an authorized human workflow
```

Verification and assertion kind are independent. A reviewed interpretation does
not become literal source text merely because a reviewer accepts it.

## 8. Proposition evidence

`corpus.legal_proposition_evidence` keeps supporting, qualifying,
contradicting, or contextual evidence separate from the proposition itself.

Evidence may point to a judicial decision, legal document, case page, physical
artifact page, exact excerpt, and character offsets.

This design allows a legal proposition to remain stable while the system records
multiple pieces of evidence or later finds contrary evidence.

## 9. Proposition relations

`corpus.legal_proposition_relations` represents relationships at the proposition
level rather than forcing every legal treatment into a document-to-document
edge.

Initial relations are intentionally limited:

```text
answers
supports
opposes
qualifies
limits
creates_exception_to
depends_on
derived_from
applies_to
distinguishes_from
```

Every relation has verification status/method. Cross-scope relations are rejected
by PostgreSQL.

This table does not replace `corpus.legal_relations`. The document graph remains
useful for explicit citations, amendment/repeal, and document-level treatment.
Proposition-level context is the safer destination for nuanced holdings and
interpretive comparisons.

## 10. What this migration deliberately does not model yet

The following are intentionally deferred into separate changes because they have
different invariants and need their own adversarial tests:

1. legal instrument identity versus temporal versions;
2. stable provision identity versus provision text versions;
3. promulgation/publication/effective/repeal event semantics;
4. bitemporal legal knowledge (`valid time` versus `recorded time`);
5. multi-parent/DAG legal taxonomies replacing single `parent_id` trees;
6. normalized procedural-role concepts and representation relationships;
7. separate judicial opinions and richer officer tenure/history;
8. contextual authority/binding-effect classifications;
9. decision legal-status/finality distinct from corpus quality;
10. richer treatment assertions that contextualize document-level
    `follows/distinguishes/conflicts_with` by issue/proposition.

Deferral here is not dismissal. These should be implemented as explicit,
versioned migrations rather than hidden in JSONB or overloaded text columns.

## 11. Required invariants

The implementation must preserve these invariants:

1. Repeated provision labels under different parents are allowed.
2. Duplicate normalized provision labels among the same siblings are rejected.
3. A controversy can contain multiple proceedings.
4. A proceeding cannot reference a controversy from another scope.
5. Procedural dates are never invented merely to satisfy a constraint.
6. A judicial officer identity is independent of the role held in a decision.
7. Raw panel role wording is preserved alongside normalization.
8. A synthesized legal proposition remains explicitly interpretive even after
   review.
9. Proposition evidence remains independently addressable.
10. Proposition relations cannot cross tenant/corpus scope boundaries.

## 12. Validation

Durable proof belongs in PostgreSQL integration tests because the most important
claims are database constraints, not Python behavior.

The tests must include both positive and adversarial cases, including:

- repeated `Párrafo I` under different articles succeeds;
- duplicate `Párrafo I` under one article fails;
- multi-proceeding controversy succeeds;
- cross-scope controversy/proposition relations fail;
- a verified procedural date without a date fails;
- raw judicial role survives normalization;
- synthesized propositions retain their interpretation marker and evidence.

Repository CI is required evidence for merge, but green CI alone does not prove
that future semantic extraction agents can identify these concepts reliably.
Agent extraction benchmarks must be added when those agents begin producing the
new canonical structures.
