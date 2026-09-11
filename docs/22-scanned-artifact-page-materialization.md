# JurisNexo — Scanned Artifact Page Materialization

## 1. Why this layer exists

Historical legal PDFs frequently do not have a one-to-one relationship between a PDF page and a legally meaningful printed page.

A real February 1980 Dominican Supreme Court Judicial Bulletin exposed several independent problems at once:

- the official artifact is a scan rather than a born-digital publication;
- it contains a substantial OCR/text layer, but the OCR is noisy;
- many physical PDF pages are two-page book spreads;
- adjacent physical pages may be duplicate scans of the same spread;
- printed page numbers are useful but OCR may also produce unrelated numbers near the header;
- XML generated from the OCR layer may contain invalid control characters;
- the official index refers to printed book pages, not PDF physical-page numbers.

Therefore JurisNexo must not use one overloaded `page_number` concept for all of these identities.

---

## 2. Three page identities

JurisNexo distinguishes at least three identities for scanned books and bulletins.

### 2.1 Physical PDF page

This is the immutable source-provenance unit.

```text
artifact SHA-256
  + physical PDF page number
```

It is never deleted or renumbered because a later process believes it is duplicated.

### 2.2 Logical scan region

A physical scan may contain more than one printed page. A derived logical region identifies a geometric subsection of the physical page.

Example:

```text
physical PDF page: 7
region: left
x range: 0..396
printed-page candidate: 184
```

and:

```text
physical PDF page: 7
region: right
x range: 396..792
printed-page candidate: 185
```

The region is a derived view. Its provenance always points back to the physical PDF page and coordinates.

### 2.3 Printed/editorial page number

This is the page number printed in the historical publication and used by indexes, citations, and editorial references.

It is an observation, not automatically canonical truth.

OCR may confuse years, footnote numbers, case numbers, or other numeric text with page numbers. Therefore materialization emits `printed_page_candidates`, which must be resolved through layout/sequence evidence before they are treated as verified printed pagination.

---

## 3. Duplicate scans are aliases, not deletions

Historical digitization may contain repeated scans of the same spread.

JurisNexo may identify likely duplicates using multiple signals such as:

- strong token-set similarity;
- matching printed-page candidates;
- image/perceptual similarity when needed;
- adjacency in the source artifact.

A duplicate diagnosis creates an alias/equivalence observation for processing efficiency.

It does **not**:

- remove a physical page;
- rewrite source provenance;
- change artifact SHA-256;
- silently choose one scan as legal truth.

An agentic discovery environment may inspect one representative scan to avoid paying twice for near-identical content, while every source page remains preserved and traceable.

---

## 4. OCR/text-layer sanitation

OCR output is not trusted to be valid XML or clean Unicode.

For bbox-layout processing, JurisNexo may replace characters forbidden by XML 1.0 solely to make the extraction representation parseable. The number of replacements is recorded as a diagnostic.

This sanitation is not OCR correction.

For example, an OCR token such as:

```text
c<control-char>isación
```

may become:

```text
c�isación
```

The replacement remains visibly uncertain rather than being silently guessed as `casación`.

Semantic correction belongs to a later OCR/model/review layer with its own provenance.

---

## 5. Bbox-based page materialization

When a PDF text layer contains word coordinates, JurisNexo prefers those coordinates over flattening the whole spread into one text string.

Initial flow:

```text
official PDF
  -> immutable physical page
  -> Poppler bbox-layout words
  -> XML sanitation diagnostics
  -> geometric left/right logical regions
  -> printed-page candidates
  -> duplicate-scan diagnostics
  -> discovery-page view
```

This allows structure discovery to reason about the same editorial units a human sees on the scanned book.

The current two-region split is an initial strategy for book spreads, not a universal invariant. Other artifacts may need:

- single-page mode;
- three or more columns;
- rotated pages;
- foldouts;
- marginal annotations;
- image-only OCR regions.

Layout classification must eventually choose the appropriate materialization strategy per artifact/page family.

---

## 6. Discovery-environment policy

The LLM/RLM-style discovery environment should consume a compact logical view rather than blindly consuming every physical PDF page.

A discovery page should retain enough provenance to display something conceptually like:

```text
logical sequence: 42
source physical pages: [45, 46]
region: right
printed-page candidates: [223]
text extraction method: embedded_ocr_layer
```

The agent may search and inspect the logical sequence, while every result can still be mapped back to the source scan.

This is especially important when the source contains duplicated scans. Deduplication for agent cost does not alter source evidence.

---

## 7. Index-to-page matching

Historical indexes commonly reference printed pagination rather than PDF pagination.

The matching flow should therefore be:

```text
index entry
  -> candidate printed page number
  -> resolved printed-page sequence
  -> logical page region
  -> physical PDF page + coordinates
```

A stable offset such as `printed page 183 -> physical page 5` may be useful evidence for a particular artifact, but it must not be hard-coded as a family rule until validated across the relevant publication family.

Index parsing and page-number resolution can be model-assisted during discovery, then compiled into deterministic rules if the publication family proves stable.

---

## 8. First real-source evidence

The initial source-backed experiment uses the official Poder Judicial publication:

```text
Boletín Judicial Núm. 831
February 1980
Suprema Corte de Justicia
```

The acquisition workflow records:

- official source URL;
- exact PDF SHA-256;
- byte size;
- physical page count;
- PDF metadata;
- text-layer density;
- rendered visual samples;
- logical region diagnostics;
- OCR sanitation count;
- likely adjacent duplicate scans.

This artifact is benchmark evidence, not yet a validated family specification.

No accuracy claim about historical segmentation should be made until a manually verified subset of this real bulletin has gold boundaries and metadata.

---

## 9. Database consequence

The existing `artifact_pages` concept remains appropriate for immutable physical source pages.

If logical page regions become persistent production entities, they should be represented separately rather than changing the meaning of `artifact_pages`.

A future persistent model may need concepts similar to:

```text
artifact_pages
page_regions
printed_page_observations
page_equivalence_observations
extraction_observations
```

The exact schema remains an open implementation decision. The invariant is that physical source provenance and derived logical structure are different layers.

---

## 10. Promotion boundary

No logical-region inference, duplicate diagnosis, OCR correction, printed-page candidate, or model-generated structure may directly create canonical legal metadata.

The chain remains:

```text
source page
  -> derived region / extraction observation
  -> candidate structure
  -> validation
  -> legal metadata observations
  -> resolution
  -> controlled promotion
```

This keeps document intelligence powerful without weakening JurisNexo's evidence model.
