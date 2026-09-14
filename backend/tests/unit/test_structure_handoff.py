from __future__ import annotations

import pytest

from jurisnexo.ingestion.document_discovery import (
    DecisionWorkUnit,
    DocumentStructureHypothesis,
    InvestigationPageEvidence,
    StructureFinding,
    StructureFindingAttribute,
)
from jurisnexo.ingestion.structure_handoff import (
    approved_decision_work_units,
    build_approved_structure_context,
    render_approved_structure_context,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _hypothesis() -> DocumentStructureHypothesis:
    return DocumentStructureHypothesis(
        artifact_class="bulletin",
        family_name_candidate="SCJ bulletin",
        structure_confidence=0.95,
        has_index=True,
        decision_work_units=[
            DecisionWorkUnit(
                work_unit_id="decision-001",
                index_ordinal=1,
                index_label="First decision",
                candidate_start_view_page=6,
                confidence=0.9,
            ),
            DecisionWorkUnit(
                work_unit_id="decision-002",
                index_ordinal=2,
                index_label="Second decision",
                candidate_start_view_page=12,
                confidence=0.9,
            ),
            DecisionWorkUnit(
                work_unit_id="admin-001",
                unit_kind="administrative_section",
                index_ordinal=3,
                index_label="Labor de la Suprema Corte",
                candidate_start_view_page=180,
                confidence=0.95,
            ),
        ],
        structure_findings=[
            StructureFinding(
                finding_id="pagination-offset",
                kind="pagination_transform",
                statement="Printed pagination is offset from the document view.",
                operational_impact="Use printed-page resolution for index destinations.",
                evidence_basis="page",
                evidence_pages=[InvestigationPageEvidence(view_page=6, printed_page=183)],
                attributes=[
                    StructureFindingAttribute(key="view_to_printed_offset", value="177")
                ],
                downstream_instructions=["Do not equate view-page numbers with printed pages."],
                confidence=0.98,
            ),
            StructureFinding(
                finding_id="decision-002-ocr",
                kind="ocr_quality",
                statement="The second decision has degraded OCR near its heading.",
                operational_impact="Inspect the source page carefully before extracting metadata.",
                evidence_basis="page",
                evidence_pages=[InvestigationPageEvidence(view_page=12, printed_page=189)],
                applies_to_work_unit_ids=["decision-002"],
                confidence=0.8,
            ),
            StructureFinding(
                finding_id="non-material-note",
                kind="other",
                statement="Cosmetic scan skew was observed.",
                operational_impact="No downstream action required.",
                evidence_basis="artifact_profile",
                confidence=0.7,
                material=False,
            ),
        ],
        status="candidate",
    )


def test_handoff_requires_clean_structure_approval() -> None:
    with pytest.raises(ValueError, match="clean APPROVED"):
        build_approved_structure_context(
            hypothesis=_hypothesis(),
            audit_state="APPROVED_WITH_AMENDMENTS",
            work_unit_id="decision-001",
        )


def test_handoff_filters_to_global_and_work_unit_specific_material_findings() -> None:
    context = build_approved_structure_context(
        hypothesis=_hypothesis(),
        audit_state="APPROVED",
        work_unit_id="decision-002",
    )

    assert [finding.finding_id for finding in context.findings] == [
        "pagination-offset",
        "decision-002-ocr",
    ]
    rendered = render_approved_structure_context(context)
    assert '"view_to_printed_offset":"177"' in rendered
    assert "Do not equate view-page numbers with printed pages." in rendered


def test_handoff_rejects_unknown_work_unit() -> None:
    with pytest.raises(ValueError, match="unknown decision work unit"):
        build_approved_structure_context(
            hypothesis=_hypothesis(),
            audit_state="APPROVED",
            work_unit_id="does-not-exist",
        )


def test_nondecision_work_unit_cannot_receive_decision_extraction_context() -> None:
    with pytest.raises(ValueError, match="not a judicial decision extraction target"):
        build_approved_structure_context(
            hypothesis=_hypothesis(),
            audit_state="APPROVED",
            work_unit_id="admin-001",
        )


def test_approved_decision_fanout_filters_administrative_sections() -> None:
    units = approved_decision_work_units(
        hypothesis=_hypothesis(),
        audit_state="APPROVED",
    )

    assert [unit.work_unit_id for unit in units] == ["decision-001", "decision-002"]


def test_decision_fanout_requires_clean_approval() -> None:
    with pytest.raises(ValueError, match="clean APPROVED"):
        approved_decision_work_units(
            hypothesis=_hypothesis(),
            audit_state="APPROVED_WITH_AMENDMENTS",
        )
