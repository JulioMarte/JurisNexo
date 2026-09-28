from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.acquisition.manifest import AcquisitionRunItem, AcquisitionRunManifest
from jurisnexo.normalization.planner import build_normalization_plan
from jurisnexo.normalization.quality import assess_text_quality
from jurisnexo.normalization.reconciliation import (
    ReconciliationSnapshot,
    reconcile_normalization,
)
from jurisnexo.normalization.resolver import (
    TextCorrection,
    TextObservation,
    normalize_search_text,
    resolve_evidence_text,
)
from jurisnexo.normalization.workspace import DocumentPage, DocumentWorkspace


def _manifest() -> AcquisitionRunManifest:
    item = AcquisitionRunItem(
        collection="principales",
        source_identifier="case-1",
        discovery_url="https://example.test/index",
        document_url="https://example.test/case-1.pdf",
        status="uploaded",
        sha256="a" * 64,
        byte_count=12,
        object_key="official/case-1.pdf",
        content_type="application/pdf",
        file_extension="pdf",
        verification_method="downloaded_and_hashed",
    )
    return AcquisitionRunManifest(
        schema_version=3,
        ingestion_id="ing-1",
        batch_id="batch-1",
        partition_index=0,
        partition_count=1,
        source="fixture",
        scope="public",
        storage_bucket="fixture",
        started_at="2026-09-21T00:00:00Z",
        completed_at="2026-09-21T00:01:00Z",
        status="succeeded",
        discovered_count=1,
        uploaded_count=1,
        already_present_count=0,
        unavailable_count=0,
        failed_count=0,
        source_inventory_sha256="b" * 64,
        artifact_set_sha256="c" * 64,
        certified_inventory_sha256=None,
        items=(item,),
    )


def test_planner_is_deterministic_and_reuses_equivalent_work() -> None:
    first = build_normalization_plan(
        manifest=_manifest(),
        manifest_sha256="d" * 64,
        pipeline_version="v1",
        config_sha256="e" * 64,
    )
    key = first.items[0].idempotency_key
    assert key is not None
    second = build_normalization_plan(
        manifest=_manifest(),
        manifest_sha256="d" * 64,
        pipeline_version="v1",
        config_sha256="e" * 64,
        reusable_keys=frozenset({key}),
    )
    assert first.items[0].disposition == "normalize"
    assert second.items[0].disposition == "reuse"
    assert first.items[0].idempotency_key == second.items[0].idempotency_key


def test_quality_report_flags_empty_or_corrupt_text_without_one_opaque_score() -> None:
    empty = assess_text_quality("")
    corrupt = assess_text_quality(("texto\ufffd" * 200) + "\nArtículo 12")
    assert empty.requires_review
    assert "empty_text" in empty.risk_flags
    assert "replacement_characters" in corrupt.risk_flags
    assert corrupt.legal_critical_span_count == 1


def test_evidence_correction_is_separate_from_search_normalization() -> None:
    observation = TextObservation("obs-1", "  Artículo   12  ", "ocr", accepted=True)
    correction = TextCorrection("corr-1", "obs-1", "Artículo 12", accepted=True)
    resolved = resolve_evidence_text((observation,), (correction,))
    assert resolved.text == "Artículo 12"
    assert resolved.correction_id == "corr-1"
    assert normalize_search_text("  Artículo   12\nLey 1 ") == "Artículo 12 Ley 1"


def test_reconciliation_refuses_to_close_when_any_authority_disagrees() -> None:
    report = reconcile_normalization(
        ReconciliationSnapshot(
            planned_source_ids=frozenset({"a", "b"}),
            run_item_source_ids=frozenset({"a"}),
            referenced_artifact_ids=frozenset({"x"}),
            lineage_artifact_ids=frozenset(),
            storage_artifact_ids=frozenset({"x"}),
            quality_report_source_ids=frozenset({"a"}),
        )
    )
    assert not report.can_close
    assert report.missing_run_items == ("b",)
    assert report.missing_lineage == ("x",)
    assert report.missing_quality_reports == ("b",)


@dataclass
class _WorkspaceBackend:
    def pages(self) -> tuple[DocumentPage, ...]:
        return (
            DocumentPage(
                page_id="p1",
                physical_index=0,
                printed_label="1",
                evidence=resolve_evidence_text(
                    (TextObservation("o1", "Primera página", "native", accepted=True),)
                ),
            ),
            DocumentPage(
                page_id="p2",
                physical_index=1,
                printed_label="2",
                evidence=resolve_evidence_text(
                    (TextObservation("o2", "Segunda página", "native", accepted=True),)
                ),
            ),
        )

    def structure(self) -> dict[str, object]:
        return {"pages": 2}

    def render_page(self, page_id: str) -> bytes:
        return page_id.encode()


def test_workspace_hides_engine_details_from_consumers() -> None:
    workspace = DocumentWorkspace(_WorkspaceBackend())
    assert workspace.get_document_structure() == {"pages": 2}
    assert workspace.read_page("p1") == "Primera página"
    assert workspace.read_pages(0, 2) == ("Primera página", "Segunda página")
    assert workspace.search_document("segunda") == ("p2",)
    assert workspace.render_page_image("p1") == b"p1"
    assert workspace.get_evidence("p2").observation_id == "o2"
