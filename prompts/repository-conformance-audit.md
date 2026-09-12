# Prompt — Audit JurisNexo implementation against repository contracts

You are auditing the current JurisNexo repository against its accepted documentation. Your job is **not** to implement fixes yet. Your job is to determine, with evidence, what is actually implemented, what is only documented, what contradicts the docs, and what remains missing.

## Operating rules

1. Read the repository root `AGENTS.md` first and obey it.
2. Read `docs/19-documentation-crosswalk.md` before interpreting older documents.
3. Treat repository documentation as the source of truth for intended architecture, but do **not** assume documented features exist in code.
4. Treat code, migrations, tests, workflows, benchmark artifacts, and runtime configuration as evidence of current implementation.
5. Distinguish clearly between:
   - `IMPLEMENTED_AND_VERIFIED`;
   - `IMPLEMENTED_PARTIALLY`;
   - `DOCUMENTED_NOT_IMPLEMENTED`;
   - `IMPLEMENTED_BUT_CONTRADICTS_DOCS`;
   - `LEGACY_BASELINE_ONLY`;
   - `UNKNOWN / INSUFFICIENT_EVIDENCE`.
6. Do not mark something implemented merely because a class/file name resembles the documented concept.
7. Do not mark a requirement verified unless you can point to concrete code/tests/CI/benchmark evidence.
8. Do not change files during this audit unless explicitly asked in a later task.

## Read first

At minimum inspect:

- `README.md`;
- `CONTRIBUTING.md`;
- `AGENTS.md`;
- `docs/01-system-architecture.md`;
- `docs/02-legal-corpus-and-data-model.md`;
- `docs/03-research-agent-and-report-contract.md`;
- `docs/05-security-privacy-and-trust.md`;
- `docs/06-mvp-roadmap.md`;
- `docs/09-tenancy-authentication-and-access-control.md`;
- `docs/10-job-state-machines-and-reproducibility.md`;
- `docs/11-benchmark-annotation-and-evaluation-protocol.md`;
- `docs/13-agent-runtime-and-multi-agent-orchestration.md`;
- `docs/14-agent-runtime-decision-record.md`;
- `docs/15-ingestion-agent-pipeline.md`;
- `docs/16-corpus-api-agent-contract.md`;
- `docs/17-agent-methodology-and-benchmark-map.md`;
- `docs/18-migration-plan-custom-harness-to-agents-sdk.md`;
- `docs/20-agents-sdk-provider-and-guardrail-compatibility.md`;
- `docs/21-implementation-governance-and-agent-execution.md`.

Then inspect relevant implementation under:

- `backend/src/jurisnexo/**`;
- `backend/migrations/**`;
- `backend/tests/**`;
- `benchmark/**`;
- `.github/workflows/**`;
- `compose.yaml` and runtime/deployment files.

## Audit domains

Audit each area independently.

### A. Agent runtime migration

Verify whether OpenAI Agents SDK is actually installed/used.

Check:

- dependency declaration;
- runtime integration;
- tool registration;
- structured outputs;
- handoffs or agents-as-tools where appropriate;
- guardrail usage;
- tracing integration;
- provider/model abstraction;
- whether old custom runtime remains and why;
- whether migration parity criteria have been met.

Do not treat selecting the SDK in docs as implementation.

### B. Ingestion pipeline

Verify existence and actual orchestration of:

```text
Structure Agent
-> Structure Auditor
-> Extraction Agent
-> Extraction Auditor
-> Corpus API commit
```

Check whether these are explicit durable stages rather than merely conceptual classes.

Verify:

- structure discovery outputs;
- independent audit behavior;
- approved/rejected/more-investigation states;
- full-decision extraction;
- extraction verification;
- canonical commit gating;
- source/page provenance;
- failure and retry semantics.

### C. Evidence/provenance model

Verify whether evidence is typed and unambiguous.

Specifically check whether the implementation distinguishes:

- source/index claim evidence;
- observed destination/content evidence;
- derived interpretation;
- verification state;
- source artifact/version/checksum;
- printed/view/physical page identities where applicable.

Flag any remaining parallel-array or implicit-correspondence contracts that can reproduce the historical scorer ambiguity.

### D. Corpus API

Verify whether agents/workers access corpus capabilities through stable services instead of unrestricted SQL/database internals.

Check:

- document capabilities;
- case capabilities;
- citation capabilities;
- evidence capabilities;
- analysis persistence;
- ingestion commit surface;
- role-scoped writes;
- authorization and tenant checks;
- runtime-independent persisted schemas.

### E. Database and canonical corpus

Verify:

- PostgreSQL system-of-record role;
- source artifact preservation;
- canonical identity;
- page-to-case provenance;
- evidence records;
- citation relationships;
- organization/tenant scoping where required;
- constraints/FKs that enforce invariants;
- migration consistency with current docs.

### F. Research agent

Verify actual implementation of the research lifecycle:

```text
brief/decomposition
-> retrieval
-> candidate review
-> citation expansion
-> adverse-authority search
-> later-treatment checks where applicable
-> evidence aggregation
-> gap assessment
-> claim verification
-> report
```

Check specialist roles such as:

- Case Analyst;
- Citation Tracer;
- Adverse Researcher;
- Auditor / Claim Verifier.

Do not count prompt text as proof that behavior occurs.

### G. Retrieval

Verify the documented baseline:

- exact/legal-reference lookup;
- metadata filters;
- PostgreSQL lexical/full-text search;
- semantic/vector retrieval if enabled;
- RRF/rank fusion if claimed;
- reranker only if adopted;
- citation traversal;
- versioned/configurable retrieval behavior.

Separate implemented baseline from future research ideas.

### H. Jobs, retries, reproducibility

Verify durable states and whether the current ingestion state machine includes Structure/Audit/Extraction/Audit gates.

Check:

- persisted transitions;
- idempotency;
- retries;
- cancellation;
- budget exhaustion;
- provider/runtime versus semantic failure classification;
- execution snapshots;
- model/prompt/tool/runtime versions;
- corpus/index/source versions.

### I. Security and tenancy

Verify deterministic enforcement of:

- organization scope;
- object ownership;
- private/public corpus boundaries;
- upload isolation;
- canonical-write permissions;
- production credential boundaries;
- role/tool permissions.

Do not treat LLM guardrails as substitutes for these controls.

### J. Benchmarks and research methodology

Verify what benchmark levels actually exist today:

1. document mechanics;
2. structure/index/boundary;
3. discrepancy resolution;
4. full-decision extraction;
5. extraction/evidence audit;
6. retrieval;
7. case analysis;
8. end-to-end legal research;
9. market/human usefulness.

For each research influence in `docs/17`, classify it as:

- baseline implemented;
- experiment implemented;
- documented future option;
- not yet justified by benchmark.

Do not penalize JurisNexo for not implementing optional methods that the docs explicitly defer.

### K. CI and repository governance

Verify:

- short-lived branch policy;
- `main` as integration branch;
- PR/CI aggregate gate;
- branch cleanup behavior;
- Ruff;
- Pyright;
- PostgreSQL-backed tests;
- Docker runtime smoke test;
- benchmark scorer smoke tests;
- whether architecture-critical docs/contracts have automated protection or only prose.

## Required output

Produce a report with these sections.

### 1. Executive conclusion

Answer directly:

```text
Does the current repository substantially implement the accepted JurisNexo architecture?
```

Use one of:

- `YES — substantially implemented`;
- `PARTIALLY — core foundation exists but major documented layers remain unimplemented`;
- `NO — implementation materially diverges from the accepted architecture`.

Explain why in plain language.

### 2. Contract-to-code matrix

Provide a table:

| Contract / capability | Status | Evidence | Missing / contradiction | Risk |
|---|---|---|---|---|

Use repository file paths, symbols, migrations, tests, workflow names, and benchmark artifacts as evidence.

### 3. Highest-risk gaps

Rank only real gaps, not cosmetic differences.

Prioritize gaps that could create:

- wrong legal evidence;
- corrupted/ambiguous corpus data;
- tenant/security failure;
- unverifiable reports;
- critical/adverse authority misses;
- non-reproducible benchmarks;
- runtime migration regressions.

### 4. Legacy versus target architecture

Identify current code that is intentionally a migration baseline rather than target architecture.

Do not call baseline code a defect solely because it has not yet been retired.

### 5. Documentation problems discovered

If code exposes ambiguity or contradiction in the docs, list it separately. Do not silently resolve it in favor of code.

### 6. Recommended implementation sequence

Propose the smallest ordered set of workstreams needed to close the gaps. Respect `docs/21-implementation-governance-and-agent-execution.md`.

Do not propose a single giant rewrite.

### 7. Evidence quality

State which findings are:

- directly proven by code/tests;
- inferred from structure;
- unverified because execution was unavailable.

### 8. Validation performed

List every command, test suite, CI run, benchmark, or static inspection actually performed. If you did not run something, say so.

## Final discipline

Be skeptical of both the code and the docs.

The goal is not to make the repository appear compliant. The goal is to expose the exact distance between accepted architecture and reality so the next implementation work is correctly prioritized.
