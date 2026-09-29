"""Second-pass JEV review for first-pass structural exceptions.

This stage never promotes a decision to gold. It takes rejected candidates from the
first deterministic refinement, preserves every rejection in an exception ledger,
and asks JEV a narrower question only when the exact first-pass page records needed
for review are available. Exact second-pass inputs/outputs and hashes are retained.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from jurisnexo.bootstrap.settings import get_normalization_model_settings, get_openrouter_settings
from jurisnexo.model_providers.openrouter_decisions import OpenRouterDecisionProvider

STRUCTURE = Path(os.environ.get("JEV_STRUCTURE_OUTPUT", ".artifacts/jev-structure-pilot.json"))
REFINED = Path(os.environ.get("JEV_REFINED_OUTPUT", ".artifacts/jev-refined-candidates.json"))
OUTPUT = Path(os.environ.get("JEV_EXCEPTION_OUTPUT", ".artifacts/jev-exception-second-pass.json"))
MAX_CASES = int(os.environ.get("JEV_EXCEPTION_MAX_CASES", "30"))
BATCH_SIZE = int(os.environ.get("JEV_EXCEPTION_BATCH_SIZE", "6"))
MAX_COST_USD = float(os.environ.get("JEV_EXCEPTION_MAX_COST_USD", "0.03"))


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _page_records(structure: dict[str, Any]) -> dict[tuple[str, int], str]:
    result: dict[tuple[str, int], str] = {}
    for call in structure.get("telemetry", []):
        for record in ((call.get("audit") or {}).get("input") or {}).get("records") or []:
            body = str(record["record"])
            source = ""
            page: int | None = None
            for line in body.splitlines()[:4]:
                if line.startswith("source="):
                    source = line.removeprefix("source=")
                elif line.startswith("pdf_page="):
                    page = int(line.removeprefix("pdf_page="))
            if source and page is not None:
                result[(source, page)] = body
    return result


def _questions(ids: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    for record_id in ids:
        questions[f"{record_id}__span_verdict"] = {
            "type": "choice",
            "instructions": (
                f'For candidate "{record_id}", decide whether the supplied START and END excerpts '
                "support one complete judicial-decision span. Be conservative and use only visible evidence."
            ),
            "criteria": {
                "supported": "START visibly opens a decision and END visibly closes that same decision.",
                "contradicted": "Visible evidence shows a wrong start, wrong end, editorial heading, or incompatible span.",
                "uncertain": "The excerpts do not contain enough evidence to decide safely.",
            },
        }
        questions[f"{record_id}__failure_mode"] = {
            "type": "choice",
            "instructions": f'Identify the main structural issue for candidate "{record_id}".',
            "criteria": {
                "none": "No visible structural problem; the span is supported.",
                "start": "The proposed start is weak or wrong.",
                "end": "The proposed end is weak or wrong.",
                "both": "Both boundaries are weak or wrong.",
                "editorial": "This is editorial/index structure rather than a decision span.",
                "insufficient": "Not enough visible evidence to classify the failure.",
            },
        }
    return questions


def _choice(answer: dict[str, Any]) -> tuple[str | None, float]:
    probabilities = answer.get("probabilities") or answer.get("choices") or {}
    if not isinstance(probabilities, dict) or not probabilities:
        return None, 0.0
    key = max(probabilities, key=lambda item: float(probabilities[item]))
    return str(key), float(probabilities[key])


def main() -> int:
    structure = json.loads(STRUCTURE.read_text(encoding="utf-8"))
    refined = json.loads(REFINED.read_text(encoding="utf-8"))
    page_records = _page_records(structure)
    ledger: list[dict[str, Any]] = []
    reviewable: list[dict[str, Any]] = []
    for number, item in enumerate(refined["rejected_candidates"], start=1):
        source = str(item["object_key"])
        start = int(item["candidate_pdf_start"])
        end_raw = item.get("candidate_pdf_end")
        end = int(end_raw) if end_raw is not None else None
        start_record = page_records.get((source, start))
        end_record = page_records.get((source, end)) if end is not None else None
        row = {
            "exception_id": f"exception-{number:04d}",
            "document_id": item["document_id"],
            "source_pdf_sha256": item["source_pdf_sha256"],
            "object_key": source,
            "title": item.get("title"),
            "candidate_pdf_start": start,
            "candidate_pdf_end": end,
            "first_pass_score": item["confidence_score"],
            "first_pass_problems": item["problems"],
            "first_pass_positive_evidence": item["positive_evidence"],
            "trace_availability": {
                "start": start_record is not None,
                "end": end_record is not None,
            },
            "second_pass_status": "not_reviewable",
        }
        ledger.append(row)
        if start_record is not None and end_record is not None and start <= end:
            reviewable.append({"ledger": row, "start_record": start_record, "end_record": end_record})

    reviewable.sort(
        key=lambda case: (
            len(case["ledger"]["first_pass_problems"]),
            -float(case["ledger"]["first_pass_score"]),
            case["ledger"]["exception_id"],
        )
    )
    selected = reviewable[:MAX_CASES]
    settings = get_openrouter_settings()
    models = get_normalization_model_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    provider = OpenRouterDecisionProvider(api_key=settings.api_key.get_secret_value(), model=models.jev_model)
    telemetry: list[dict[str, Any]] = []
    total_cost = 0.0
    for offset in range(0, len(selected), BATCH_SIZE):
        batch = selected[offset : offset + BATCH_SIZE]
        ids = tuple(case["ledger"]["exception_id"] for case in batch)
        records = tuple(
            {
                "id": record_id,
                "record": (
                    f"FIRST_PASS_PROBLEMS={','.join(case['ledger']['first_pass_problems'])}\n"
                    f"TITLE={case['ledger']['title']}\n\nSTART EXCERPT\n{case['start_record']}\n\n"
                    f"END EXCERPT\n{case['end_record']}"
                ),
            }
            for record_id, case in zip(ids, batch, strict=True)
        )
        questions = _questions(ids)
        state = (
            "Second-pass audit of SCJ decision-boundary candidates rejected by a first-pass scorer. "
            "Do not repair or invent missing text. Judge only whether the supplied excerpts support the proposed span."
        )
        started = time.perf_counter()
        decision = provider.decide(state_description=state, records=records, questions=questions)
        latency = int((time.perf_counter() - started) * 1000)
        total_cost += float(decision.cost_usd or 0.0)
        audit_input = {"state_description": state, "records": records, "questions": questions}
        audit_output = {"answers": decision.answers}
        telemetry.append({
            "exception_ids": list(ids), "model": decision.model, "model_version": decision.model_version,
            "response_id": decision.response_id, "input_tokens": decision.usage.input_tokens,
            "output_tokens": decision.usage.output_tokens, "cost_usd": decision.cost_usd,
            "latency_ms": latency, "input_sha256": _sha(audit_input), "output_sha256": _sha(audit_output),
            "exact_input": audit_input, "exact_output": audit_output,
        })
        for record_id, case in zip(ids, batch, strict=True):
            verdict, verdict_p = _choice(decision.answers[f"{record_id}__span_verdict"])
            failure, failure_p = _choice(decision.answers[f"{record_id}__failure_mode"])
            case["ledger"]["second_pass_status"] = "reviewed"
            case["ledger"]["second_pass"] = {
                "span_verdict": verdict, "span_verdict_probability": verdict_p,
                "failure_mode": failure, "failure_mode_probability": failure_p,
                "note": "JEV second-pass opinion only; never automatic promotion to gold or accepted corpus.",
            }
    if total_cost > MAX_COST_USD:
        raise RuntimeError(f"JEV exception second pass exceeded cost cap: ${total_cost:.6f}")
    counts = {
        "total_rejected": len(ledger),
        "trace_reviewable": len(reviewable),
        "second_pass_reviewed": len(selected),
        "not_reviewed": len(ledger) - len(selected),
        "second_pass_supported": sum(
            item.get("second_pass", {}).get("span_verdict") == "supported" for item in ledger
        ),
        "second_pass_contradicted": sum(
            item.get("second_pass", {}).get("span_verdict") == "contradicted" for item in ledger
        ),
        "second_pass_uncertain": sum(
            item.get("second_pass", {}).get("span_verdict") == "uncertain" for item in ledger
        ),
    }
    output = {
        "schema_version": 1,
        "purpose": "complete first-pass exception ledger plus narrow auditable JEV second pass",
        "model": models.jev_model,
        "counts": counts,
        "policy": {
            "max_second_pass_cases": MAX_CASES,
            "selection": "fewest first-pass problems, then highest first-pass score",
            "automatic_promotion": False,
            "all_rejections_preserved_even_when_not_reviewable": True,
        },
        "exceptions": ledger,
        "telemetry": telemetry,
        "total_cost_usd": total_cost,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({**counts, "total_cost_usd": total_cost}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
