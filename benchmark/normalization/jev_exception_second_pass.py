"""Auditable second-pass JEV review for first-pass structural exceptions.

Every rejection is retained. Evidence coverage is expanded deterministically from the
same durable SCJ census, so missing first-pass JEV calls do not make an exception
invisible. JEV only reviews a bounded sample; it never promotes a span automatically.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import get_normalization_model_settings, get_openrouter_settings
from jurisnexo.model_providers.openrouter_decisions import OpenRouterDecisionProvider

from jev_structure_pilot import _archive_files, _load_document

STRUCTURE = Path(os.environ.get("JEV_STRUCTURE_OUTPUT", ".artifacts/jev-structure-pilot.json"))
REFINED = Path(os.environ.get("JEV_REFINED_OUTPUT", ".artifacts/jev-refined-candidates.json"))
OUTPUT = Path(os.environ.get("JEV_EXCEPTION_OUTPUT", ".artifacts/jev-exception-second-pass.json"))
MAX_CASES = int(os.environ.get("JEV_EXCEPTION_MAX_CASES", "40"))
BATCH_SIZE = int(os.environ.get("JEV_EXCEPTION_BATCH_SIZE", "6"))
MAX_COST_USD = float(os.environ.get("JEV_EXCEPTION_MAX_COST_USD", "0.03"))
EXCERPT_CHARS = int(os.environ.get("JEV_EXCEPTION_EXCERPT_CHARS", "2600"))


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _first_pass_records(structure: dict[str, Any]) -> dict[tuple[str, int], str]:
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


def _evidence_record(
    *, source: str, page: int, texts: dict[int, str], classifications: dict[int, str]
) -> dict[str, Any] | None:
    page_index = page - 1
    text = texts.get(page_index)
    if text is None:
        return None
    excerpt = text[:EXCERPT_CHARS]
    payload = {
        "source": source,
        "pdf_page": page,
        "fidelity": classifications.get(page_index, "unknown"),
        "excerpt": excerpt,
    }
    return {**payload, "evidence_sha256": _sha(payload)}


def _questions(ids: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    for record_id in ids:
        questions[f"{record_id}__span_verdict"] = {
            "type": "choice",
            "instructions": (
                f'For candidate "{record_id}", decide whether PREVIOUS, START, END and NEXT '
                "support one complete judicial-decision span. Use only visible evidence."
            ),
            "criteria": {
                "supported": "START opens one decision and END closes it; neighbors support the transition.",
                "contradicted": "Visible evidence shows a wrong boundary, editorial heading, or incompatible span.",
                "uncertain": "The supplied excerpts do not contain enough evidence to decide safely.",
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


def _select_diverse(reviewable: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Avoid testing only easy near-threshold failures."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for case in reviewable:
        problems = case["ledger"]["first_pass_problems"]
        key = str(problems[0] if problems else "unclassified")
        buckets.setdefault(key, []).append(case)
    for cases in buckets.values():
        cases.sort(
            key=lambda case: (
                -float(case["ledger"]["first_pass_score"]),
                case["ledger"]["exception_id"],
            )
        )
    selected: list[dict[str, Any]] = []
    while len(selected) < MAX_CASES and any(buckets.values()):
        for key in sorted(buckets):
            if buckets[key] and len(selected) < MAX_CASES:
                selected.append(buckets[key].pop(0))
    return selected


def main() -> int:
    structure = json.loads(STRUCTURE.read_text(encoding="utf-8"))
    refined = json.loads(REFINED.read_text(encoding="utf-8"))
    first_pass = _first_pass_records(structure)
    store = build_s3_object_store()
    document_cache: dict[str, tuple[dict[int, str], dict[int, str]]] = {}
    ledger: list[dict[str, Any]] = []
    reviewable: list[dict[str, Any]] = []

    for number, item in enumerate(refined["rejected_candidates"], start=1):
        source = str(item["object_key"])
        start = int(item["candidate_pdf_start"])
        end_raw = item.get("candidate_pdf_end")
        end = int(end_raw) if end_raw is not None else None
        if source not in document_cache:
            document_cache[source] = _load_document(_archive_files(store, source))
        texts, classifications = document_cache[source]
        pages = {
            "previous": _evidence_record(
                source=source, page=start - 1, texts=texts, classifications=classifications
            ) if start > 1 else None,
            "start": _evidence_record(
                source=source, page=start, texts=texts, classifications=classifications
            ),
            "end": _evidence_record(
                source=source, page=end, texts=texts, classifications=classifications
            ) if end is not None else None,
            "next": _evidence_record(
                source=source, page=end + 1, texts=texts, classifications=classifications
            ) if end is not None else None,
        }
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
            "first_pass_jev_trace_availability": {
                "start": (source, start) in first_pass,
                "end": end is not None and (source, end) in first_pass,
            },
            "expanded_evidence": pages,
            "expanded_evidence_sha256": _sha(pages),
            "second_pass_status": "not_reviewed",
        }
        ledger.append(row)
        if pages["start"] is not None and pages["end"] is not None and end is not None and start <= end:
            reviewable.append({"ledger": row})

    selected = _select_diverse(reviewable)
    settings = get_openrouter_settings()
    models = get_normalization_model_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    provider = OpenRouterDecisionProvider(
        api_key=settings.api_key.get_secret_value(), model=models.jev_model
    )
    telemetry: list[dict[str, Any]] = []
    total_cost = 0.0
    for offset in range(0, len(selected), BATCH_SIZE):
        batch = selected[offset : offset + BATCH_SIZE]
        ids = tuple(case["ledger"]["exception_id"] for case in batch)
        records = []
        for record_id, case in zip(ids, batch, strict=True):
            ledger_row = case["ledger"]
            evidence = ledger_row["expanded_evidence"]
            sections = []
            for role in ("previous", "start", "end", "next"):
                page = evidence.get(role)
                if page is not None:
                    sections.append(
                        f"{role.upper()} PDF_PAGE={page['pdf_page']} "
                        f"FIDELITY={page['fidelity']}\n{page['excerpt']}"
                    )
            records.append({
                "id": record_id,
                "record": (
                    f"FIRST_PASS_PROBLEMS={','.join(ledger_row['first_pass_problems'])}\n"
                    f"TITLE={ledger_row['title']}\n\n" + "\n\n".join(sections)
                ),
            })
        records_tuple = tuple(records)
        questions = _questions(ids)
        state = (
            "Second-pass audit of SCJ decision-boundary candidates rejected by a first-pass scorer. "
            "The four excerpts come from the durable corpus, not from JEV reconstruction. Do not repair "
            "or invent missing text. Judge only the supplied evidence."
        )
        started = time.perf_counter()
        decision = provider.decide(
            state_description=state, records=records_tuple, questions=questions
        )
        latency = int((time.perf_counter() - started) * 1000)
        total_cost += float(decision.cost_usd or 0.0)
        audit_input = {
            "state_description": state,
            "records": records_tuple,
            "questions": questions,
        }
        audit_output = {"answers": decision.answers}
        telemetry.append({
            "exception_ids": list(ids),
            "model": decision.model,
            "model_version": decision.model_version,
            "response_id": decision.response_id,
            "input_tokens": decision.usage.input_tokens,
            "output_tokens": decision.usage.output_tokens,
            "cost_usd": decision.cost_usd,
            "latency_ms": latency,
            "input_sha256": _sha(audit_input),
            "output_sha256": _sha(audit_output),
            "exact_input": audit_input,
            "exact_output": audit_output,
        })
        for record_id, case in zip(ids, batch, strict=True):
            verdict, verdict_p = _choice(decision.answers[f"{record_id}__span_verdict"])
            failure, failure_p = _choice(decision.answers[f"{record_id}__failure_mode"])
            case["ledger"]["second_pass_status"] = "reviewed"
            case["ledger"]["second_pass"] = {
                "span_verdict": verdict,
                "span_verdict_probability": verdict_p,
                "failure_mode": failure,
                "failure_mode_probability": failure_p,
                "note": "JEV second-pass opinion only; never automatic promotion.",
            }
    if total_cost > MAX_COST_USD:
        raise RuntimeError(f"JEV exception second pass exceeded cost cap: ${total_cost:.6f}")

    counts = {
        "total_rejected": len(ledger),
        "expanded_trace_complete": sum(
            item["expanded_evidence"]["start"] is not None
            and item["expanded_evidence"]["end"] is not None
            for item in ledger
        ),
        "structurally_reviewable": len(reviewable),
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
        "schema_version": 2,
        "purpose": "complete exception ledger, deterministic evidence expansion, auditable JEV second pass",
        "model": models.jev_model,
        "counts": counts,
        "policy": {
            "max_second_pass_cases": MAX_CASES,
            "selection": "round-robin across first-pass failure modes, then highest score",
            "automatic_promotion": False,
            "all_rejections_preserved": True,
            "expanded_evidence_source": "durable SCJ corpus native text plus fidelity classification",
            "neighbor_context": ["previous", "start", "end", "next"],
        },
        "exceptions": ledger,
        "telemetry": telemetry,
        "total_cost_usd": total_cost,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({**counts, "total_cost_usd": total_cost}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
