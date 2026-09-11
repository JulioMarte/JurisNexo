# JurisNexo — Document Intelligence and Structure Discovery

## 1. Purpose

JurisNexo must ingest legal material that is not uniformly structured.

The corpus will eventually include:

- modern born-digital decisions with stable headings;
- older Supreme Court compilations with different publication grammars;
- Constitutional Court material;
- other courts whose identifiers and metadata do not match SCJ conventions;
- scanned books and bulletins;
- mixed PDFs containing both embedded text and scanned pages;
- compilations with useful indexes but weak per-page metadata;
- documents whose structure changes inside one artifact;
- tenant-provided legal material with no known publication family.

Therefore the ingestion architecture must not assume that one universal deterministic parser can recognize every legal artifact.

The core design principle is:

> **Models discover candidate structure; deterministic code operationalizes validated structure; database constraints and provenance prevent unverified model output from silently becoming corpus truth.**

This document makes that principle part of the JurisNexo architecture.

---

## 2. Two ingestion paths

Every artifact first goes through artifact inspection and page materialization. After that, JurisNexo chooses one of two paths.

### 2.1 Known document family

Use this path when the artifact matches a versioned family with validated rules.

```text
artifact
  -> page materialization
  -> family detector
  -> known family/version
  -> deterministic segmenter/parser
  -> observations
  -> validation/reconciliation
  -> canonical promotion when eligible
```

Examples include the currently implemented SCJ publication/layout families.

### 2.2 Unknown or insufficiently supported document family

Use this path when:

- no known family matches reliably;
- OCR quality or page layout makes existing rules unreliable;
- the artifact appears to contain an index or nested structure that has not been modeled;
- the publication grammar changes materially inside the document;
- a known-family parser produces excessive diagnostics or unknown pages;
- the source is a court or historical period not yet supported.

```text
artifact
  -> page materialization / OCR
  -> discovery workspace
  -> agent exploration
  -> candidate family specification
  -> candidate segmentation + metadata rules
  -> validation against source evidence
  -> human/gold review when required
  -> accepted family version
  -> deterministic execution
```

The discovery path is not allowed to write directly to canonical legal tables.

---

## 3. Artifact inspection before legal parsing

Legal parsing starts only after JurisNexo knows what kind of pages it has.

Each page should be classified at minimum as:

- `digital_text` — useful native text is embedded in the file;
- `scanned_image` — the page is primarily an image and requires OCR;
- `mixed` — both native text and image content materially contribute;
- `unreadable` — neither extraction nor OCR currently yields usable evidence.

The artifact-level classification is derived from page-level evidence rather than assumed from the PDF extension.

The source image/page must remain preserved even after OCR.

```text
physical artifact
    -> physical page
         -> native text, if any
         -> OCR text, if required
         -> normalized text
         -> extraction/OCR provenance
```

OCR is an extraction method, not source truth. OCR output must retain method/version/confidence and point back to the original page image.

---

## 4. Discovery workspace

A structure-discovery agent receives a bounded workspace, not unrestricted database authority.

The workspace may expose tools such as:

```text
get_page(page_number)
get_pages(start, end)
search_text(query)
sample_pages(strategy, count)
render_page(page_number)
run_regex(pattern, scope)
run_python(code, bounded_inputs)
compare_headers(page_numbers)
list_candidate_boundaries()
inspect_index_candidate(page_range)
```

The agent may also delegate bounded sub-tasks or recursive model calls.

The workspace stores:

- discovery run identity;
- artifact SHA-256;
- model provider/model/version;
- prompt/instruction version;
- inspected page ranges;
- tool calls and outputs needed for reproducibility;
- candidate hypotheses;
- candidate family specification;
- validation results;
- unresolved anomalies;
- cost/token/runtime accounting.

The agent cannot mutate canonical `corpus.cases`, canonical dates, or evidence relationships.

---

## 5. RLM-style exploration

JurisNexo adopts the Recursive Language Model pattern for very large or unknown documents without requiring a literal dependency on one RLM implementation.

The important pattern is:

```text
root model
   -> external document/page environment
   -> search/sample/programmatic inspection
   -> bounded recursive/sub-model calls
   -> hypothesis
   -> programmatic validation
```

A 700-page scanned legal book should not normally be serialized into one giant prompt even when the model context window technically allows it.

The agent should instead inspect selectively.

Example:

