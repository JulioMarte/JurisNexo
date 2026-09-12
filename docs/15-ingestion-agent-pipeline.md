# JurisNexo — Ingestion Agent Pipeline

## 1. Purpose

This document defines the MVP ingestion pipeline for messy legal source documents after adopting OpenAI Agents SDK as the default agent runtime.

The ingestion system must convert source artifacts into trustworthy, reusable case records without assuming that OCR, indexes, printed pagination, or document boundaries are reliable.

## 2. Core rule

Use LLMs for ambiguity and interpretation. Use deterministic services for identity, access, persistence, provenance, and evidence integrity.

```text
LLM responsibilities
    -> interpret damaged OCR
    -> infer candidate structure
    -> compare semantic identity
    -> inspect ambiguous boundaries
    -> extract legal content
    -> identify uncertainty

Deterministic responsibilities
    -> artifact identity/checksum
    -> page addressing
    -> source/version membership
    -> database constraints
    -> tenant authorization
    -> evidence traceability
    -> required workflow gates
```

## 3. Stage model

```text
ACQUIRE SOURCE
    ↓
BUILD DOCUMENT WORKSPACE
    ↓
STRUCTURE DISCOVERY
    ↓
STRUCTURE AUDIT
    ↓
DECISION EXTRACTION
    ↓
EXTRACTION AUDIT
    ↓
CORPUS COMMIT
    ↓
OPTIONAL ENRICHMENT
```

Every stage produces a versioned artifact that can be inspected and benchmarked independently.

## 4. Document workspace

The workspace is the tool-facing representation of one source artifact.

It should provide capabilities rather than expose implementation details:

```text
search_document(query)
read_page(page_id)
read_pages(range)
resolve_printed_page(number)
render_page_image(page_id)
inspect_neighbor_pages(page_id, radius)
get_artifact_metadata()
record_observation(...)
```

The workspace may internally use OCR text, page geometry, rendered images, logical views, or source-specific mappings. Those are implementation choices. The agent sees stable capabilities.

The workspace must preserve enough identifiers to map every observation back to the original source artifact.

## 5. Structure discovery

The Structure Agent should be allowed to investigate iteratively rather than being forced into a fixed page-reading script.

Expected output should include:

- artifact class;
- likely index/table-of-contents regions;
- candidate decision/case boundaries;
- boundary confidence;
- anomalies;
- unresolved references;
- evidence objects supporting each important claim;
- recommended focused follow-up if needed.

A structural hypothesis is never persisted as canonical merely because the model emitted valid JSON.

## 6. Structure audit

The Structure Auditor receives the hypothesis plus independent access to the workspace.

It should test the most failure-prone claims first:

- candidate starts/ends;
- transitions between cases;
- continued decisions;
- index-to-destination consistency;
- duplicate scans;
- missing or repeated printed pages;
- OCR-damaged references;
- conflicting names/dates;
- neighboring content leakage.

Output states may include:

```text
APPROVED
APPROVED_WITH_AMENDMENTS
MORE_INVESTIGATION_REQUIRED
REJECTED
SOURCE_QUALITY_BLOCKED
```

Approval must identify which boundaries/evidence were checked.

## 7. Full-decision extraction

The Extraction Agent operates on one approved or sufficiently bounded decision at a time.

The first priority is faithful content capture, not deep interpretation.

Recommended progressive layers:

### Layer A — source-faithful reconstruction

- ordered decision text;
- page/span provenance;
- gaps or unreadable regions;
- OCR/image fallback notes.

### Layer B — structural sections

- heading/caption;
- parties;
- procedural history;
- facts;
- party arguments;
- court analysis/reasoning;
- dispositive/outcome;
- signatures/administrative tail where relevant.

### Layer C — metadata

- court/chamber;
- date;
- decision number;
- docket/reference number;
- matter/procedure;
- parties;
- source citation.

### Layer D — references

- statutes/articles;
- regulations;
- cited decisions;
- cited institutions/documents;
- unresolved references.

### Layer E — deep legal enrichment

Only when useful and benchmarked:

- legal issues;
- holdings;
- Legal Elements/factors;
- proposition-level relationships;
- citation treatment;
- later-treatment signals.

