# Acquisition reconciliation

## Storage layout

Official artifacts are content addressed and partitioned by authoritative source:

```text
official/
  constitutional_court/
    <sha256-prefix>/
      <sha256>.pdf
  supreme_court/
    <sha256-prefix>/
      <sha256>.pdf
```

The source segment is part of the storage contract. Documents from different authoritative
sources are never mixed under one undifferentiated prefix. The SHA-256 remains the immutable
content identity inside each source partition.

Do not create physical directory objects in S3. S3-compatible storage uses object-key prefixes;
creating zero-byte folder markers adds no integrity and complicates provider portability.

## Reconciliation contract

The authoritative source inventory is compared against two durable layers:

1. PostgreSQL bibliography/provenance registrations.
2. The content-addressed object expected in S3-compatible storage.

`plan_source_reconciliation()` classifies each currently published official document as:

- already registered and stored;
- missing registration;
- registered but missing its storage object.

`reconcile_source()` downloads only the latter two classes, lets the canonical acquisition path
calculate SHA-256 and write the object, registers the artifact in PostgreSQL, and then reruns the
completeness verifier.

A source is not certified complete merely because reconciliation finished. Certification still
requires an inventory whose enumeration contract is itself known to be exhaustive. This is true
for the current Tribunal Constitucional all-sentences inventory. The Suprema Corte de Justicia
must remain uncertifiable until its full query/pagination contract has been established.

## CI strategy

Normal CI must be deterministic and must not depend on court uptime, changing HTML, production S3
credentials, or production PostgreSQL credentials. CI therefore exercises the same reconciliation
code with:

- a frozen official-inventory fixture;
- deterministic PDF bytes;
- a memory object store implementing the production `ObjectStore` contract;
- the real migrated PostgreSQL schema and `PostgresOfficialArtifactCatalog`.

The integration test starts with an intentionally incomplete corpus, reconciles it, and requires:

```text
only missing PDF fetched
        -> source-partitioned object stored
        -> PostgreSQL provenance registered
        -> deterministic completeness verifier returns complete
```

Live source/S3 validation is a separate operational workflow. It should reuse the same code but is
not a substitute for deterministic CI and must fail closed on source drift or incomplete source
enumeration.
