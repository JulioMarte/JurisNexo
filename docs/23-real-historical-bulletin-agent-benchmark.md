# JurisNexo — Real Historical Bulletin Agent Benchmark

## 1. Purpose

The synthetic discovery fixtures proved that the bounded agent loop, structured outputs, tool budget, and scoring infrastructure work. They do not prove that JurisNexo can discover structure in a real historical legal publication.

The first real-source agent benchmark uses the official Supreme Court publication:

- publication: `Boletín Judicial Núm. 831`;
- period: February 1980;
- publisher/source: Poder Judicial de la República Dominicana;
- source origin: `https://transparencia.poderjudicial.gob.do/documentos/PDF/boletines/1980/FEBRERO.pdf`;
- observed SHA-256 during source-backed acquisition: `0edd1beefaf198cb88db26127fb83cbd3a56832176af24b57e4e94e48e37f2f2`.

This experiment tests whether an agent can use document structure rather than brute-force reading.

---

## 2. What the model is allowed to know

The benchmark prompt may tell the model:

- the artifact identity;
- that its task is document-structure discovery;
- that it should investigate whether the `SUMARIO` functions as an index;
- that it should verify multiple index references before proposing a reusable segmentation strategy;
- what read-only tools are available.

The prompt must **not** disclose the manually observed correct page references or case boundaries.

In particular, the benchmark prompt must not tell the model that early decision starts have been observed at printed pages such as 183, 189, 193, or 198.

Those facts may be used later as evaluation evidence, but not as model input.

---

## 3. Deterministic preprocessing

The model does not receive the raw 181 PDF pages as a flat prompt.

Before agent exploration, deterministic code performs:

```text
official PDF
  -> verified TLS acquisition
  -> %PDF validation
  -> SHA-256
  -> Poppler bbox OCR/text geometry
  -> XML-control sanitation diagnostics
  -> physical-page materialization
  -> left/right logical regions
  -> adjacent-rescan equivalence detection
  -> logical document view
  -> observed sequence-consistent printed-page resolution
  -> read-only DocumentEnvironment
```

No missing printed page is invented merely because continuity would make it plausible.

Duplicate scans remain part of immutable provenance even when one representative region is used for model reading.

---

## 4. Agent tools

The benchmark exposes only bounded read operations:

```text
get_page(view_page_number)
get_printed_page(printed_page_number)
get_pages(start_view_page, end_view_page)
search_text(literal_query)
sample_pages(strategy, count)
finish
```

`get_printed_page` is deterministic. The model proposes a printed page number; JurisNexo either resolves that number to an observed logical region or rejects the request.

Returned evidence includes:

- derived view-page number;
- resolved printed/editorial page number when available;
- physical PDF page or pages supporting the logical region;
- side of the scan spread;
- representative physical scan.

The agent has no canonical database-write authority.

---

## 5. Initial experiment question

The first run is intentionally narrower than whole-book extraction:

> Can the agent find and interpret the real `SUMARIO`, follow multiple page references using resolved printed pagination, confirm that referenced regions begin judicial decisions, and propose a cautious reusable segmentation hypothesis?

This isolates index interpretation and navigation before asking the model to segment the entire volume.

---

## 6. Frozen first-run configuration

Initial defaults:

```text
provider: Google Gemini Developer API / Interactions
model: gemini-3.8-flash
service tier: flex
thinking level: medium
max model calls: 8
max total tokens: 40,000
```

The workflow is manual (`workflow_dispatch`) and uses the protected `llm-benchmark` GitHub Environment.

Changing the model, tier, thinking level, or budgets creates a different benchmark configuration and must be recorded in the resulting artifact.

---

## 7. Evidence recorded for every run

The benchmark artifact records at minimum:

- model/provider/version;
- service tier;
- source origin and source SHA-256;
- physical-page count;
- duplicate-scan count;
- scan-group count;
- logical view-page count;
- resolved printed-page count;
- XML sanitation count;
- every model tool decision and rationale;
- every bounded tool output returned to the model;
- model response IDs when available;
- per-step usage;
- aggregate token usage;
- final structured document-family hypothesis.

This is a benchmark trace, not canonical corpus data.

---

## 8. First-run qualitative acceptance criteria

Before building a numeric gold evaluator for the real bulletin, the first live run is considered informative only if all of the following are inspectable from the trace:

1. the agent discovers or directly inspects the `SUMARIO` rather than assuming a case grammar from the cover;
2. it uses at least two independently resolved printed-page targets from the index;
3. target evidence contains decision-start material rather than arbitrary body citations;
4. it does not confuse view-page numbers with editorial printed-page numbers;
5. it retains source provenance in the tool evidence;
6. it expresses unresolved OCR/index ambiguity rather than silently repairing uncertain text;
7. its final family hypothesis identifies validation work still required.

These are not production release gates. They determine whether the next investment should be a manually reviewed historical gold subset.

---

## 9. Next evaluation stage

After the first trace is inspected, freeze a small independent gold subset from the real source before tuning the prompt against failures.

The gold subset should include:

- several `SUMARIO` entries;
- verified printed decision-start pages;
- exact start/end printed-page ranges;
- decision date;
- matter/document type where visible;
- party names where reliably recoverable;
- physical PDF provenance for each gold observation.

Then score:

```text
index-reference accuracy
printed-page navigation accuracy
start-boundary precision / recall
end-boundary precision / recall
exact-segment F1
metadata precision / recall
model calls
tokens
wall-clock latency
estimated cost
```

Prompt/model changes after that point must be evaluated against a separated development/test split rather than repeatedly tuning on the same few cases.

---

## 10. What success would and would not prove

A successful first run would show that the architecture can combine noisy OCR, deterministic page/provenance materialization, and selective model reasoning on an authentic historical publication.

It would **not** prove that:

- the entire 1980 bulletin is correctly segmented;
- all historical bulletins share the same family grammar;
- OCR is sufficiently accurate for canonical metadata;
- model output can bypass human/gold validation;
- this model/provider is permanently optimal;
- deterministic parsers are unnecessary after a family has been learned.

The intended end state remains:

```text
agent discovers candidate structure
  -> independent validation
  -> accepted family specification
  -> deterministic repeated execution
  -> model fallback only where explicitly justified
```