Layers may use separate agents/models when doing so improves measurable quality or cost.

## 8. Extraction audit

The Extraction Auditor should independently verify material fields and claims against the source.

Required checks should include, where applicable:

- text belongs to the intended decision;
- no adjacent decision content leaked in;
- extracted dates/numbers/parties appear in evidence;
- dispositive text is not confused with argument or commentary;
- holdings are distinguished from party positions;
- cited authorities are actually present;
- unresolved or unreadable source regions remain marked;
- source passages exist for material semantic fields.

The auditor may downgrade, reject, or request re-extraction.

## 9. Evidence objects

Avoid parallel arrays whose semantic relationship is implicit.

Prefer typed evidence objects:

```json
{
  "artifact_id": "...",
  "source_version": "...",
  "view_page": 12,
  "printed_page": 189,
  "role": "decision_header",
  "span_ref": "...",
  "observation": "METALDOM decision header",
  "derived": false
}
```

For index discrepancies, keep index evidence and destination evidence distinct.

Example:

```json
{
  "reference_as_printed": 353,
  "index_evidence": [{"view_page": 4, "role": "index_entry"}],
  "destination_evidence": [{"printed_page": 353, "view_page": 176}],
  "observed_start": null,
  "resolution_status": "contradictory"
}
```

Do not silently normalize source errors.

## 10. Runtime use

OpenAI Agents SDK provides the generic agent/tool runtime. JurisNexo provides the document tools and stage orchestration.

The SDK should not decide the whole ingestion DAG dynamically.

Explicit orchestration remains:

```python
structure = run_structure_agent(workspace)
review = run_structure_auditor(workspace, structure)

if review.allows_extraction:
    extraction = run_extraction_agent(workspace, review.approved_boundaries)
    extraction_review = run_extraction_auditor(workspace, extraction)

if extraction_review.allows_commit:
    corpus_api.commit(...)
```

Implementation may differ, but the semantic gates should remain visible.

## 11. Specialist delegation

Dynamic agents-as-tools/handoffs are appropriate for bounded ambiguity, such as:

- OCR/image specialist;
- printed-page/reference resolver;
- citation resolver;
- boundary investigator;
- metadata reconciler.

Specialists should receive the minimum task/context needed and return structured observations with evidence.

Do not allow specialist delegation to erase the parent stage's responsibility for final output.

## 12. Cost strategy

Model selection should be stage-specific.

Potential policy:

- cheap/fast model for routine structure and extraction;
- stronger model only when confidence/evidence checks expose ambiguity;
- independent verifier model for high-risk fields or difficult sources;
- visual-capable model only for pages where text extraction is insufficient.

Escalation thresholds must eventually be benchmark-calibrated, not arbitrary constants.

## 13. Reproducibility

Persist enough execution metadata to reproduce and diagnose:

- source artifact/version/checksum;
- pipeline stage;
- agent role/version;
- prompt/instruction version;
- model/provider/version/configuration;
- tool calls and evidence identifiers;
- structured output version;
- audit result;
- token/cost/latency metadata;
- failure taxonomy.

Do not persist hidden chain-of-thought as a requirement for reproducibility.

## 14. Benchmark gates

Each layer should have its own tests before relying on end-to-end success.

Structure benchmarks:

- index detection;
- boundary precision/recall;
- discrepancy resolution;
- duplicate/continuation handling.

Extraction benchmarks:

- text completeness/fidelity;
- metadata field accuracy;
- citation extraction accuracy;
- semantic-role classification;
- evidence correctness.

Audit benchmarks:

- error-detection recall;
- false rejection rate;
- unsupported-claim detection;
- boundary-leakage detection.

A workflow process exit of `success` is not sufficient evidence of semantic quality.

## 15. Migration from current historical harness

Reuse what is domain-specific and already valuable:

- source acquisition/checksum validation;
- `DocumentEnvironment`/logical page capabilities where useful;
- frozen historical gold;
- provenance concepts;
- discrepancy investigation concepts;
- benchmark scorer patterns.

Replace or retire only generic runtime machinery after the SDK implementation proves comparable or better behavior.

The current historical bulletin remains a regression case, not the architecture itself.
