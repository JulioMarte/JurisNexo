# JurisNexo — Legal Reality V2

## Status

Normative pre-ingestion data-model contract. This document refines `02-legal-corpus-and-data-model.md` and the temporal/schema documents without replacing their provenance rules.

## Why this exists

The corpus model must represent legal reality rather than a convenient one-row-per-concept approximation. Before mass ingestion, JurisNexo therefore removes several false singularities that are common in legal databases but do not survive real litigation.

The guiding rule is:

```text
real-world identity
    != document representation
    != semantic proposition
    != JurisNexo assertion about that proposition
```

Compatibility columns may remain temporarily for current API callers, but comments must identify them as compatibility/preferred-display values when a normalized relation is canonical.

## Canonical identity layers

The litigation layer is:

```text
legal_controversy
    <-> controversy_proceedings <-> legal_proceeding
    <-> proceeding_decisions   <-> judicial_decision
```

A controversy may span multiple proceedings. A proceeding may participate in more than one litigation-family relationship over time. A judicial decision may resolve or concern multiple proceedings, including consolidated matters. `proceeding_decisions.is_primary` is therefore only a source/display preference and must never be used as an identity invariant.

The source layer remains independent:

```text
source_registry
 -> source_artifact
 -> artifact_page
 -> legal_document_artifact_occurrence
 -> legal_document / judicial_decision representation
```

## Proposition identity and subjects

`legal_propositions` are immutable semantic claims. Changing proposition text, proposition type, normalized text, or assertion origin creates a new proposition identity rather than rewriting the existing claim. Verification and confidence may still evolve.

`legal_proposition_subjects` is genuinely N:N. A proposition can concern multiple provisions, decisions, documents, or proceedings of the same type. `subject_role` records how a subject participates in the claim without forcing one subject per type.

Examples that must be representable:

- one holding concerning Articles 20 and 21;
- one synthesis comparing two judicial decisions;
- one proposition about several consolidated proceedings.

## Multi-valued decision classification

A judicial decision may concern several legal matters and several procedural concepts. Canonical classification therefore lives in:

- `decision_legal_matters`;
- `decision_procedures`.

The historical single-valued fields on `judicial_decisions` are compatibility/preferred classifications only. New analytical code must not infer that a decision has exactly one legal matter or one procedure.

## Judicial panel, opinion, authorship and stance

These are separate identities:

```text
judicial_officer
 -> decision_panel_member
 -> decision_vote participation/legacy summary
 -> judicial_vote_stances

judicial_opinion
 -> judicial_opinion_authors
 -> judicial_opinion_joiners
```

A judge can concur as to one issue, dissent as to another, join only part of an opinion, or record a saved/reserved vote. `decision_votes.vote_type` is retained only as a coarse compatibility summary. Canonical mixed or partial positions live in `judicial_vote_stances` and are scoped to the whole decision, an opinion, a proposition, or a disposition.

An opinion may have zero, one, or multiple identified authors. Canonical authorship is N:N in `judicial_opinion_authors`; the historical single-author field is compatibility-only.

Database constraints must ensure that an opinion author and a vote stance refer to members of the same decision panel and that a stance cannot borrow a `vote_id` from a different judge or decision.

## Common legal entity identity

`legal_entities` provides a shared identity for real persons and institutions that may appear in several legal roles. Specialized tables remain because their role-specific attributes are useful:

- `participants`;
- `judicial_officers`;
- `courts`;
- `legal_authorities`.

Those rows point to `legal_entities`. The same real person may therefore be a participant in one historical proceeding and a judicial officer in a later period without becoming two unrelated real-world identities. The same institution can likewise be represented as a court and as a legal authority where both roles are legally meaningful.

Identity resolution remains explicit. Equal normalized names are not sufficient proof that two records are the same entity.

## Claims and requested relief

Arguments, issues and holdings do not replace the procedural question "what did this party ask the tribunal to do?"

`legal_claims` therefore represents claims, counterclaims, procedural exceptions, inadmissibility motions, interim requests, and appeal/cassation/review grounds. Claim concepts are extensible rather than frozen in a universal enum.

`disposition_claim_effects` links a judicial disposition to the claim it resolves and an extensible effect concept such as granted, partially granted, denied, or inadmissible.

A later hardening rule may require the claim's proceeding to be one of the proceedings linked to the decision before a verified disposition effect can be committed. Until that rule is implemented, ingestion/audit code must not treat mere foreign-key validity as proof of procedural membership.

## Contextual legal norm identity

Proposition text is not the complete identity of a legal norm. The same wording may have different legal effect by jurisdiction, legal matter, or validity period.

The model is therefore:

```text
legal_proposition
      -> legal_norm_claim
             -> legal_norm_assertions (knowledge history)
                    -> legal_norm_sources
```

`legal_norm_claims` identifies the contextual claim: proposition, jurisdiction, norm kind, optional matter, and legal-validity interval. `legal_norm_assertions` records what JurisNexo knew or believed about that claim over system time.

Knowledge-overlap protection is keyed by `norm_claim_id`, not merely `proposition_id`. Two contextual claims using the same proposition may coexist; two overlapping knowledge states for the same claim may not.

## Events versus durative states

A point event and a legal state are different facts.

`decision_legal_status_events` remains the lifecycle-event ledger for events such as issuance or notification. Historical state-like values are readable for compatibility.

New durative legal states belong in `decision_legal_states`, for example:

- final;
- res judicata;
- stayed;
- suspended;
- enforceable;
- superseded.

Decision states carry both legal-validity time and JurisNexo knowledge time. Overlapping knowledge intervals for the same decision/state identity are rejected.

## Extensibility policy

Jurisdiction-sensitive legal categories should move toward concept identities rather than ever-growing `CHECK (... IN (...))` lists. Legal Reality V2 establishes this pattern for claims, claim effects and decision states while preserving existing concept registries for dispositions, procedural roles, matters and procedures.

Not every text field should become a taxonomy. Raw source wording stays raw; normalized concepts exist only where cross-source semantics are valuable.

## Compatibility rule

Compatibility fields are not competing sources of truth. New code should prefer the normalized relations named in this document. Compatibility fields exist to let the MVP evolve without forcing an unrelated rewrite of every caller in the same migration.

No compatibility layer may reintroduce a false HARD invariant such as one matter per decision, one proceeding per decision, one author per opinion, or one judicial stance per judge/decision.

## Pre-ingestion boundary

Migrations `0031_legal_reality_v2` and `0032_harden_legal_reality_v2` form part of the intentional pre-ingestion normalization boundary. Their downgrade functions fail deliberately rather than pretending that collapsing the richer identities is lossless.
