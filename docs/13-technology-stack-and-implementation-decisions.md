# JurisNexo — Technology Stack and Implementation Decisions

## 1. Purpose

This document freezes the initial implementation stack for the JurisNexo MVP while preserving explicit replacement boundaries for technologies that still require benchmark evidence.

The goal is not to select the most fashionable components. The goal is to create the smallest production-shaped stack that can safely support:

- a shared Dominican legal corpus;
- organization-private research and uploads;
- hybrid legal retrieval;
- long-running research workflows;
- evidence verification and immutable report snapshots;
- repeatable evaluation;
- Docker-based deployment behind Coolify;
- later evolution without rewriting the domain model.

## 2. Governing architectural decision

JurisNexo will begin as a **modular monolith**, not as a distributed microservice system.

The product has multiple runtime processes, but one coherent backend codebase and one primary transactional database.

```text
Browser
   |
   v
Next.js web
   |
   v
FastAPI application API
   |
   +--> PostgreSQL / pgvector
   +--> object storage
   +--> workflow/queue runtime
   +--> model providers
   |
   v
background workers
   |
   +--> ingestion
   +--> retrieval/research
   +--> verification/report generation
```

A runtime boundary is not automatically a service boundary. API, worker, ingestion, retrieval, and research code may run in separate containers while sharing the same versioned Python application package.

## 3. Adopt / Trial / Assess / Hold matrix

### ADOPT — implementation default

| Concern | Selection | Rationale |
|---|---|---|
| frontend | Next.js + TypeScript | mature React application framework, server rendering where useful, strong ecosystem, thin presentation layer |
| frontend styling | Tailwind CSS + shadcn/ui-style component primitives | fast product iteration without tying domain behavior to UI framework abstractions |
| backend API | Python + FastAPI | natural fit for document processing, retrieval, LLM tooling, evaluation and typed HTTP APIs |
| contracts/config | Pydantic + pydantic-settings | typed boundaries for API, jobs, model outputs, configuration and evidence contracts |
| Python packaging | `uv` + `pyproject.toml` | fast reproducible dependency management and lockfile-based CI |
| ORM | SQLAlchemy 2.x | explicit relational persistence with mature async/sync support |
| migrations | Alembic | versioned schema evolution and reproducible database state |
| primary database | PostgreSQL | transactional system of record for corpus metadata, tenants, jobs, evidence and reports |
| vector retrieval | pgvector | keeps the MVP semantic index colocated with the system of record |
| lexical retrieval baseline | PostgreSQL Full Text Search | low-infrastructure lexical baseline; explicitly not treated as true BM25 |
| hybrid fusion baseline | Reciprocal Rank Fusion implemented behind a retrieval contract | transparent, score-scale-independent baseline that can be benchmarked and replaced |
| authentication | Supabase Auth initially | managed authentication with JWT support and convenient integration with PostgreSQL-backed tenancy |
| database hosting | Supabase Postgres initially | reduces infrastructure work while preserving ordinary PostgreSQL semantics |
| object storage | Supabase Storage initially | sufficient for immutable public artifacts, private uploads and report exports during MVP validation |
| testing | pytest + Playwright | backend/domain/integration/security tests plus browser-level product journeys |
| Python lint/format | Ruff | fast canonical lint/format gate |
| Python typing | Pyright strict | catches contract drift and unsafe boundary assumptions early |
| frontend quality | ESLint + TypeScript strict + framework build | static frontend gate and production-build proof |
| CI | GitHub Actions | repository-native pull-request and branch validation |
| observability contract | OpenTelemetry | vendor-neutral traces, metrics and correlation across API/workers |
| application error tracking | Sentry-compatible error reporting | practical application/runtime failure visibility |
| packaging/deployment | Docker + Docker Compose | identical local/CI/deployment runtime contract and direct compatibility with Coolify |
| production orchestrator | Coolify | Git-connected container deployment, proxy/TLS, environment management and Compose lifecycle |

### TRIAL — expected early experiment, not architectural truth