```text
inspect pages 1-20
  -> detect probable index
  -> parse candidate index entries
  -> inspect pages referenced by sample entries
  -> infer candidate case-start grammar
  -> execute candidate grammar across book
  -> compare discovered count with index count
  -> investigate mismatches
```

This makes the model an investigator of document structure rather than an opaque bulk extractor.

---

## 6. DocETL-style transformation

Once candidate segments exist, JurisNexo may use DocETL-style model-assisted transformations for fields that are not robustly expressible through deterministic rules.

Examples:

- extracting heterogeneous party roles;
- identifying metadata labels that vary by decade;
- interpreting old indexes;
- mapping source-specific headings to a normalized legal schema;
- comparing extraction strategies across samples.

The valuable idea is pipeline optimization and evaluation, not unconditional adoption of a specific framework.

Model-assisted transformations still emit observations, not canonical facts.

---

## 7. LOTUS-style semantic operations

LOTUS-like semantic dataframe/relational operations are more valuable after page and case structure exists.

Potential uses include:

- semantic filtering across candidate segments;
- semantic joins for duplicate/matching decisions;
- semantic aggregation over large normalized collections;
- extraction/classification jobs where a relational execution plan can minimize expensive model calls.

LOTUS-style operations complement rather than replace source-preserving ingestion.

---

## 8. Family specification as a first-class artifact

The most valuable output of discovery is not a one-time list of extracted cases. It is a reusable, versioned **document family specification**.

Conceptually:

```yaml
family_id: scj_bulletin_1970s
version: 1
artifact_class: compilation

index:
  expected: true
  candidate_pages: [3, 4, 5, 6]

segmentation:
  start_signals:
    - type: heading_regex
      pattern: "..."
  end_strategy: next_start_or_artifact_end

metadata:
  decision_date:
    source_region: first_pages
    strategies:
      - deterministic_regex
      - model_fallback

  docket_number:
    optional: true

validation:
  minimum_boundary_precision: 0.99
  minimum_boundary_recall: 0.98
```

The exact representation can evolve. The invariant is that family behavior must be versioned and auditable.

A family version records at minimum:

- family/version identity;
- source/court/period applicability signals;
- page-layout detection rules;
- segmentation strategy;
- extraction strategies per field;
- fallback policy;
- validation dataset/version;
- measured metrics;
- code revision;
- enabled/disabled promotion capabilities.

---

## 9. Discovery does not equal acceptance

A model may propose:

```text
"I found 84 decisions"
```

That is only a hypothesis.

Acceptance requires evidence such as:

- comparison against an official index or declared decision count;
- sampled page-boundary review;
- cross-checking repeated headings;
- field-level consistency checks;
- known identifier patterns;
- independent gold annotation;
- explicit review of anomalies.

Possible outcomes:

- `accepted_for_deterministic_execution`;
- `accepted_with_model_fallback`;
- `review_required`;
- `insufficient_structure_confidence`;
- `rejected`.

Failure to understand a document is a valid result.

---

## 10. Matching across heterogeneous sources

The same judicial decision may appear in multiple representations:

- standalone official decision;
- annual/period compilation;
- scanned bulletin;
- later database export;
- tenant-uploaded copy.

Identity resolution must combine multiple signals rather than rely on embeddings alone.

Candidate matching signals include:

```text
court / court organ
normalized decision number
decision date
docket identifiers
party names
opening text fingerprints
normalized text similarity
citation neighborhood
source chronology
```

High-confidence matches may be linked automatically only after benchmarked thresholds exist. Medium-confidence matches route to review. Low-confidence candidates remain separate.

---

## 11. LLM provider architecture

The discovery subsystem depends on a provider abstraction rather than one vendor-specific client throughout the domain code.

Initial conceptual contract:

```text
ModelProvider
  -> structured_generate(...)
  -> classify(...)
  -> analyze_document_sample(...)
```

Provider responses must expose usage/provenance metadata when available.

The first implementation provider is Google Gemini through the Gemini Developer API.

As of September 2026 the default discovery model is:

```text
provider: google
model: gemini-3.8-flash
thinking: medium
```

Rationale:

- generally available rather than preview-only;
- 1M-token input context;
- native PDF/image/multimodal input;
- structured output;
- function calling;
- code execution support;
- designed for autonomous-agent and long-horizon workflows;
- materially cheaper/faster than using a top-tier Pro model for every discovery step.

