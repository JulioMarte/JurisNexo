# corpus

Owns canonical legal truth after required deterministic/audit gates: legal documents, judicial decisions/proceedings, provenance, identity resolution, evidence, canonical legal relations and supported corpus queries.

A source record or S3 object is not automatically a canonical legal document. Model output remains candidate interpretation until the owning commit contract accepts it.

`analysis_observations` is the deliberate quarantine boundary for useful findings that do not yet have a canonical field. Agents may submit JSONB observations through the corpus API, but those rows remain non-canonical until explicit review promotes the concept to a named schema destination.