| Concern | Candidate | Decision rule |
|---|---|---|
| reranking | multilingual/legal cross-encoder or managed reranker | adopt the candidate that materially improves legal Recall/NDCG and critical-authority coverage at acceptable cost/latency |
| embeddings | strong multilingual vs legal-specialized embeddings | choose only from JurisNexo's Dominican jurisprudence benchmark |
| durable workflows | Celery/Redis baseline versus Hatchet or Temporal spike | prefer the simpler system unless durable execution materially reduces custom retry/checkpoint/recovery logic |
| document parsing | PyMuPDF + Docling pipeline | retain only if measured page fidelity and extraction quality are sufficient on SCJ/TC PDFs |
| OCR engine | Docling-supported OCR engines and targeted alternatives | use only for pages that require OCR; select by actual Dominican court scans |

### ASSESS — permitted future evolution

- OpenSearch or another dedicated lexical/hybrid engine;
- Qdrant or another dedicated vector engine;
- ColBERT/multi-vector retrieval;
- SPLADE or learned sparse retrieval;
- domain-fine-tuned retrievers/rerankers;
- dedicated graph storage;
- Cloudflare R2 for large public artifact storage;
- Temporal as the durable workflow platform;
- organization-specific private indexes;
- model-routing infrastructure.

These are not MVP dependencies. Each must solve a measured bottleneck.

### HOLD — deliberately excluded from the initial architecture

- Kubernetes;
- Kafka;
- service mesh;
- Neo4j as an MVP requirement;
- Pinecone or another external vector DB by default;
- OpenSearch before PostgreSQL retrieval has a measured deficiency;
- LangChain/LangGraph as the owner of JurisNexo's domain/workflow semantics;
- unrestricted model-generated Python execution;
- independent deployable microservices for each domain module.

## 4. Backend language and framework

Python is the authoritative backend language.

FastAPI owns external HTTP/SSE transport concerns only. Core legal behavior must remain outside FastAPI route handlers.

The intended dependency direction is:

```text
entrypoints/API
      |
      v
application/use cases
      |
      v
domain contracts
      |
      +------> ports/interfaces
                   |
                   v
             infrastructure adapters
```

Domain/research code must be runnable in workers and tests without constructing an HTTP application.

## 5. Frontend boundary

The frontend will use Next.js and TypeScript.

Responsibilities:

- sign-in/session UX;
- organization selection;
- research request form;
- upload flow;
- persisted progress display;
- report/evidence navigation;
- case/source viewing;
- feedback;
- later account/quota screens.

The frontend must not:

- decide tenant authorization;
- access unrestricted database tables;
- infer report citations from prose;
- contain retrieval/research logic;
- become the canonical location for job-state transitions.

The preferred topology is browser -> JurisNexo API. Supabase may provide authentication primitives, but sensitive application data remains behind the backend contract.

## 6. PostgreSQL and schema ownership

PostgreSQL remains the system of record.

Use explicit logical schemas as the implementation matures:

```text
corpus.*
tenant.*
research.*
audit.*
internal.*
```

Examples:

```text
corpus.cases
corpus.source_artifacts
corpus.case_pages
corpus.passages
corpus.case_citations

tenant.organizations
tenant.memberships
tenant.uploads

research.jobs
research.job_events
research.search_runs
research.case_reviews
research.evidence
research.claims
research.reports

audit.events

internal.index_generations
internal.model_runs
internal.provider_usage
```

Public corpus data and tenant-private data must be visibly and permission-wise distinct.

## 7. Supabase is infrastructure, not application architecture

The MVP may use Supabase for managed PostgreSQL, Auth, and Storage.

JurisNexo must remain portable to ordinary PostgreSQL/object storage.

Therefore:

- business logic must not depend on PostgREST-specific behavior;
- migrations are owned by Alembic/repository source control;
- sensitive tables are accessed through backend/worker roles, not directly by the browser;
- ordinary research workers must not receive unrestricted `BYPASSRLS`/service-role authority;
- database roles should distinguish API, workers, ingestion and administration where practical;
- tenant context remains explicit in every private job.

RLS is defense in depth, not a replacement for application authorization.

## 8. Retrieval stack

The retrieval service must expose stable domain-level operations independent of storage implementation.

Initial channels:

1. canonical/legal reference resolver;
2. metadata filters;
3. PostgreSQL lexical full-text retrieval;
4. pgvector dense semantic retrieval;
5. explicit citation traversal.

Initial fusion:

```text
lexical candidates ----+
semantic candidates ---+--> RRF --> optional reranker --> candidate cases/passages
exact references ------+
```