A cheaper secondary model may be configured for high-volume low-complexity triage. The initial candidate is `gemini-3.1-flash-lite`.

Model IDs and prices are operational configuration, not permanent product invariants. They must be re-benchmarked as provider offerings change.

---

## 12. LLM cost policy

Model calls are not part of ordinary deterministic CI.

Normal pull-request CI remains:

```text
lint
static typing
unit tests
PostgreSQL contracts
Docker/runtime smoke
source-backed deterministic parser regressions
```

External paid-model evaluation runs through an explicit workflow such as:

```text
workflow_dispatch
  -> protected GitHub Environment
  -> provider secret
  -> bounded dataset
  -> hard request/token/cost caps
  -> artifact with results
```

No PR should spend model budget merely because documentation or unrelated code changed.

The workflow must fail closed when the API secret is absent.

---

## 13. GitHub secret contract

The repository must never contain an API key.

Initial secret:

```text
GEMINI_API_KEY
```

Non-secret configuration can be supplied as workflow inputs or repository/environment variables:

```text
LLM_PROVIDER=google
LLM_MODEL=gemini-3.8-flash
LLM_THINKING_LEVEL=medium
```

The API key should preferably live in a GitHub Environment dedicated to model benchmarks/discovery rather than being broadly available to all workflows.

---

## 14. Security boundaries

The structure-discovery agent is less trusted than deterministic code.

It must not receive:

- tenant-private documents unless the selected provider/data policy permits it;
- broad database credentials;
- Supabase service-role keys;
- arbitrary network access by default;
- canonical write privileges.

Agent-produced code, if allowed, executes in a bounded sandbox with explicit inputs and resource limits.

Prompt injection inside legal documents is treated as untrusted document content, not an instruction source.

---

## 15. Promotion policy

The discovery subsystem ends before canonical promotion.

```text
model hypothesis
  -> candidate observation
  -> validation
  -> immutable resolution
  -> promotion policy
  -> canonical corpus
```

An LLM observation cannot bypass the observation/resolution/promotion ledger already established for JurisNexo.

For high-value fields such as decision date, decision number, court, court organ, and case boundary, deterministic or independently corroborated evidence remains preferred.

---

## 16. Implementation sequence

### Phase A — provider and discovery foundation

1. provider-neutral model interface;
2. Google Gemini provider;
3. structured-output contract;
4. deterministic fake provider for tests;
5. manual GitHub Action using `GEMINI_API_KEY`;
6. token/request budget controls;
7. structured benchmark artifact.

### Phase B — document environment

1. page inspection API;
2. text search over artifact pages;
3. deterministic sampling;
4. OCR/image diagnostics;
5. candidate-index detection;
6. bounded Python/regex execution;
7. discovery-run persistence.

### Phase C — family discovery

1. root discovery agent;
2. index interpretation;
3. candidate boundary hypothesis;
4. whole-document validation;
5. candidate family specification;
6. human/gold evaluation;
7. accepted family version.

### Phase D — compiled execution

1. family registry;
2. deterministic adapter execution;
3. model fallback only for declared fields/layouts;
4. anomaly monitoring;
5. re-discovery when drift is detected.

---

## 17. Success criteria for the first discovery experiment

Use several artifacts whose true structure is already substantially known, then hide the existing parser rules from the discovery agent.

Measure:

- candidate case-boundary precision/recall;
- decision-date/decision-number accuracy;
- index interpretation accuracy;
- pages inspected before useful hypothesis;
- model calls;
- input/output token consumption;
- estimated cost;
- wall-clock runtime;
- number of unresolved anomalies;
- whether the generated family specification reproduces results without repeated full-document reasoning.

Compare at minimum:

```text
custom RLM-style discovery agent
vs
simple one-shot/large-context extraction baseline
vs
DocETL-style transformation spike when applicable
```

LOTUS is evaluated later for semantic operations over normalized/segmented collections.

---

## 18. Non-goals

The first discovery implementation is not:

- an unrestricted autonomous agent;
- a replacement for OCR;
- permission to send all corpus documents to a model provider;
- a mechanism for direct canonical database writes;
- a claim that one provider/model will remain optimal;
- a reason to abandon deterministic parsers that already work;
- a substitute for gold evaluation.

The intended system uses expensive intelligence primarily to discover and repair structure, then moves stable repeated work back into cheap, testable, deterministic execution.
