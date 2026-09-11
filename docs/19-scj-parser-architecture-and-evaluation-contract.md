# JurisNexo — SCJ Parser Architecture and Evaluation Contract

## 1. Objective

The SCJ parser must transform primary-source compilation pages into auditable candidate judicial decisions without silently inventing boundaries or metadata.

The parser is considered a source-processing subsystem, not a retrieval feature. Its output must be deterministic by default, versioned, provenance-aware, and measurable against human-reviewed source pages.

## 2. Architectural rule

Do not build one monolithic function named conceptually `parse_scj_document()` containing every historical regex.

Use this shape instead:

```text
artifact pages
    -> publication/layout family detector
    -> page signatures
    -> contiguous segmenter
    -> layout-specific metadata extractor
    -> common MetadataObservation[]
    -> reconciliation
    -> resolution ledger
    -> reviewed promotion
```

The detector and extractors are related but separate concerns.

## 3. Core types

The parser layer should expose explicit domain types similar to:

```text
SCJLayoutFamily
PageLayoutDetection
CaseBoundaryCandidate
CaseSegment
MetadataObservation
ParserDiagnostic
```

### `SCJLayoutFamily`

Initial families should include at least:

```text
principales_decisiones_2023_2024
principales_decisiones_2025_primera_sala
principales_decisiones_2025_segunda_sala
principales_decisiones_2025_tercera_sala
principales_decisiones_2025_pleno_resolution
unknown
```

These names describe observed publication grammars, not permanent claims that every decision in a calendar year uses exactly one format.

### `PageLayoutDetection`

Minimum fields:

- page number;
- layout family;
- stable signature key when available;
- evidence spans or matched labels used by the detector;
- deterministic detector version;
- status (`recognized`, `ambiguous`, `unknown`).

Avoid an uncalibrated floating-point confidence merely to look sophisticated. If confidence is introduced, it must have measured meaning.

### `CaseSegment`

Minimum fields:

- layout family;
- start page;
- end page;
- stable segment signature;
- segmentation method/version;
- status (`candidate`, `verified`, `ambiguous`, `rejected`);
- diagnostics.

A segment must never cross from one confidently recognized stable layout identity into another without an explicit boundary event.

## 4. Publication family: 2023–2024 principal decisions

Observed source pages use a materially different structure from 2025.

A strong deterministic signal is the formal page heading:

```text
SENTENCIA DEL 29 DE FEBRERO DE 2024, NÚM. SCJ-SS-24-0138
```

Variants must account for capitalization, accents, whitespace, and punctuation while remaining strict enough not to turn citations in body text into boundaries.

The parser should extract directly from this heading when present:

- decision date;
- decision number;
- likely organ from the SCJ identifier prefix when that mapping is explicitly defined and tested.

The segmenter must first determine whether this formal sentence heading repeats on every page or appears only on case starts for each publication sub-generation. This behavior must be learned from fixtures, not assumed globally.

## 5. Publication family: 2025 structured repeated headers

The 2025 early-year compilation demonstrates repeated page-header metadata.

### Primera Sala

Observed signals include:

- `SCJ-PS-...`;
- expediente labels;
- `Partes`;
- `Materia`;
- `Decisión`;
- `Ponente`.

The stable case identity should not be based only on every SCJ number found in the page. Body citations must be excluded from boundary identity.

### Segunda Sala

Observed repeated header signals include:

- `Exp.`;
- `Rc.` / related recurrente label variants;
- `Fecha:`.

The first page may also contain a sentence identifier such as `SCJ-SS-...`.

The parser should emit the labeled date as a header date observation instead of requiring only the long-form decision formula.

### Tercera Sala

Observed signals include:

- `Exp. núm.` / `Exps. núms.` variants;
- party-role labels;
- `Materia`;
- `Decisión`;
- an SCJ-TS decision number associated with the case.

Structured Tercera Sala grammar must outrank incidental `SCJ-PS-*` or other citations appearing near the top of body text.

### Pleno / resolution style

Observed signals include combinations such as:

- `Resolución núm.`;
- `Expediente núm.`;
- other structured header metadata.

Do not coerce this material into a Sala grammar merely because an SCJ reference occurs nearby.

## 6. Segmentation algorithm contract

For layouts with repeated page headers, the baseline algorithm is:

1. detect a structured layout signature independently on every physical page;
2. normalize only the fields that define page-header identity;
3. group contiguous pages with the same stable signature;
4. treat a confidently different stable signature as a boundary;
5. allow unrecognized pages inside a run only under an explicit bounded bridging rule;
6. never silently merge two conflicting recognized signatures;
7. retain unknown/ambiguous pages for review.

A bridging rule is required because title/front matter, blank pages, diagrams, or extraction artifacts may lack recognizable headers.

The bridging rule must be conservative and tested. Example policy to evaluate:

```text
recognized A
unknown <= N pages
recognized A
=> one candidate segment with diagnostic gap
```

but:

```text
recognized A
unknown pages
recognized B
=> boundary; never bridge A to B
```

The value of `N` must be selected from real corpus evidence.

