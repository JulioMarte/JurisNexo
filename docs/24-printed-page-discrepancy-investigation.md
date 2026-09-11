# Printed-page discrepancy investigation

## Purpose

Historical legal bulletins can contain three different facts that must never be collapsed into one:

1. **reference as printed** — what the SUMARIO or index says;
2. **observed document location** — where the referenced material is actually visible in the derived document view;
3. **normalized decision start** — the best evidence-backed start page JurisNexo may later use for segmentation.

A disagreement between these facts is not automatically an OCR error and is not automatically an editorial error. It is an investigation target.

## Environment contract

`DocumentEnvironment` exposes both view-page navigation and resolved printed/editorial pagination.

The new bounded operation is:

```text
get_printed_pages(start_printed_page, end_printed_page)
```

It:

- accepts only positive inclusive printed-page ranges;
- is bounded independently from ordinary view-page range reads;
- returns every resolved page in the requested editorial span;
- preserves view-page identity and physical source provenance for each returned page;
- reports unresolved printed numbers instead of inventing continuity or silently skipping the fact that resolution is missing;
- never changes canonical physical-page identity.

The default agent budget allows at most seven printed pages per range call. Larger investigation must be explicit and incremental.

## Agent discrepancy protocol

When an index target does not clearly match the expected heading, parties, date, or other identity evidence, the discovery agent must not immediately report only that the reference is inconsistent.

The expected behavior is:

```text
index reference
    ↓
get_printed_page(reference)
    ↓
clear identity match?
    ├─ yes → confirmed_at_reference
    └─ no  → inspect a small printed-page neighborhood
              ↓
           get_printed_pages(...)
              ↓
           determine whether evidence supports:
              - confirmed_nearby
              - unresolved
              - contradictory
```

A nearby confirmation does **not** rewrite the source reference. Both facts remain recorded.

## Structured investigation evidence

`DocumentStructureHypothesis.index_reference_investigations` records:

- `reference_as_printed`;
- `expected_description`;
- `resolution_status`;
- `observed_decision_start_printed_page` when supported;
- printed and view pages actually inspected;
- observed description;
- explanation;
- confidence.

Allowed resolution states are:

- `confirmed_at_reference`: the inspected evidence supports a decision start on the printed reference itself;
- `confirmed_nearby`: the source reference is preserved but nearby inspected evidence supports a different start page;
- `unresolved`: the available evidence is insufficient to decide;
- `contradictory`: inspected evidence materially conflicts with the reference and no supported nearby resolution was established.

Confirmed states require an observed start. `confirmed_at_reference` requires that the observed start equal the printed reference, while `confirmed_nearby` requires a different start.

## Evaluation contract

The historical bulletin scorer now separates two questions:

1. **navigation status** — did deterministic printed-page navigation resolve pages with source provenance and intersect the frozen gold set?
2. **semantic status** — did the final hypothesis explicitly confirm investigated index references with evidence-backed resolution states?

The original frozen gold and its original navigation acceptance rule are not rewritten after observing the first paid run. `status` therefore continues to represent that frozen navigation rule for comparability, while `semantic_status` is reported separately for the stronger contract.

This avoids the previous ambiguity where a successful `get_printed_page(353)` could be called “verified” even when the content on page 353 did not actually confirm the decision identity.

## Safety and truthfulness rule

JurisNexo must prefer:

```text
"the SUMARIO prints 353; inspected evidence supports a start on 354"
```

over either of these lossy claims:

```text
"the correct page is 354"
"page 353 is wrong"
```

unless independent evidence is sufficient to make the stronger claim. Source statements and JurisNexo interpretations remain separately auditable.
