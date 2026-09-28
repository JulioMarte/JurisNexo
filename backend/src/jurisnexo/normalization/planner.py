from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from jurisnexo.acquisition.manifest import AcquisitionRunManifest

PlanDisposition = Literal["normalize", "reuse", "skip_unavailable"]


@dataclass(frozen=True, slots=True)
class NormalizationPlanItem:
    source_identifier: str
    source_sha256: str | None
    object_key: str | None
    content_type: str | None
    disposition: PlanDisposition
    idempotency_key: str | None


@dataclass(frozen=True, slots=True)
class NormalizationPlan:
    manifest_sha256: str
    pipeline_version: str
    config_sha256: str
    items: tuple[NormalizationPlanItem, ...]

    @property
    def selected_count(self) -> int:
        return sum(item.disposition in {"normalize", "reuse"} for item in self.items)


def normalization_idempotency_key(
    *, source_sha256: str, pipeline_version: str, config_sha256: str
) -> str:
    material = "\n".join((source_sha256, pipeline_version, config_sha256)).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def build_normalization_plan(
    *,
    manifest: AcquisitionRunManifest,
    manifest_sha256: str,
    pipeline_version: str,
    config_sha256: str,
    reusable_keys: frozenset[str] = frozenset(),
) -> NormalizationPlan:
    if len(manifest_sha256) != 64 or len(config_sha256) != 64:
        raise ValueError("manifest_sha256 and config_sha256 must be SHA-256 digests")
    if manifest.status not in {"succeeded", "partial"}:
        raise ValueError("normalization requires a closed acquisition manifest")
    if not pipeline_version.strip():
        raise ValueError("pipeline_version must not be empty")

    items: list[NormalizationPlanItem] = []
    for item in manifest.items:
        if item.status not in {"uploaded", "already_present"}:
            items.append(
                NormalizationPlanItem(
                    source_identifier=item.source_identifier,
                    source_sha256=None,
                    object_key=None,
                    content_type=None,
                    disposition="skip_unavailable",
                    idempotency_key=None,
                )
            )
            continue
        assert item.sha256 is not None
        assert item.object_key is not None
        key = normalization_idempotency_key(
            source_sha256=item.sha256,
            pipeline_version=pipeline_version,
            config_sha256=config_sha256,
        )
        items.append(
            NormalizationPlanItem(
                source_identifier=item.source_identifier,
                source_sha256=item.sha256,
                object_key=item.object_key,
                content_type=item.content_type,
                disposition="reuse" if key in reusable_keys else "normalize",
                idempotency_key=key,
            )
        )

    return NormalizationPlan(
        manifest_sha256=manifest_sha256,
        pipeline_version=pipeline_version,
        config_sha256=config_sha256,
        items=tuple(items),
    )