## 7. Metadata observation contract

Layout-specific extractors must emit the existing common `MetadataObservation` domain contract rather than writing canonical cases directly.

Every observation includes:

- field name;
- raw value;
- normalized typed value;
- extraction method name;
- source page;
- character offsets;
- stable observation key.

Required near-term fields:

- `decision_number`;
- `docket_number` / docket candidates;
- `decision_date_candidate`;
- `matter`;
- `decision_summary`;
- `rapporteur`;
- parties/party-role candidates where grammar is sufficiently stable;
- court-organ candidate when deterministically supported.

Do not collapse multiple dockets into one semantic identity before reconciliation.

## 8. Date parsing

The date subsystem should accept several explicit evidence channels:

- formal sentence heading date (`SENTENCIA DEL ...`);
- repeated structured `Fecha:` label;
- primary-text decision formula;
- official metadata import;
- manual verification;
- future bounded LLM assist.

Each extraction pattern must map to a named evidence channel and method version.

The reconciliation rule remains conservative: disagreement between normalized dates is a conflict, not an invitation to choose the most convenient value.

## 9. Court-organ parsing

Do not infer chamber only from an arbitrary cited SCJ identifier in body text.

Preferred organ signals, in order of reliability to evaluate:

1. explicit structured chamber heading;
2. stable publication layout family;
3. primary decision identifier associated with the formal case heading;
4. weaker supporting signals.

Prefix mapping such as `PS`, `SS`, `TS`, or other identifiers must be represented in a tested mapping table and must support `unknown` rather than raising confidence artificially.

## 10. Diagnostics are product data

The parser should return explicit diagnostics such as:

- unknown layout;
- conflicting page signatures;
- missing expected primary decision number;
- multiple candidate primary decision numbers;
- date conflict;
- docket ambiguity;
- unexpectedly long/short segment;
- gap of unrecognized pages inside an otherwise stable run;
- parser pattern not applicable to publication family.

These diagnostics should drive manual-review queues and benchmark analysis.

## 11. Golden fixtures

Do not unit-test only synthetic one-line strings.

The parser test suite should include exact extracted-text fixtures derived from representative real pages, with sensitive/nonessential bulk text minimized only if provenance to the original page remains documented.

The initial fixture matrix must cover:

- 2023 first-period formal sentence heading;
- 2024 first-period formal sentence heading;
- 2024 second/third-period variants;
- 2025 Primera Sala;
- 2025 Segunda Sala;
- 2025 Tercera Sala;
- 2025 Pleno/resolution;
- at least one page containing an incidental citation that must **not** change layout identity;
- at least one unknown/front-matter page;
- at least one malformed or extraction-damaged header.

## 12. Evaluation dataset

Coverage profiling and gold accuracy are separate artifacts.

### Coverage profile

May be computed automatically over the full corpus and reports:

- pages recognized;
- pages unknown;
- candidate segments;
- fields emitted;
- diagnostics;
- distribution by layout family.

It must never be called precision/recall.

### Gold dataset

A human-reviewed stratified sample should label:

- correct segment boundaries;
- correct primary decision number;
- correct dockets;
- correct decision date;
- correct organ;
- page-span correctness;
- whether parser-required manual review is appropriate.

Sampling must be stratified by publication generation/layout and include hard/unknown cases.

## 13. Release thresholds

Initial automatic canonical-promotion thresholds should be intentionally strict.

Before a layout family can automatically promote core identity/date metadata, require at minimum a locked gold set demonstrating:

- boundary precision >= 99%;
- boundary recall >= 98%;
- decision-number precision >= 99.5%;
- decision-number recall >= 99%;
- decision-date precision >= 99%;
- decision-date recall >= 97% where the source contains an explicit parseable date;
- court-organ precision >= 99%;
- zero known cross-case page-provenance violations;
- manual-review routing for unresolved conflicts.

These are engineering release gates, not claims about statistical certainty. They may be tightened after the first reviewed dataset.

If a layout family does not meet the gate, it may still be ingested as candidate/unverified data, but its uncertain fields must not be silently promoted as canonical verified facts.

## 14. LLM fallback policy

Do not introduce an LLM simply because deterministic coverage is incomplete.

Evaluate an LLM fallback only after deterministic layout families and gold evaluation expose a residual class that is:

- material;
- difficult to solve with stable rules;
- sufficiently bounded to verify against source text;
- measurable for precision/recall/cost/latency.

LLM extraction must emit observations with explicit method/model/prompt/version provenance and must never bypass reconciliation or the resolution ledger.

## 15. Definition of parser trustworthiness

The parser is not trustworthy because it successfully processed thousands of pages.

It is trustworthy when:

```text
known publication families are explicitly recognized
+ boundaries are measured against human gold
+ core metadata is measured per layout family
+ unknowns remain unknown
+ conflicts remain conflicts
+ all observations retain page/offset provenance
+ canonical promotion is separately controlled
```

That is the standard required before JurisNexo treats the SCJ source corpus as dependable infrastructure rather than a convenient collection of searchable text.
