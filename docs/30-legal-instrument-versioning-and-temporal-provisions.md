# JurisNexo — Legal Instrument Versioning and Temporal Provisions

## 1. Purpose

A normative legal instrument is not identical to one PDF, one publication, one
consolidated text, or one historical snapshot. A provision is also not identical
to the wording or number it happens to have at one moment in time.

The durable identity rule is:

```text
legal instrument != instrument version != legal document != source artifact
stable provision != provision version
amending instrument != amended instrument version
```

This distinction is required before large-scale legislative ingestion. Without
it, a later amendment either overwrites history or creates false duplicate laws
and articles.

## 2. Stable legal instrument identity

`corpus.legal_instruments` represents a stable normative instrument such as a
constitution, code, statute, decree, regulation, administrative resolution,
circular, treaty, ordinance, or rule.

Examples:

```text
Ley 100-20                    -> one stable instrument
Código Civil                  -> one stable instrument
Constitución                  -> one stable instrument
Ley 25-22 that amends 100-20  -> a different stable instrument
```

The last distinction is essential. A law that amends another law is not merely a
new row in the target law's version table. It remains an independently enacted
legal instrument with its own source, identity, dates, provisions, and legal
effects.

Identifiers are stored separately in `legal_instrument_identifiers` so official
numbers, registry identifiers, aliases, and source-specific forms do not have to
be collapsed into one string.

## 3. Instrument versions

`corpus.legal_instrument_versions` represents a temporal/legal text state of one
stable instrument.

Initial version kinds include:

- original;
- amended;
- official consolidation;
- editorial consolidation;
- corrected text;
- historical snapshot.

A version has an optional legal-validity interval (`valid_from`, `valid_to`) and
an explicit derivation method/status. A derived version may refer only to a
previous version of the same instrument.

The model deliberately does **not** impose a global no-overlap rule on version
intervals. Two representations can legitimately overlap, for example an enacted
text history and an official or editorial consolidation. A future canonical
version stream may add stricter non-overlap semantics once the source corpus
proves that distinction is stable.

## 4. Source documents remain separate

`corpus.legal_instrument_version_documents` links a version to the legal
documents that evidence or render it. Roles include official text, official
publication, consolidated text, corrected text, historical copy, and editorial
text.

This preserves the existing provenance architecture:

```text
stable instrument
    -> instrument version
        -> legal document representation
            -> immutable source artifact
                -> physical pages
```

A consolidated text therefore never replaces the original publication artifact.

## 5. Stable provision identity

`corpus.legal_provisions` intentionally contains very little descriptive text.
It answers only: **which continuing legal provision is this?**

The following properties live in a version instead:

- parent/hierarchy;
- article/paragraph label;
- ordinal;
- heading;
- text.

That choice is deliberate because all of them can change.

Example:

```text
2020 version:
Capítulo I / Artículo 10 / "Texto A"

2024 version:
Capítulo II / Artículo 11 / "Texto B"
```

If the legal history proves this is the same provision after renumbering and
relocation, both rows point to the same `legal_provisions.id` while their
`legal_provision_versions` remain different.

## 6. Provision versions

`corpus.legal_provision_versions` binds one stable provision to one instrument
version. It enforces that the provision, its parent, and the instrument version
all belong to the same legal instrument.

Sibling labels are unique only inside one instrument version and parent. Thus:

```text
Artículo 10 / Párrafo I
Artículo 11 / Párrafo I
```

is valid, while two distinct `Párrafo I` children under the same article and
same version are a structural conflict.

This is separate from `corpus.legal_document_provisions`, which remains the
source/document-facing structure extracted from a particular legal document.
The temporal canonical layer does not overwrite that source structure.

## 7. Mapping canonical provision versions back to source text

`corpus.legal_provision_version_sources` links a canonical temporal provision
version to the exact `legal_document` and, when available, the exact
`legal_document_provision` from which it was established.

This means JurisNexo can answer both:

```text
What did Article 7 say on a given date?
```

and:

```text
Which source document/provision supports that historical wording?
```

without treating a reconstructed consolidation as primary source merely because
it is convenient for retrieval.

## 8. Lifecycle events are not one generic date

Legislation has multiple legally meaningful dates. `corpus.legal_instrument_events`
records events such as:

```text
adopted
enacted
promulgated
published
effective
amended
corrected
suspended
reinstated
repealed
expired
```

Each event carries its own date status, source/evidence, verification state, and
method. A date marked as verified cannot be stored without an actual date.
Unknown dates remain unknown.

This avoids overloading `document_date`, `published_at`, or `effective_from` with
meanings they cannot safely carry across jurisdictions and instrument types.

## 9. Amendment effects

`corpus.legal_amendment_effects` represents the legal effect produced by one
instrument upon another instrument or provision.

Initial effects include:

```text
amends
inserts
replaces
renumbers
repeals
partially_repeals
suspends
reinstates
corrects
```

The source instrument and target instrument are always explicit. The target may
optionally be a stable provision. Evidence and raw effect wording can be kept
alongside the normalized effect.

Example:

```text
Ley 25-22
   --replaces effective 2022-04-01-->
Ley 100-20 / stable Article 7 identity
```

The new 2022 text of Article 7 is represented separately as a provision version
under the amended version of Ley 100-20.

This prevents a damaging shortcut:

```text
WRONG: Ley 25-22 == version 2 of Ley 100-20
```

They are different legal instruments connected by an amendment effect.

## 10. Temporal semantics and bitemporality

This migration introduces **legal valid time** through version validity intervals
and dated lifecycle/effect records. It does not yet claim full bitemporality.

The next temporal layer must distinguish:

```text
valid time
    when the legal state was legally applicable

recorded/system time
    when JurisNexo learned, corrected, or accepted that state
```

Those two clocks must not be faked by reusing `created_at`. A dedicated
bitemporal migration should add/query them deliberately after this stable
identity layer is proven by PostgreSQL tests.

## 11. Invariants

The implementation must preserve these rules:

1. One stable instrument can have multiple temporal versions.
2. A derived version cannot descend from a version belonging to another instrument.
3. One stable provision can have different text, label, ordinal, and parent across versions.
4. A provision version cannot combine an instrument version with a provision from another instrument.
5. Source legal documents remain separate from canonical temporal versions.
6. Cross-scope version/document links are rejected by PostgreSQL.
7. Verified lifecycle dates cannot be manufactured when the date is unknown.
8. An amending law remains a distinct instrument from the law it changes.
9. Amendment effects identify source instrument, target instrument, and optional target provision explicitly.
10. Repeated child labels are scoped to their parent within a particular instrument version.

## 12. Deferred work

This model intentionally leaves several later concerns separate:

- full bitemporal recorded/system-time history;
- authoritative version-selection rules for a date and jurisdiction;
- explicit amendment-operation reconstruction at character/word level;
- provision split/merge lineage when one provision becomes several or vice versa;
- contextual binding/precedential effect;
- multi-parent legal taxonomies;
- normalized authorities beyond preserved `issuing_authority_raw`.

Those are real gaps, but folding them into this migration would make it harder to
prove which legal identity rules are actually correct. Each should get its own
schema contract and adversarial tests.