The PostgreSQL lexical baseline must not be described as BM25. If benchmark data shows lexical recall/ranking is a material bottleneck, evaluate true BM25/search-engine alternatives behind the same retrieval interface.

Retrieval configuration is versioned. A completed research report must record the profile/index generation used to produce it.

## 9. Embeddings and reranking

No embedding or reranking model is a permanent architectural dependency at MVP freeze.

Persist at minimum:

- provider;
- model identifier;
- dimensions where relevant;
- generation/index version;
- creation timestamp;
- normalization/chunking profile.

Benchmark:

- strong multilingual embeddings;
- legal-specialized embeddings;
- hybrid retrieval without reranking;
- hybrid retrieval with reranking.

JurisNexo should support case-level and passage-level representations rather than assuming that fixed-size generic chunks are the final retrieval unit.

## 10. Model-provider abstraction

Root research, case analysis, extraction and verification models may differ.

Configuration should distinguish roles such as:

```text
ROOT_RESEARCH_MODEL
CASE_ANALYSIS_MODEL
VERIFICATION_MODEL
EXTRACTION_MODEL
EMBEDDING_MODEL
RERANK_MODEL
```

The implementation should wrap provider SDKs behind narrow adapters and persist provider/model/version metadata with research evidence where material.

Do not permit provider-specific message/object types to leak through the domain model.

## 11. Workflow execution

Long-running work runs outside synchronous HTTP lifetimes.

The first implementation may use Celery + Redis because it is operationally simple and mature. This is a **trial implementation choice**, not a durable workflow commitment.

Before research orchestration becomes deeply coupled to Celery primitives, run a bounded comparison against a durable workflow system such as Temporal or Hatchet.

Decision criteria:

- crash recovery;
- retries/timeouts;
- cancellation;
- fan-out/fan-in case analysis;
- looping from gap assessment back into retrieval;
- workflow observability;
- deployment burden behind Coolify;
- testability;
- migration cost.

Regardless of workflow engine, PostgreSQL remains the product source of truth for user-visible research state, evidence, report versions and audit history.

## 12. Python execution policy

Do not begin with unrestricted arbitrary Python generated by the model.

Prefer bounded deterministic tools first:

```text
aggregate_cases
build_citation_subgraph
compare_authorities
deduplicate_evidence
timeline_cases
calculate_retrieval_metrics
```

Introduce a hardened general Python sandbox only when real research tasks demonstrate that bounded operations are insufficient.

## 13. Document extraction policy

The original source artifact is immutable evidence.

Derived artifacts are versioned and replaceable:

```text
original PDF
   -> extraction result
   -> OCR result where needed
   -> normalized pages
   -> passages/structure
   -> extracted metadata/citations
```

A parser/OCR upgrade creates new derived versions; it never mutates the primary artifact.

Selection of PyMuPDF, Docling and OCR engines is benchmark-driven against representative SCJ/TC documents, with page-boundary preservation treated as a correctness requirement.

## 14. Architecture change rule

A new datastore, search engine, workflow system, agent framework or infrastructure service is admitted only when at least one of these is demonstrated:

- meaningful improvement in Critical Miss Rate or legal retrieval quality;
- material improvement in citation/evidence correctness;
- substantial latency or cost improvement;
- reliability problem not reasonably solved within the current stack;
- security/compliance requirement;
- operational burden lower than the complexity introduced.

Technology adoption without measurable product or operational benefit is architectural regression.

## 15. MVP stack summary

```text
Web
  Next.js + TypeScript

API / domain / research
  Python 3.13+
  FastAPI
  Pydantic
  SQLAlchemy
  Alembic
  uv

Data
  PostgreSQL
  pgvector
  PostgreSQL FTS
  Supabase-managed initially

Auth / objects
  Supabase Auth
  Supabase Storage

Async execution
  Celery + Redis initial trial
  Temporal/Hatchet evaluated before deep coupling

Quality
  Ruff
  Pyright strict
  pytest
  Playwright
  retrieval/evidence benchmark suite

Observability
  OpenTelemetry
  Sentry-compatible application errors

Runtime/deployment
  Docker
  Docker Compose
  Coolify
  GitHub Actions
```

This stack is considered frozen for the first implementation slice except for components explicitly marked TRIAL or ASSESS.