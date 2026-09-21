from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from jurisnexo.acquisition.official_corpus import ObjectStore
from jurisnexo.normalization.artifacts import store_derived_artifact
from jurisnexo.normalization.contracts import FormatInspector, StructuralNormalizer
from jurisnexo.normalization.planner import NormalizationPlan
from jurisnexo.normalization.quality import assess_text_quality, extract_text_from_structural_json
from jurisnexo.normalization.recovery import CircuitBreaker, classify_normalization_error


class SourceByteReader(Protocol):
    def read(self, key: str) -> bytes: ...


class NormalizationLedger(Protocol):
    def create_run(
        self,
        *,
        scope_id: str,
        manifest_locator: str,
        manifest_sha256: str,
        pipeline_version: str,
        config_sha256: str,
        selected_count: int,
    ) -> str: ...

    def resolve_source_artifact_id(self, *, scope_id: str, sha256: str) -> str: ...

    def ensure_item(
        self,
        *,
        scope_id: str,
        run_id: str,
        source_artifact_id: str,
        status: str = "pending",
    ) -> str: ...

    def find_reusable_artifact(
        self,
        *,
        scope_id: str,
        source_artifact_id: str,
        pipeline_version: str,
        config_sha256: str,
    ) -> str | None: ...

    def register_derived_artifact(
        self,
        *,
        scope_id: str,
        source_artifact_id: str,
        sha256: str,
        artifact_kind: str,
        mime_type: str,
        byte_size: int,
        storage_locator: str,
        engine: str,
        engine_version: str | None,
        pipeline_version: str,
        config_sha256: str,
        parameters: dict[str, object] | None = None,
    ) -> str: ...

    def register_child_derived_artifact(
        self,
        *,
        scope_id: str,
        parent_artifact_id: str,
        sha256: str,
        artifact_kind: str,
        mime_type: str,
        byte_size: int,
        storage_locator: str,
        engine: str,
        engine_version: str | None,
        pipeline_version: str,
        config_sha256: str,
        derivation_type: str,
        parameters: dict[str, object] | None = None,
    ) -> str: ...

    def record_observation(
        self,
        *,
        scope_id: str,
        run_item_id: str,
        artifact_id: str | None,
        observation_kind: str,
        payload: dict[str, object],
        status: str = "candidate",
        provider: str | None = None,
        model: str | None = None,
        model_version: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: Decimal | None = None,
    ) -> str: ...

    def mark_running(self, *, scope_id: str, item_id: str) -> None: ...

    def mark_normalized(
        self, *, scope_id: str, item_id: str, normalized_artifact_id: str
    ) -> None: ...

    def mark_review_required(
        self, *, scope_id: str, item_id: str, normalized_artifact_id: str
    ) -> None: ...

    def mark_failed(
        self,
        *,
        scope_id: str,
        item_id: str,
        error_code: str,
        error_message: str,
    ) -> None: ...

    def mark_reconciling(self, *, scope_id: str, run_id: str) -> object: ...

    def fail_run(self, *, scope_id: str, run_id: str, reason: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    run_id: str
    normalized: int
    reused: int
    review_required: int
    failed: int


@dataclass(slots=True)
class NormalizationExecutor:
    inspector: FormatInspector
    normalizer: StructuralNormalizer
    source_reader: SourceByteReader
    derived_store: ObjectStore
    ledger: NormalizationLedger
    pipeline_version: str
    config_sha256: str
    circuit_breaker: CircuitBreaker

    def execute(
        self,
        *,
        plan: NormalizationPlan,
        scope_id: str,
        manifest_locator: str,
    ) -> ExecutionResult:
        run_id = self.ledger.create_run(
            scope_id=scope_id,
            manifest_locator=manifest_locator,
            manifest_sha256=plan.manifest_sha256,
            pipeline_version=self.pipeline_version,
            config_sha256=self.config_sha256,
            selected_count=plan.selected_count,
        )
        normalized = 0
        reused = 0
        review_required = 0
        failed = 0

        for planned in plan.items:
            if planned.disposition == "skip_unavailable":
                continue
            self.circuit_breaker.ensure_closed()
            if planned.source_sha256 is None or planned.object_key is None:
                raise ValueError("selected normalization items require source hash and object key")
            source_artifact_id = self.ledger.resolve_source_artifact_id(
                scope_id=scope_id,
                sha256=planned.source_sha256,
            )
            item_id = self.ledger.ensure_item(
                scope_id=scope_id,
                run_id=run_id,
                source_artifact_id=source_artifact_id,
            )

            reusable = self.ledger.find_reusable_artifact(
                scope_id=scope_id,
                source_artifact_id=source_artifact_id,
                pipeline_version=self.pipeline_version,
                config_sha256=self.config_sha256,
            )
            if reusable is not None:
                self.ledger.mark_normalized(
                    scope_id=scope_id,
                    item_id=item_id,
                    normalized_artifact_id=reusable,
                )
                reused += 1
                continue

            self.ledger.mark_running(scope_id=scope_id, item_id=item_id)
            try:
                source = self.source_reader.read(planned.object_key)
                inspection = self.inspector.inspect(
                    source,
                    filename=planned.source_identifier,
                )
                candidate = self.normalizer.normalize(
                    source,
                    inspection,
                    filename=planned.source_identifier,
                )
                stored = store_derived_artifact(
                    object_store=self.derived_store,
                    payload=candidate.payload,
                    content_type=candidate.media_type,
                    artifact_kind="docling-json",
                    pipeline_version=self.pipeline_version,
                    metadata={
                        "engine": candidate.engine,
                        "engine_version": candidate.engine_version or "",
                        "source_sha256": planned.source_sha256,
                    },
                )
                artifact_id = self.ledger.register_derived_artifact(
                    scope_id=scope_id,
                    source_artifact_id=source_artifact_id,
                    sha256=stored.sha256,
                    artifact_kind=stored.artifact_kind,
                    mime_type=stored.content_type,
                    byte_size=stored.byte_count,
                    storage_locator=stored.object_key,
                    engine=candidate.engine,
                    engine_version=candidate.engine_version,
                    pipeline_version=self.pipeline_version,
                    config_sha256=self.config_sha256,
                    parameters={"detected_media_type": inspection.media_type},
                )
                text = extract_text_from_structural_json(candidate.payload)
                quality = assess_text_quality(text)
                self.ledger.record_observation(
                    scope_id=scope_id,
                    run_item_id=item_id,
                    artifact_id=artifact_id,
                    observation_kind="deterministic_qa",
                    payload={
                        "character_count": quality.character_count,
                        "replacement_character_count": quality.replacement_character_count,
                        "empty_line_ratio": quality.empty_line_ratio,
                        "suspicious_fragment_count": quality.suspicious_fragment_count,
                        "legal_critical_span_count": quality.legal_critical_span_count,
                        "risk_flags": list(quality.risk_flags),
                    },
                    status="accepted",
                )
                if quality.requires_review:
                    self.ledger.mark_review_required(
                        scope_id=scope_id,
                        item_id=item_id,
                        normalized_artifact_id=artifact_id,
                    )
                    review_required += 1
                else:
                    resolved_payload = text.encode("utf-8")
                    resolved_stored = store_derived_artifact(
                        object_store=self.derived_store,
                        payload=resolved_payload,
                        content_type="text/plain; charset=utf-8",
                        artifact_kind="resolved-evidence-text",
                        pipeline_version=self.pipeline_version,
                        metadata={
                            "source_sha256": planned.source_sha256,
                            "parent_artifact_id": artifact_id,
                        },
                    )
                    resolved_artifact_id = self.ledger.register_child_derived_artifact(
                        scope_id=scope_id,
                        parent_artifact_id=artifact_id,
                        sha256=resolved_stored.sha256,
                        artifact_kind=resolved_stored.artifact_kind,
                        mime_type=resolved_stored.content_type,
                        byte_size=resolved_stored.byte_count,
                        storage_locator=resolved_stored.object_key,
                        engine="jurisnexo-resolver",
                        engine_version=None,
                        pipeline_version=self.pipeline_version,
                        config_sha256=self.config_sha256,
                        derivation_type="resolve_evidence_text",
                        parameters={"policy": "deterministic-native-structural-text"},
                    )
                    self.ledger.mark_normalized(
                        scope_id=scope_id,
                        item_id=item_id,
                        normalized_artifact_id=resolved_artifact_id,
                    )
                    normalized += 1
                self.circuit_breaker.record_success()
            except Exception as exc:
                failure = classify_normalization_error(exc)
                self.circuit_breaker.record_failure(failure)
                self.ledger.mark_failed(
                    scope_id=scope_id,
                    item_id=item_id,
                    error_code=failure.code,
                    error_message=failure.detail,
                )
                failed += 1
                if failure.failure_class == "systemic" and self.circuit_breaker.open:
                    self.ledger.fail_run(
                        scope_id=scope_id,
                        run_id=run_id,
                        reason=failure.detail,
                    )
                    return ExecutionResult(
                        run_id=run_id,
                        normalized=normalized,
                        reused=reused,
                        review_required=review_required,
                        failed=failed,
                    )

        self.ledger.mark_reconciling(scope_id=scope_id, run_id=run_id)
        return ExecutionResult(
            run_id=run_id,
            normalized=normalized,
            reused=reused,
            review_required=review_required,
            failed=failed,
        )
