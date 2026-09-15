---
applyTo: "backend/**/*.py"
---

# Python implementation instructions

This is a tool-specific adapter. Canonical authority remains repository `AGENTS.md`, the nearest local `AGENTS.md`, and `docs/`.

When editing Python:

- preserve explicit capability ownership and authority boundaries;
- do not give agent/model code unrestricted database authority;
- do not persist provider/Agents-SDK runtime objects as durable legal/corpus contracts;
- avoid generic `utils`, `helpers`, `common`, `services`, or `managers` buckets used to hide ownership;
- identify affected guarantee IDs and the plausible regression before changing correctness-sensitive behavior;
- use real PostgreSQL/security/benchmark evidence when the claimed guarantee depends on those mechanisms;
- run Ruff, Pyright, the narrow relevant proof, and the owning canonical CI lane before claiming completion.
