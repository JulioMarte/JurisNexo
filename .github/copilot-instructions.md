# GitHub Copilot repository adapter

Use `AGENTS.md` as the repository-wide operational map and source of agent working rules.

For `backend/tests/**`, also apply `backend/tests/AGENTS.md`.

Use `docs/` for durable architecture, product, legal-evidence, security, testing, benchmark, and migration contracts. In particular, test and architecture changes must follow:

- `docs/testing/README.md`
- `docs/testing/repository-governance-contract.md`
- `docs/testing/evidence-authoring-guide.md`
- `docs/testing/current-guarantees.toml`
- `docs/testing/current-proof-map.toml`
- `docs/testing/test-architecture-migration.md` when proof is moved/replaced/retired
- `docs/23-pre-production-evolution-and-adversarial-proof-policy.md` when deliberately superseding a current pre-production architecture/test restriction

This file is an adapter only. It must not become a competing architecture specification.
