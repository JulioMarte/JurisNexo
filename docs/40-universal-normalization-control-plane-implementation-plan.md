# Universal normalization control plane — execution plan

This branch starts from current `development` and implements the accepted V3 plan without inheriting the divergent PR #111 branch wholesale.

## Governing architecture

JurisNexo owns the control plane: immutable source identity, planning, routing, quality/risk policy, provenance, durable execution, resolution, reconciliation, observability and a stable workspace. Commodity parsing/OCR/layout stays behind replaceable engines. The normalization core must remain institution/source agnostic.

## Phased execution

### Phase 0 — substrate reconciliation
- Reconcile the useful persistence/provenance semantics from PR #111 onto the current migration baseline.
- Preserve immutable derived artifacts, acyclic lineage, manifest-scoped normalization runs/items and reproducibility.
- Verify one migration head and exact-head CI.
- Do not copy stale migration numbering blindly.

Exit gate: current development substrate + normalization persistence contract are compatible and tested.

### Phase 1 — measured Docling + Tika spike
- Build an isolated spike: source bytes -> Tika inspection -> Docling conversion -> DoclingDocument JSON.
- Use representative fixtures and representative acquired artifacts.
- Record support, failures, runtime, memory, text fidelity, layout/reading order and output size.
- No JEV/VLM production architecture yet.

Exit gate: evidence-backed compatibility/failure matrix.

### Phase 2 — minimal replaceability boundaries
Introduce only boundaries justified by real substitution/testing:
`FormatInspector`, `StructuralNormalizer`, `OcrBackend`, `TextQualityJudge`, `VisualTextVerifier`, `NormalizedRepresentationResolver`.

Exit gate: source-specific code cannot depend on concrete parser/provider internals.

### Phase 3 — Gold Set + generic contracts
Cover born-digital/scanned/mixed PDF, DOCX, legacy DOC/RTF where supported, HTML/image where supported, corrupt/unsupported inputs, engine failure and legal-critical fidelity. Keep source regressions separate from generic contracts.

### Phase 4 — manifest planner + durable execution
Manifest verification, selection, dry-run, idempotency, durable item checkpoints, resume, retry taxonomy and circuit breaking.

### Phase 5 — production Docling/Tika adapters
Sandbox engines, pin versions/models, persist large derivatives in object storage, persist identity/lineage/run state in PostgreSQL, and emit explicit quality metadata.

### Phase 6 — deterministic QA
Text/layout health, legal-critical risk, page/region routing, explicit quality states and no silent degradation.

### Phase 7 — JEV shadow
Provider-neutral `TextQualityJudge`; persist predictions and benchmark false negatives. No active gate before promotion evidence.

### Phase 8 — visual verification
Rendering/crops, provider/privacy gate, `VisualTextVerifier`, versioned correction assertions and unresolved-review state. VLM is never ground truth.

### Phase 9 — resolved views + sentinel sampling
Evidence-text resolver, search-text view, stable workspace, permanent sentinel sampling and residual-error measurement.

### Phase 10 — reconciliation
Close only after work plan ↔ DB items ↔ derived artifacts ↔ lineage ↔ object storage ↔ quality reports reconcile. Publish immutable normalization manifest.

### Phase 11 — SCJ Principales rollout
Fixtures -> calibration -> holdout -> adversarial sample -> canary -> full Principales -> OOD SCJ sample. Require provenance, resume/idempotency, quality and cost evidence.

### Phase 12 — second-source proof
Onboard a materially different source (prefer TC or legislation) through a source adapter and the same normalization core. No duplicated OCR/retry/JEV/VLM/reconciliation pipeline.

## Non-negotiable design rules
- Acquisition and normalization remain separate.
- Normalize preserved source bytes, never mutable public URLs.
- One physical artifact may contain multiple legal documents.
- Physical/rendered, printed and logical legal-document pagination remain distinct.
- Technical normalization is not legal-semantic extraction.
- Native good text wins over unnecessary OCR.
- Corrections are append/versioned assertions, not destructive rewrites.
- Evidence text and search text are distinct.
- Agents see stable workspace capabilities, not Docling/Tika/OCR/JEV/VLM internals.
- GitHub Actions may orchestrate, but is not the scheduler architecture.
- Begin derivative GC with read-only reachability/orphan audit.
- Universal means proven on a materially different second source, not generic class names.

## Evidence discipline
For each phase, state exactly which evidence exists: fitness/architecture, unit/contract, PostgreSQL/object-storage integration, semantic benchmark, operational canary. Never promote a claim beyond its evidence.

## Immediate next action
Implement Phase 0 first, then Phase 1. Do not build the later abstraction/control machinery until the engine spike provides measured evidence.
