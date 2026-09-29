"""Build a human-auditable packet for the selected JEV decision boundaries.

The packet contains exact model input excerpts and exact provider outputs for the
pages around each selected boundary. It intentionally makes no semantic verdict:
a third party can inspect the evidence without trusting the refinement scorer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STRUCTURE = Path(os.environ.get("JEV_STRUCTURE_OUTPUT", ".artifacts/jev-structure-pilot.json"))
REFINED = Path(os.environ.get("JEV_REFINED_OUTPUT", ".artifacts/jev-refined-candidates.json"))
OUTPUT = Path(os.environ.get("JEV_AUDIT_OUTPUT", ".artifacts/jev-boundary-audit.json"))


def _trace_pages(structure: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    pages: dict[tuple[str, int], dict[str, Any]] = {}
    for call in structure.get("telemetry", []):
        audit = call.get("audit") or {}
        inputs = audit.get("input") or {}
        records = inputs.get("records") or []
        answers = (audit.get("output") or {}).get("answers") or {}
        for record in records:
            record_id = str(record["id"])
            body = str(record["record"])
            source = ""
            pdf_page: int | None = None
            for line in body.splitlines()[:4]:
                if line.startswith("source="):
                    source = line.removeprefix("source=")
                elif line.startswith("pdf_page="):
                    pdf_page = int(line.removeprefix("pdf_page="))
            if not source or pdf_page is None:
                continue
            prefix = f"{record_id}__"
            pages[(source, pdf_page)] = {
                "record_id": record_id,
                "exact_model_record": body,
                "answers": {
                    key.removeprefix(prefix): value
                    for key, value in answers.items()
                    if key.startswith(prefix)
                },
                "call_response_id": call.get("response_id"),
                "call_input_sha256": audit.get("input_sha256"),
                "call_output_sha256": audit.get("output_sha256"),
                "model": call.get("model"),
                "model_version": call.get("model_version"),
            }
    return pages


def build(structure: dict[str, Any], refined: dict[str, Any]) -> dict[str, Any]:
    trace = _trace_pages(structure)
    cases: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for number, decision in enumerate(refined["selected_pilot_decisions"], start=1):
        source = str(decision["object_key"])
        start = int(decision["candidate_pdf_start"])
        end = int(decision["candidate_pdf_end"])
        review_pages = sorted({page for page in (start - 1, start, end, end + 1) if page > 0})
        evidence: list[dict[str, Any]] = []
        for page in review_pages:
            item = trace.get((source, page))
            if item is None:
                missing.append({"case": number, "source": source, "pdf_page": page})
                evidence.append({"pdf_page": page, "trace_status": "missing"})
            else:
                evidence.append({"pdf_page": page, "trace_status": "present", **item})
        cases.append(
            {
                "case": number,
                "document_id": decision["document_id"],
                "source_pdf_sha256": decision["source_pdf_sha256"],
                "object_key": source,
                "title": decision["title"],
                "index_evidence": {
                    "source_index_page": decision["source_index_page"],
                    "printed_start_page": decision["printed_start_page"],
                },
                "claimed_span": {"pdf_start": start, "pdf_end": end},
                "refinement_score": decision["confidence_score"],
                "refinement_positive_evidence": decision["positive_evidence"],
                "boundary_evidence": evidence,
                "independent_review_questions": [
                    "Does the start page visibly contain a real decision opening?",
                    "Does the page before start belong to a different editorial/legal unit?",
                    "Does the end page visibly contain a real decision ending?",
                    "Does the page after end begin a different editorial/legal unit?",
                    "Does the claimed span agree with the index evidence without relying on JEV?",
                    "Is any model conclusion contradicted by the exact quoted input?",
                ],
                "review_verdict": None,
                "review_notes": None,
            }
        )
    return {
        "schema_version": 1,
        "purpose": "third-party audit of selected decision boundaries",
        "source_structure_schema_version": structure.get("schema_version"),
        "source_refinement_schema_version": refined.get("schema_version"),
        "census_generation": structure.get("census_generation"),
        "model": structure.get("model"),
        "cases": cases,
        "missing_trace_pages": missing,
        "review_contract": {
            "semantic_verdict_is_intentionally_blank": True,
            "reviewer_must_not_use_refinement_score_as_ground_truth": True,
            "exact_model_records_and_provider_answers_are_preserved": True,
            "pass_condition": "all four boundary pages needed for a case are traceable and independently reviewable",
        },
    }


def main() -> int:
    structure = json.loads(STRUCTURE.read_text(encoding="utf-8"))
    refined = json.loads(REFINED.read_text(encoding="utf-8"))
    result = build(structure, refined)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(result["cases"]), "missing_trace_pages": len(result["missing_trace_pages"])}, indent=2))
    if result["missing_trace_pages"]:
        raise RuntimeError("audit packet is incomplete: one or more boundary pages lack exact JEV trace evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
