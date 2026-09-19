# Legal Reality V4 implementation status

Implementation branch: `hardening/legal-model-v4`.

The branch contains the V4 schema migrations, PostgreSQL legal-model tests, updated canonical documentation, updated guarantee inventory and the private PostgreSQL/VPS operating contract.

The remaining merge gate is empirical: exact-head CI must prove fresh migration, PostgreSQL invariants, architecture fitness, Ruff, Pyright and runtime smoke behavior. Do not treat this status file as evidence that CI passed; GitHub Actions is the authoritative merge gate.
