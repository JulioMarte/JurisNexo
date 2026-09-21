from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jurisnexo.model_providers.fake import FakeModelProvider
from jurisnexo.normalization.artifacts import store_derived_artifact
from jurisnexo.normalization.judges import StructuredTextQualityJudge
from jurisnexo.normalization.provider_policy import (
    ProviderPolicy,
    ProviderPolicyDenied,
    enforce_provider_policy,
)
from jurisnexo.normalization.recovery import (
    CircuitBreaker,
    NormalizationFailure,
    classify_normalization_error,
)


@dataclass
class _MemoryObjectStore:
    objects: dict[str, bytes] = field(default_factory=dict)

    def exists(self, key: str) -> bool:
        return key in self.objects

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        del content_type, metadata
        if key in self.objects:
            raise AssertionError("immutable object must not be overwritten")
        self.objects[key] = content


def test_derived_artifact_storage_is_content_addressed_and_idempotent() -> None:
    store = _MemoryObjectStore()
    first = store_derived_artifact(
        object_store=store,
        payload=b"normalized",
        content_type="application/json",
        artifact_kind="docling-json",
        pipeline_version="v1",
    )
    second = store_derived_artifact(
        object_store=store,
        payload=b"normalized",
        content_type="application/json",
        artifact_kind="docling-json",
        pipeline_version="v1",
    )
    assert first.sha256 == second.sha256
    assert not first.already_present
    assert second.already_present
    assert len(store.objects) == 1


def test_provider_policy_fails_closed_for_private_unapproved_egress() -> None:
    policy = ProviderPolicy(provider="openrouter", allow_private_documents=False)
    with pytest.raises(ProviderPolicyDenied):
        enforce_provider_policy(
            policy,
            document_class="judicial_decision",
            is_public=False,
            redacted=False,
        )
    enforce_provider_policy(
        policy,
        document_class="judicial_decision",
        is_public=True,
        redacted=False,
    )


def test_circuit_breaker_only_opens_on_repeated_systemic_failures() -> None:
    breaker = CircuitBreaker(threshold=2)
    breaker.record_failure(
        NormalizationFailure("retryable_infrastructure", "timeout", True, "temporary")
    )
    assert not breaker.open
    breaker.record_failure(NormalizationFailure("systemic", "auth", False, "bad credentials"))
    assert not breaker.open
    breaker.record_failure(NormalizationFailure("systemic", "auth", False, "bad credentials"))
    assert breaker.open
    with pytest.raises(RuntimeError, match="circuit breaker"):
        breaker.ensure_closed()


def test_error_classifier_separates_document_retryable_and_systemic_failures() -> None:
    assert classify_normalization_error(ValueError("unsupported format")).failure_class == (
        "permanent_document"
    )
    assert classify_normalization_error(RuntimeError("HTTP 429 rate limit")).retryable
    assert classify_normalization_error(RuntimeError("invalid credentials")).failure_class == "systemic"


def test_text_quality_judge_uses_provider_contract_without_becoming_ground_truth() -> None:
    provider = FakeModelProvider(
        {
            "pass_text": False,
            "material_error_probability": 0.8,
            "reasons": ["article number uncertain"],
        },
        model="jev-fixture",
    )
    result = StructuredTextQualityJudge(provider).judge(
        "Artículo 1?",
        context={"source": "fixture", "page": 1},
    )
    assert result["pass_text"] is False
    assert result["material_error_probability"] == 0.8
    assert result["provider"] == "fake"
    assert result["model"] == "jev-fixture"
