from __future__ import annotations

"""Large local calibration for SCJ Principales.

This entrypoint deliberately does not change the admission policy. It only
widens candidate discovery so a 600-page audit can actually inspect 600 pages,
then promotes every accepted page into a reusable benchmark manifest.
"""

import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_HELPERS = ROOT / "benchmark" / "normalization"
if str(BENCHMARK_HELPERS) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_HELPERS))

from scj_page_selection import has_native_text, select_reference_pages  # noqa: E402

BASE_PATH = Path(__file__).with_name("scj_principales_visual_benchmark.py")
spec = importlib.util.spec_from_file_location("scj_visual_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {BASE_PATH}")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)

# Keep the source corpus diverse, but allow enough pages per volume to reach
# 600 candidates. The old cap of four pages/document mathematically capped the
# observed pool at 134 pages in the 2026-09-27 calibration run.
MAX_PAGES_PER_DOCUMENT = 32
MAX_PAGES_TO_SCAN = 10_000

_inventory: dict[str, Any] = {}


def _discover_cases(store: Any, *, limit: int) -> list[Any]:
    keys = base._list_pdf_keys(store)
    per_document: list[list[Any]] = []
    total_pdf_pages = 0
    native_text_documents = 0
    eligible_documents = 0
    qualifying_body_pages = 0
    document_stats: list[dict[str, Any]] = []

    import pypdfium2 as pdfium

    for key in keys:
        try:
            pdf_bytes = base._read_pdf(store, key)
            document = pdfium.PdfDocument(pdf_bytes)
            try:
                page_count = len(document)
            finally:
                document.close()
            total_pdf_pages += page_count
        except Exception as exc:
            document_stats.append({"object_key": key, "error": f"{type(exc).__name__}: {exc}"})
            continue

        if not has_native_text(pdf_bytes):
            document_stats.append(
                {"object_key": key, "page_count": page_count, "native_text": False, "selected_candidates": 0}
            )
            continue

        native_text_documents += 1
        selected = select_reference_pages(
            pdf_bytes,
            min_reference_chars=800,
            max_pages_to_scan=MAX_PAGES_TO_SCAN,
            max_pages_per_document=MAX_PAGES_PER_DOCUMENT,
        )
        if selected:
            eligible_documents += 1
            qualifying_body_pages += len(selected)
            per_document.append(
                [
                    base.VisualPageCase(
                        object_key=key,
                        page_index=page.page_index,
                        gold_source="pdf_text_layer",
                    )
                    for page in selected
                ]
            )
        document_stats.append(
            {
                "object_key": key,
                "page_count": page_count,
                "native_text": True,
                "selected_candidates": len(selected),
            }
        )

    # Round-robin across documents. This prevents a few long compilations from
    # dominating the benchmark while still permitting >4 pages per volume.
    cases: list[Any] = []
    for page_rank in range(MAX_PAGES_PER_DOCUMENT):
        for document_cases in per_document:
            if page_rank < len(document_cases):
                cases.append(document_cases[page_rank])
                if len(cases) >= limit:
                    break
        if len(cases) >= limit:
            break

    _inventory.update(
        {
            "pdf_objects": len(keys),
            "total_pdf_pages": total_pdf_pages,
            "native_text_documents": native_text_documents,
            "eligible_documents": eligible_documents,
            "selected_candidate_capacity": qualifying_body_pages,
            "candidate_pages_returned": len(cases),
            "max_pages_per_document": MAX_PAGES_PER_DOCUMENT,
            "max_pages_to_scan": MAX_PAGES_TO_SCAN,
            "documents": document_stats,
        }
    )
    return cases


def _promote_all_accepted() -> None:
    output = base.OUTPUT
    audit_path = output / "alignment-audit.jsonl"
    if not audit_path.exists():
        return

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    accepted = [record for record in records if record.get("accepted")]
    cases: list[dict[str, Any]] = []

    for index, record in enumerate(accepted):
        audit_id = str(record["audit_id"])
        evidence_dir = Path("alignment-evidence") / "accepted" / audit_id
        assessment = record.get("assessment") or {}
        cases.append(
            {
                "sample_id": f"gold-{index:04d}",
                "object_key": str(record["object_key"]),
                "page_index": int(record["page_index"]),
                "gold_source": "aligned_native_visual",
                "reference_reliable": True,
                "reference_authority": "dual_channel_aligned",
                "reference_path": str(evidence_dir / "reference-native.txt"),
                "visual_reference_path": str(evidence_dir / "reference-visual-ocr.txt"),
                "image_path": str(evidence_dir / "input-page.png"),
                "alignment_path": str(evidence_dir / "alignment.json"),
                "alignment": assessment,
                "source_pdf_sha256": record.get("source_pdf_sha256"),
                "reference_sha256": record.get("native_text_sha256"),
                "visual_reference_sha256": record.get("visual_ocr_sha256"),
                "image_sha256": record.get("image_sha256"),
                "visual_ocr_engine": record.get("visual_ocr_engine"),
                "visual_ocr_language": record.get("visual_ocr_language"),
            }
        )

    audited = len(records)
    manifest = {
        "schema_version": 1,
        "benchmark_kind": "scj_principales_visual_gold_pool",
        "purpose": "Every page admitted by independent rendered-page OCR alignment; reusable as benchmark gold.",
        "corpus_inventory": _inventory,
        "admission": {
            "audited_candidates": audited,
            "accepted_candidates": len(accepted),
            "rejected_candidates": audited - len(accepted),
            "observed_acceptance_rate": len(accepted) / audited if audited else 0.0,
            "policy": record_policy(records),
        },
        "cases": cases,
    }
    (output / "gold-benchmark-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "corpus-inventory.json").write_text(
        json.dumps(_inventory, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "gold_benchmark_pages": len(accepted),
                "audited_candidates": audited,
                "total_pdf_pages": _inventory.get("total_pdf_pages", 0),
                "pdf_objects": _inventory.get("pdf_objects", 0),
                "candidate_capacity": _inventory.get("selected_candidate_capacity", 0),
            },
            sort_keys=True,
        ),
        flush=True,
    )


def record_policy(records: list[dict[str, Any]]) -> dict[str, Any]:
    # Policy is already serialized in alignment-summary.json by the base runner.
    summary_path = base.OUTPUT / "alignment-summary.json"
    if summary_path.exists():
        return dict(json.loads(summary_path.read_text(encoding="utf-8")).get("policy") or {})
    return {}


def main() -> int:
    if base.STAGE != "prepare":
        return base.main()
    base._discover_cases = _discover_cases
    status = base._prepare()
    _promote_all_accepted()
    return status


if __name__ == "__main__":
    raise SystemExit(main())
