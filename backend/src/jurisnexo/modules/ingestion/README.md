# ingestion

Owns legal-document processing semantics and the mandatory canonicalization gates:

```text
Structure -> Structure Audit -> Extraction -> Extraction Audit -> Corpus commit
```

It consumes acquired artifacts and produces typed candidate evidence/observations for canonical commit. Acquisition mechanics and research-agent behavior remain separate concerns.
