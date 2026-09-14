from __future__ import annotations

import json
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from jurisnexo.ingestion.document_discovery import (
    DocumentStructureHypothesis,
    StructureFinding,
)


def _empty_findings() -> list[StructureFinding]:
    return []


class ApprovedStructureContext(BaseModel):
    """Audited structural context for one downstream decision agent.

    This context is operational guidance derived from an APPROVED structure hypothesis. It is not
    primary legal evidence and must never substitute for source pages when extracting legal facts.
    """

    model_config = ConfigDict(extra="forbid")

    work_unit_id: str | None = None
    findings: list[StructureFinding] = Field(default_factory=_empty_findings)
    audit_state: Literal["APPROVED"] = "APPROVED"


class _EvidencePagePayload(TypedDict):
    view_page: int
    printed_page: int | None
    source_reference: str | None


class _FindingPayload(TypedDict):
    finding_id: str
    kind: str
    statement: str
    operational_impact: str
    attributes: dict[str, str]
    downstream_instructions: list[str]
    confidence: float
    evidence_pages: list[_EvidencePagePayload]


def build_approved_structure_context(
    *,
    hypothesis: DocumentStructureHypothesis,
    audit_state: str,
    work_unit_id: str | None,
) -> ApprovedStructureContext:
    """Filter durable findings only after the structure gate is cleanly approved."""

    if audit_state != "APPROVED":
        raise ValueError("downstream structure context requires a clean APPROVED audit")

    known_work_units = {unit.work_unit_id for unit in hypothesis.decision_work_units}
    if work_unit_id is not None and work_unit_id not in known_work_units:
        raise ValueError(f"unknown decision work unit {work_unit_id!r}")

    findings = [
        finding
        for finding in hypothesis.structure_findings
        if finding.material
        and (
            not finding.applies_to_work_unit_ids
            or work_unit_id is not None
            and work_unit_id in finding.applies_to_work_unit_ids
        )
    ]
    return ApprovedStructureContext(
        work_unit_id=work_unit_id,
        findings=findings,
    )


def render_approved_structure_context(context: ApprovedStructureContext) -> str:
    """Render compact operational context without duplicating source-page text."""

    if not context.findings:
        return "No material approved structure findings apply to this decision."

    payload: list[_FindingPayload] = []
    for finding in context.findings:
        evidence_pages: list[_EvidencePagePayload] = [
            {
                "view_page": evidence.view_page,
                "printed_page": evidence.printed_page,
                "source_reference": evidence.source_reference,
            }
            for evidence in finding.evidence_pages
        ]
        payload.append(
            {
                "finding_id": finding.finding_id,
                "kind": finding.kind,
                "statement": finding.statement,
                "operational_impact": finding.operational_impact,
                "attributes": {
                    attribute.key: attribute.value for attribute in finding.attributes
                },
                "downstream_instructions": finding.downstream_instructions,
                "confidence": finding.confidence,
                "evidence_pages": evidence_pages,
            }
        )
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
