# JurisNexo — Judicial Proceedings and Extensible Analysis

## 1. Purpose

The corpus must distinguish the legal controversy/proceeding from each judicial
decision issued during that controversy. It must also let analysis agents report
useful findings that the current schema does not yet know how to represent,
without silently converting those findings into canonical legal facts.

The durable identity rule is:

```text
proceeding / expediente != judicial decision != source publication != source artifact
```

The epistemic rule is:

```text
primary source fact != normalized analytical value != inferred interpretation
```

## 2. Proceeding versus decision

`corpus.cases` remains the judicial-decision specialization already used by the
retrieval and ingestion stack. The underlying controversy is represented by
`corpus.legal_proceedings`.

A proceeding may have many decisions:

```text
legal_proceeding
  ├─ first-instance decision
  ├─ appellate decision
  ├─ cassation decision
  └─ later constitutional decision when legally connected
```

A decision may also be connected to multiple proceedings when consolidation or
review requires that representation. `corpus.proceeding_decisions` is therefore
a many-to-many link, not a `proceeding_id` column forced onto `cases`.

This separation is required for procedural-history analysis, argument evolution,
comparison of outcomes across levels, and future training datasets.

## 3. Proceeding identifiers

`corpus.proceeding_identifiers` stores expediente/docket identifiers separately
from decision numbers. It preserves the raw source value, an optional normalized
value, the source registry, and the court that assigned the identifier.

Exact duplicate identifiers remain idempotent even when `source_registry_id` is
NULL. Normalization must never replace the raw official identifier.

## 4. Participants and procedural roles

`corpus.participants` is a scope-local identity candidate. Automatic ingestion
must not globally merge people or organizations merely because normalized names
match.

`corpus.proceeding_participants` preserves:

- raw participant name;
- raw procedural role;
- optional normalized role;
- broad side (`claimant`, `respondent`, `neutral`, `other`);
- source observation provenance;
- verification state and method.

The raw role is mandatory because Dominican matters use vocabulary such as
`recurrente`, `recurrido`, `apelante`, `imputado`, `querellante`, and other roles
that cannot safely be reduced to plaintiff/defendant.

## 5. Procedural graph is not the jurisprudential graph

`corpus.procedural_decision_relation_observations` stores evidence-bearing
candidate procedural relationships. LLM extraction is explicitly an observation
method and creates no canonical edge by itself.

`corpus.procedural_decision_relations` stores verified procedural history such as:

- reviews;
- affirms;
- reverses;
- vacates;
- modifies;
- remands;
- cassates / partially cassates.

This graph is intentionally separate from `corpus.legal_relations`, where
`cites`, `interprets`, `applies`, `distinguishes`, `overrules`, and other
jurisprudential/legal relationships live.

```text
decision A --cites--> decision B        jurisprudential graph

decision C --reverses--> decision D     procedural graph
```

They must never be collapsed into one generic relation table.

## 6. Structured dispositions

A judicial decision may contain several dispositive clauses. Therefore outcome
is not one scalar field on `cases`.

`corpus.case_dispositions` stores an ordered set of clauses and requires exact
`raw_text`. Optional normalization is separate from that source text.

A single decision can therefore represent:

```text
1. partially_cassated
2. remanded
3. costs
```

Every extracted clause carries method, verification state, optional confidence,
and optional page evidence.

## 7. Matter and procedure concepts

Existing `cases.matter` and `cases.procedure_type` remain source-facing/raw text.
They are not overwritten.

The normalized layers are:

- `corpus.legal_matter_concepts`;
- `corpus.procedure_concepts`;
- `cases.legal_matter_concept_id`;
- `cases.procedure_concept_id`.

The concept tables are hierarchical and may be jurisdiction-qualified. They are
intentionally not pre-populated with speculative taxonomies. Real official
source values and benchmark cases should drive expansion.

## 8. Extensible analysis observations

Agents will sometimes discover a repeated legal pattern, taxonomy dimension,
argument form, factual distinction, or other useful concept before JurisNexo has
a first-class field for it. Dropping that information would waste analysis;
adding arbitrary columns whenever an LLM proposes something would corrupt the
canonical model.

`corpus.analysis_observations` is the quarantine boundary between those two
failure modes.

An observation records:

- stable SHA-256 observation key;
- subject (`case`, `proceeding`, `legal_document`, or `corpus`);
- named observation type;
- arbitrary JSONB object payload;
- JSONB evidence list;
- producer and model identity;
- analysis run identifier;
- optional `schema_hint` proposed by the agent;
- confidence when meaningful;
- review/promotion status.

The JSONB payload must be an object. Evidence must be an array. This permits
schema discovery while retaining a minimal machine-auditable envelope.

### Observation lifecycle

```text
observed
   ├─ reviewed
   ├─ rejected
   ├─ superseded
   └─ promoted -> explicit canonical destination required
```

`promoted` does not mean the JSON blob itself became canonical. It means a human
or trusted review process decided the concept deserves a modeled destination,
and `promoted_to_schema` records that destination.

The intended feedback loop is:

```text
agents analyze corpus
      ↓
unmodeled observations (JSONB)
      ↓
review recurring/high-value patterns
      ↓
formal schema/ontology decision
      ↓
versioned migration or normalized concept
      ↓
future agents use the formal model
```

This is how JurisNexo can learn what its data model is missing without granting
LLMs authority to redefine the database.

## 9. API contract

The internal API exposes:

```text
POST /v1/analysis-observations
GET  /v1/analysis-observations
POST /v1/analysis-observations/{id}:review
```

The current adapter is intentionally public-corpus only. `scope_id` is not
accepted from the agent request. Private-scope submission must later derive scope
from authenticated server context rather than model-supplied input.

This is a deliberate tenant-boundary requirement.

## 10. Deferred interpretive schema

This migration does not prematurely freeze first-class tables for every semantic
claim an LLM might extract. Dedicated structures for claims, arguments,
material facts, legal issues, holdings, reasoning segments, and judicial officers
should be added only after real-source benchmarks demonstrate stable semantics.

Until then, useful unmodeled discoveries can be retained in
`analysis_observations`, reviewed, counted, and used to justify the next formal
schema change.

## 11. Invariants

The following are hard requirements:

1. A proceeding is never inferred to be identical to a decision.
2. LLM procedural relations remain observations until explicitly promoted.
3. Raw source names, roles, matter text, procedure text, and dispositive text are
   never overwritten by normalized values.
4. Cross-scope proceeding/case/participant/document links are rejected by
   PostgreSQL.
5. Arbitrary JSONB analysis observations are quarantined from canonical legal
   facts.
6. Agents cannot select tenant scope through the observation API.
7. Promotion requires a named canonical destination and review action.
