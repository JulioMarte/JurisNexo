# JurisNexo — Judicial Proceedings, Decision Identity, and Cross-Source Resolution

## 1. Purpose

JurisNexo must support the Suprema Corte de Justicia, Tribunal Constitucional, and later lower courts without rebuilding the data model for each source. The core distinction is:

```text
proceeding / expediente != judicial decision != source publication != source artifact
```

A proceeding may generate multiple decisions at different judicial levels. One decision may appear in several official source channels: a standalone PDF, a principal-decisions compilation, a bulletin, a historical repository, or a corrected republication.

This document defines the durable judicial abstraction added by migration `0017_judicial_proceedings`.

## 2. Canonical hierarchy

The judicial model is:

```text
institution
  -> court
      -> court organ
          -> proceeding / expediente
              -> judicial decision(s)
                  -> source-native publication record(s)
                      -> immutable source artifact(s)
```

The layers are deliberately independent.

- `corpus.courts` and `corpus.court_organs` describe the adjudicative institution and organ.
- `corpus.judicial_proceedings` represents the underlying case file / expediente / process.
- `corpus.cases` continues to represent one canonical judicial decision.
- `corpus.source_documents` represents what an official source channel published.
- `corpus.source_artifacts` represents immutable acquired bytes.
- `corpus.source_document_canonical_resolutions` records when a source-native record has been resolved onto one canonical legal document.

No source URL, PDF, bulletin entry, or principal-decisions entry is itself the canonical identity of a judicial decision.

## 3. Why proceedings are separate from decisions

A single dispute can produce several decisions:

```text
first instance decision
  -> appeal decision
      -> cassation decision
          -> constitutional review where applicable
```

Those decisions should remain separate legal authorities while still being connected to the same underlying proceeding when the evidence supports that identity.

`corpus.judicial_proceedings` therefore carries process-level identity and may have multiple identifiers in `corpus.judicial_proceeding_identifiers`.

This is required for future questions such as:

- how did the outcome change between first instance, appeal, and cassation?;
- what arguments survived successive levels of review?;
- which procedural posture correlates with a particular disposition?;
- which lower-court decisions were affirmed, modified, remanded, or cassated?;

## 4. Source-native identifiers

Identifiers are source facts, not global identity by themselves.

A proceeding may have:

- expediente number;
- docket number;
- legacy docket number;
- source-specific identifier;
- aliases introduced by a new judicial stage or publication system.

Raw values must be retained. Normalized values are separate analytical fields.

The same rule applies to judicial decisions through the existing `case_identifiers` and generic `legal_document_identifiers` tables.

## 5. Participants and party roles

`corpus.judicial_proceeding_participants` preserves participants at the proceeding level.

Important fields include:

- raw participant name;
- normalized participant name;
- participant kind;
- raw role;
- normalized role;
- party side;
- source-document observation or case-page evidence;
- verification state and method.

Raw legal vocabulary must not be destroyed during normalization. `Recurrente`, `recurrido`, `apelante`, `imputado`, `querellante`, and other source-native roles may later map to broader analytical categories while retaining their original meaning.

Do not assume every matter can be reduced to plaintiff/defendant.

## 6. Matter and procedure normalization

Source interfaces often expose useful controlled metadata such as `Materia` and procedure/recurso type. JurisNexo must preserve the raw strings already stored on a decision while allowing stable normalized concepts through:

- `corpus.legal_matters`;
- `corpus.procedure_types`;
- `cases.legal_matter_id`;
- `cases.procedure_type_id`.

The vocabulary is hierarchical and temporal. This allows source-specific values to map onto a shared analytical vocabulary without pretending the source originally used the normalized label.

## 7. Court hierarchy

`corpus.courts` now supports:

- `parent_court_id`;
- `court_level`;
- `territorial_jurisdiction`.

This enables later representation of the Dominican judicial hierarchy without encoding SCJ-specific assumptions into every decision.

Court hierarchy is institutional metadata. Procedural review relationships between individual decisions are stored separately.

## 8. Procedural relations between decisions

JurisNexo distinguishes jurisprudential relationships from procedural relationships.

Existing `legal_relations` can represent concepts such as:

```text
cites
follows
distinguishes
overrules
interprets
```

The new judicial-decision relation layer represents procedural treatment such as:

```text
reviews
affirms
reverses
vacates
modifies
remands
cassates
partially_cassates
orders_new_trial
enforces
```

These are different meanings and must not be collapsed into a generic `RELATED_TO` edge.

Candidate procedural relationships belong first in `judicial_decision_relation_observations`. LLM extraction alone does not create a verified canonical relation. Promotion to `judicial_decision_relations` is a separate verified action.

## 9. Structured dispositions

`corpus.case_dispositions` records the dispositive result of a judicial decision while retaining exact source language.

Examples of normalized disposition categories include:

- granted;
- denied;
- dismissed;
- inadmissible;
- affirmed;
- reversed;
- vacated;
- modified;
- remanded;
- cassated;
- partially cassated;
- costs;
- other.

A decision may contain multiple ordered dispositive clauses. The raw text remains mandatory because the normalized category is an analytical projection, not a replacement for the judicial source.

This supports later aggregate analysis without sacrificing auditability.

## 10. Judicial officers

`corpus.judicial_officers` and `corpus.case_judicial_officers` model adjudicators separately from parties.

Supported roles include:

- presiding judge;
- rapporteur / ponente;
- judge/member;
- dissenting judge;
- concurring judge.

The purpose is historical and doctrinal analysis, not simplistic prediction of individual judges.

## 11. Cross-source canonical resolution

The same decision may be visible through several official SCJ channels. For example:

```text
Principales Decisiones
        +
standalone SCJ decision record
        +
Boletín Judicial representation
        -> one canonical legal document
```

`corpus.source_document_canonical_resolutions` records this mapping.

A source record may have multiple candidate matches while identity is unresolved, but at most one verified canonical resolution is permitted at a time.

The resolver should use evidence such as:

- exact official source identifier;
- expediente number;
- decision number;
- decision date;
- court / organ;
- parties;
- exact or near-exact text fingerprint;
- artifact identity where applicable.

Thresholds for automatic resolution must be benchmarked against reviewed examples. Do not hard-code arbitrary confidence thresholds as legal truth.

## 12. SCJ ingestion priority

The current MVP priority is:

```text
1. Principales Decisiones
2. standalone SCJ decisions, 1994 -> present
3. cross-source identity reconciliation
4. historical bulletins / historical decisions as catalog-only inventory
```

The first two sources should feed the same canonical decision model.

The historical archive may be mapped for future expansion, but catalog-only records must not be treated as parsed/searchable authority merely because JurisNexo knows that a remote document exists.

## 13. Official metadata preservation

The source inventory already preserves the complete official payload in `source_document_observations.source_payload` plus deterministic normalization notes.

Normalized fields in canonical tables are therefore projections from source evidence. They must never silently replace or rewrite the original source payload.

For modern SCJ records this is especially valuable because structured fields such as date, parties, expediente, sala, materia, decision number, and document links can be retained before any LLM processing.

## 14. Analysis and model-training boundary

The canonical corpus must not be designed around one model-training format.

Instead:

```text
canonical corpus
   -> versioned dataset builder
       -> retrieval datasets
       -> citation-link datasets
       -> issue/holding datasets
       -> procedural-outcome datasets
       -> argument/fact datasets
       -> supervised or preference-training datasets where justified
```

Training data is derived, versioned output. It is not the system of record.

This keeps JurisNexo useful for retrieval and agentic research even if the model stack changes completely.

## 15. What is intentionally not implemented yet

Migration `0017` creates the durable relational foundation. It does not yet claim that JurisNexo can reliably extract all of the following across every court:

- material facts;
- party arguments;
- claims/pretensions;
- legal issues;
- holdings;
- damages or monetary awards;
- judge identity resolution across spelling variants;
- person/organization entity resolution across proceedings;
- complete procedural chains across court levels.

Those require source-specific ingestion, evidence-bearing extraction, and independent benchmarks.

The correct sequence is to store structured official metadata first, then add semantic enrichment only where a benchmark proves acceptable precision and recall.

## 16. Architectural invariant

The durable rule is:

```text
source fact
  != normalized analytical value
  != inferred legal interpretation
```

and:

```text
proceeding
  != decision
  != source publication
  != artifact
```

Preserving those distinctions is what makes later large-scale legal analysis auditable rather than merely plausible.
