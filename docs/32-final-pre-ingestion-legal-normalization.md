# Final pre-ingestion legal normalization

Status: normative architecture.

This document records the last intentionally breaking schema normalization before large-scale corpus ingestion. The database had no production corpus data when these changes were made, so compatibility with misleading early physical names or closed enumerations was explicitly subordinate to legal correctness.

## Judicial decision identity

`corpus.judicial_decisions` is the physical canonical table for one judicial decision.

A judicial decision is not a controversy, proceeding/expediente, publication, source artifact or research "case". `corpus.cases` exists only as a deprecated compatibility view during code migration and must not be used by new persistence code.

The same distinction remains:

```text
legal_controversy
    -> one or more legal_proceedings
        -> one or more judicial_decisions
            -> one or more source manifestations / artifacts
```

## Legal norms are assertions, not invented primary text

The former `legal_requirements.canonical_text` abstraction is removed.

A derived legal requirement is represented as:

1. a `legal_propositions` row describing the semantic proposition;
2. a `legal_norm_assertions` row saying that the proposition functions as a norm/requirement in a jurisdiction and time;
3. one or more typed `legal_norm_sources` rows recording whether a source establishes, defines, amends, repeals, creates an exception, interprets, satisfies or otherwise evidences the norm.

`derivation_kind` distinguishes explicit primary-source text from multi-source derivation, synthesized interpretation and human legal analysis. A synthesized statement does not become statutory text merely because it is useful or verified.

A norm assertion cannot become `verified` without at least one verified legal source.

## Stable legal relations and historical assertions

Structural document relations now have two layers:

- `legal_relation_identities`: stable source/type/target identity;
- `legal_relation_assertions`: legal-valid time, JurisNexo knowledge time, verification state and review information.

Evidence attaches to the assertion through `legal_relation_assertion_evidence`, not to an ahistorical edge.

This permits the same structural relation to be asserted for different legal periods or corrected later without erasing what JurisNexo previously knew.

Substantive judicial treatment continues to live separately in `legal_treatment_assertions`.

## Extensible disposition and procedural-role concepts

Judicial dispositive outcomes are no longer a closed `disposition_type` enum. `disposition_concepts` supplies canonical identities while the exact dispositive language remains source text on `judicial_decision_dispositions`.

Canonical procedural roles are likewise `procedural_role_concepts`, not a fixed `role_type` string. This lets Dominican and future jurisdictions add legally meaningful roles without schema migrations merely to extend vocabulary.

`proceeding_participants.role_raw` and related source-native fields remain provenance and must never be overwritten by canonical concepts.

## Proposition ownership

`legal_proposition_subjects` binds a proposition to the judicial decision, document, proceeding, stable provision or general-law subject it actually describes.

For judicial treatment:

- a supplied `source_proposition_id` must belong to `source_case_id`;
- a supplied `target_proposition_id` must belong to `target_case_id`;
- treatment evidence must come from the source judicial decision;
- verified substantive treatment requires evidence.

The database therefore rejects a holding extracted from Decision Z being silently used as the holding of Decision A merely because both records exist in the same corpus scope.

## Judicial opinion membership

An officer may author or join an opinion only when the database can connect that officer to the panel for the same judicial decision. Opinion stance and panel membership remain independent facts.

The database rejects an officer joining an opinion in a matter on whose panel that officer did not sit.

## Court competence is multidimensional

The old generic jurisdiction vocabulary remains useful for broad institutional classification, but court competence is now decomposed into independent legal dimensions:

- `territorial_units` + `court_territorial_competences`;
- `legal_matter_concepts` + `court_subject_matter_competences`;
- `court_functional_competences` for original/appellate/cassation/constitutional-review/etc. function and instance level.

Territory, subject matter, functional competence, instance and institutional judicial system are not interchangeable concepts.

## Bitemporal boundary outside legislation

Bitemporality is extended to mutable legal assertions, not indiscriminately to every semantic identity.

The rule is:

- legislation/version knowledge uses legal-valid time plus system-knowledge time;
- legal norm assertions use `valid_*` plus `known_*`;
- structural legal relation assertions use `valid_*` plus `known_*`;
- judicial treatment assertions use `valid_*` plus `known_*`;
- precedential-authority assertions use `valid_*` plus `known_*`;
- decision legal-status assertions/events retain system-knowledge intervals as well as their legal event date.

`legal_propositions` themselves are treated as immutable semantic claims. If JurisNexo later concludes that a proposition was wrong or materially incomplete, it creates a new proposition and links the old/new claims with `supersedes` or `contradicts`; it does not mutate yesterday's proposition into a different statement.

This boundary avoids duplicating knowledge-history machinery on stable semantic identities while preserving auditable changes in every mutable legal conclusion.

## Compatibility policy

Compatibility is allowed only where it does not restore the old ontology.

Examples:

- `corpus.cases` is a deprecated read/write-compatible view over `judicial_decisions` during migration, not the canonical table;
- Python canonical-commit results expose temporary read aliases such as `case_id`, but canonical field names are `judicial_decision_id` and `decision_page_ids`;
- closed persisted `role_type` and `disposition_type` columns are not restored for compatibility.

New code, agents, tests and documentation must use canonical terminology.

## Non-negotiable epistemic layers

```text
SOURCE
what the legal source actually says

NORMALIZATION
how JurisNexo identifies and organizes source facts

ASSERTION
what JurisNexo claims those facts imply, with evidence and time

LEGAL CONCLUSION
what a lawyer can defend from one or more assertions
```

No convenience API, LLM output or migration shortcut may collapse these layers.
