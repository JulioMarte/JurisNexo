from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pypdfium2 as pdfium

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import get_openrouter_settings
from jurisnexo.normalization.ling_literal_ocr_analysis import (
    CHANGE_EXACT,
    CHANGE_SUBSTANTIVE,
    classify_change,
    detect_anomalies,
    legal_span_disagreements,
)

PLAN_SHA = "63f0ac73fa659a67bca79c20dbf1bde5e18a99f560c0bef6f50de10c51df8cc4"
LING_MODEL = "inclusionai/ling-3.0-flash-vl"
LING_PROVIDER = "NovitaAI"
DECISION_MODEL = "openai/gpt-6-luna-decisions"
PREFIX = "benchmarks/scj-principales/ling-literal-ocr/v1"
PASS_RE = re.compile(r"^pass-(\d+)\.json$")
DIFFICULT_SIZE = 50
CONTROL_SIZE = 50
RENDER_SCALE = 2.0


@dataclass(frozen=True, slots=True)
class Page:
    document_id: str
    page_index: int
    object_key: str
    source_pdf_sha256: str
    first: dict[str, Any]
    second: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Result:
    sample_id: str
    cohort: str
    document_id: str
    page_index: int
    change_class: str
    legal_disagreement_count: int
    anomaly_count: int
    requires_repair_probability: float
    missing_visible_text_probability: float
    reading_order_error_probability: float
    legal_critical_error_probability: float
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    latency_ms: int
    model: str
    provider: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _discover_prefix(store: Any) -> tuple[str, str]:
    successes = [
        obj
        for obj in store.list_objects(PREFIX + "/")
        if obj.key.endswith("/_SUCCESS.json")
    ]
    candidates: list[tuple[float, str, str]] = []
    for obj in successes:
        try:
            payload = json.loads(store.get_bytes(obj.key))
        except Exception:
            continue
        if str(payload.get("requested_model") or "") != LING_MODEL:
            continue
        if str(payload.get("requested_provider") or "") != LING_PROVIDER:
            continue
        plan_sha = str(payload.get("plan_sha256") or "")
        if len(plan_sha) != 64:
            continue
        candidates.append((obj.last_modified, obj.key.rsplit("/", 1)[0], plan_sha))
    if not candidates:
        observed = [obj.key for obj in successes[:20]]
        raise RuntimeError(
            "no completed Ling OCR success marker found in configured object store; "
            f"observed_success_markers={observed}"
        )
    _, base, plan_sha = max(candidates, key=lambda item: item[0])
    return base + "/pages/", plan_sha


def _load_pages(store: Any) -> tuple[list[Page], str]:
    print(json.dumps({"status": "s3_discovery_started", "prefix": PREFIX + "/"}), flush=True)
    prefix, plan_sha = _discover_prefix(store)
    print(
        json.dumps(
            {"status": "s3_evidence_prefix_resolved", "prefix": prefix, "plan_sha256": plan_sha},
            sort_keys=True,
        ),
        flush=True,
    )

    grouped_keys: dict[tuple[str, int], dict[int, str]] = {}
    listed = 0
    matched = 0
    for obj in store.list_objects(prefix):
        listed += 1
        if listed == 1 or listed % 1000 == 0:
            print(
                json.dumps(
                    {
                        "status": "s3_inventory_progress",
                        "objects_listed": listed,
                        "pass_objects_matched": matched,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        if not obj.key.endswith(".json"):
            continue
        rel = obj.key[len(prefix):]
        parts = rel.split("/")
        if len(parts) != 3:
            continue
        match = PASS_RE.match(parts[2])
        if match is None:
            continue
        matched += 1
        grouped_keys.setdefault((parts[0], int(parts[1])), {})[int(match.group(1))] = obj.key

    paired = {
        identity: passes
        for identity, passes in grouped_keys.items()
        if 1 in passes and 2 in passes
    }
    evidence_keys = [key for passes in paired.values() for key in (passes[1], passes[2])]
    print(
        json.dumps(
            {
                "status": "s3_inventory_complete",
                "objects_listed": listed,
                "pass_objects_matched": matched,
                "paired_pages": len(paired),
                "json_objects_to_fetch": len(evidence_keys),
            },
            sort_keys=True,
        ),
        flush=True,
    )

    payloads: dict[str, dict[str, Any]] = {}
    fetch_workers = 16
    with ThreadPoolExecutor(max_workers=fetch_workers, thread_name_prefix="ling-evidence") as executor:
        futures = {executor.submit(store.get_bytes, key): key for key in evidence_keys}
        completed = 0
        for future in as_completed(futures):
            key = futures[future]
            payloads[key] = json.loads(future.result())
            completed += 1
            if completed == 1 or completed % 250 == 0 or completed == len(evidence_keys):
                print(
                    json.dumps(
                        {
                            "status": "s3_fetch_progress",
                            "completed": completed,
                            "total": len(evidence_keys),
                            "percent": round(completed / len(evidence_keys) * 100, 2) if evidence_keys else 100.0,
                            "workers": fetch_workers,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )

    pages: list[Page] = []
    skipped_identity = 0
    for (document_id, page_index), passes in sorted(paired.items()):
        first = payloads[passes[1]]
        second = payloads[passes[2]]
        object_key = str(first.get("object_key") or "")
        source_sha = str(first.get("source_pdf_sha256") or "")
        transcription = str(first.get("transcription") or "")
        if not object_key or len(source_sha) != 64:
            skipped_identity += 1
            continue
        if first.get("plan_sha256") != plan_sha or second.get("plan_sha256") != plan_sha:
            skipped_identity += 1
            continue
        if str(first.get("transcription_sha256") or "") != _sha256(transcription.encode("utf-8")):
            raise RuntimeError(f"corrupt pass-1 evidence for {document_id}/{page_index}")
        pages.append(
            Page(
                document_id=document_id,
                page_index=page_index,
                object_key=object_key,
                source_pdf_sha256=source_sha,
                first=first,
                second=second,
            )
        )

    print(
        json.dumps(
            {"status": "s3_evidence_loaded", "usable_pages": len(pages), "skipped_identity": skipped_identity},
            sort_keys=True,
        ),
        flush=True,
    )
    return pages, plan_sha


def _difficulty(page: Page) -> tuple[int, int, float, int, int]:
    first = str(page.first.get("transcription") or "")
    second = str(page.second.get("transcription") or "")
    legal = legal_span_disagreements(first, second)
    anomalies = detect_anomalies(first)
    change = classify_change(first, second)
    similarity = SequenceMatcher(None, first, second).ratio()
    return (
        1 if legal else 0,
        1 if change == CHANGE_SUBSTANTIVE else 0,
        1.0 - similarity,
        len(anomalies),
        abs(len(first) - len(second)),
    )


def _select(pages: list[Page]) -> list[tuple[str, Page]]:
    difficult = [
        page
        for page in pages
        if classify_change(
            str(page.first.get("transcription") or ""),
            str(page.second.get("transcription") or ""),
        )
        != CHANGE_EXACT
    ]
    difficult.sort(key=_difficulty, reverse=True)
    controls = [
        page
        for page in pages
        if classify_change(
            str(page.first.get("transcription") or ""),
            str(page.second.get("transcription") or ""),
        )
        == CHANGE_EXACT
    ]
    controls.sort(key=lambda page: (page.document_id, page.page_index))
    if len(difficult) < DIFFICULT_SIZE or len(controls) < CONTROL_SIZE:
        raise RuntimeError(
            f"need {DIFFICULT_SIZE} difficult and {CONTROL_SIZE} controls; "
            f"found {len(difficult)} and {len(controls)}"
        )
    step = max(1, len(controls) // CONTROL_SIZE)
    selected_controls = controls[::step][:CONTROL_SIZE]
    if len(selected_controls) < CONTROL_SIZE:
        selected_controls = controls[:CONTROL_SIZE]
    return [("difficult", page) for page in difficult[:DIFFICULT_SIZE]] + [
        ("control", page) for page in selected_controls
    ]


def _render(pdf_bytes: bytes, page_index: int) -> bytes:
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            bitmap = page.render(scale=RENDER_SCALE)
            try:
                image = bitmap.to_pil()
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                return buffer.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()


def _noul(answer: object) -> float:
    if not isinstance(answer, dict):
        raise RuntimeError("decision answer is not an object")
    value = answer.get("noul")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"decision answer missing noul probability: {answer}")
    return float(value)


def _call(
    *,
    api_key: str,
    base_url: str,
    image: bytes,
    ocr: str,
) -> tuple[dict[str, Any], int]:
    encoded = base64.b64encode(image).decode("ascii")
    state = [
        {
            "type": "input_text",
            "text": (
                "Audit the OCR candidate against the judicial page image. "
                "The image is authoritative. Do not reward plausible legal wording "
                "that is not visibly present. OCR candidate follows:\\n\\n" + ocr
            ),
        },
        {
            "type": "input_image",
            "image_url": "data:image/png;base64," + encoded,
            "detail": "high",
        },
    ]
    questions = {
        "requires_repair": {
            "type": "noul",
            "instructions": (
                "Does the OCR candidate contain any material transcription error or "
                "omission that should be repaired before this page is trusted?"
            ),
            "criteria": {
                "true": (
                    "At least one visible word, number, identifier, legal reference, "
                    "or material line is wrong, missing, duplicated, or materially out "
                    "of order."
                ),
                "false": (
                    "The OCR faithfully preserves all material visible text; harmless "
                    "whitespace-only differences do not count."
                ),
            },
        },
        "missing_visible_text": {
            "type": "noul",
            "instructions": (
                "Is there material visible text in the image that is absent from the "
                "OCR candidate?"
            ),
        },
        "reading_order_error": {
            "type": "noul",
            "instructions": (
                "Does the OCR candidate materially violate the visible reading order "
                "of the page?"
            ),
        },
        "legal_critical_error": {
            "type": "noul",
            "instructions": (
                "Does the OCR candidate contain an error in a legally critical token "
                "such as a case identifier, date, year, amount, article, law, "
                "resolution, decree, party name, or dispositive wording?"
            ),
        },
    }
    payload = {
        "model": DECISION_MODEL,
        "state": state,
        "questions": questions,
        "provider": {"order": ["OpenAI"], "allow_fallbacks": False},
    }
    request = Request(
        url=f"{base_url.rstrip('/')}/decisions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "JurisNexo Ling OCR audit benchmark",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=180) as response:
            body = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:4000]
        raise RuntimeError(f"OpenRouter decisions HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"OpenRouter decisions transport error: {exc.reason}") from exc
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if not isinstance(body, dict) or not isinstance(body.get("answers"), dict):
        raise RuntimeError(f"invalid decisions response: {str(body)[:2000]}")
    return body, elapsed_ms


def _call_with_heartbeat(
    *,
    api_key: str,
    base_url: str,
    image: bytes,
    ocr: str,
    index: int,
    total: int,
    cohort: str,
    document_id: str,
    page_index: int,
) -> tuple[dict[str, Any], int]:
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="luna-audit") as executor:
        future = executor.submit(
            _call,
            api_key=api_key,
            base_url=base_url,
            image=image,
            ocr=ocr,
        )
        while True:
            try:
                return future.result(timeout=15)
            except FutureTimeoutError:
                elapsed = int(time.perf_counter() - started)
                print(
                    json.dumps(
                        {
                            "status": "waiting_for_luna",
                            "progress": f"{index}/{total}",
                            "cohort": cohort,
                            "page": f"{document_id}/{page_index}",
                            "elapsed_seconds": elapsed,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )


def _write_checkpoint(output: Path, results: list[Result], total: int) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "records.partial.jsonl").write_text(
        "".join(
            json.dumps(asdict(result), ensure_ascii=False, sort_keys=True) + "\n"
            for result in results
        ),
        encoding="utf-8",
    )
    (output / "progress.json").write_text(
        json.dumps(
            {
                "completed": len(results),
                "total": total,
                "percent": round((len(results) / total) * 100, 2) if total else 0.0,
                "last_sample_id": results[-1].sample_id if results else None,
                "updated_unix": time.time(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _metric(values: list[float]) -> dict[str, float | None]:
    return {
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def run(output: Path) -> int:
    store = build_s3_object_store()
    settings = get_openrouter_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")

    pages, resolved_plan_sha = _load_pages(store)
    selected = _select(pages)
    total = len(selected)
    output.mkdir(parents=True, exist_ok=True)
    pdf_cache: dict[str, bytes] = {}
    results: list[Result] = []

    print(json.dumps({"status": "benchmark_started", "total_pages": total}, sort_keys=True), flush=True)

    for index, (cohort, page) in enumerate(selected, start=1):
        print(
            json.dumps(
                {
                    "status": "page_started",
                    "progress": f"{index}/{total}",
                    "cohort": cohort,
                    "page": f"{page.document_id}/{page.page_index}",
                },
                sort_keys=True,
            ),
            flush=True,
        )
        pdf_bytes = pdf_cache.get(page.object_key)
        if pdf_bytes is None:
            pdf_bytes = store.get_bytes(page.object_key)
            if _sha256(pdf_bytes) != page.source_pdf_sha256:
                raise RuntimeError(f"source PDF drift: {page.object_key}")
            pdf_cache[page.object_key] = pdf_bytes

        image = _render(pdf_bytes, page.page_index)
        first = str(page.first.get("transcription") or "")
        second = str(page.second.get("transcription") or "")
        body, latency_ms = _call_with_heartbeat(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.decisions_base_url,
            image=image,
            ocr=first,
            index=index,
            total=total,
            cohort=cohort,
            document_id=page.document_id,
            page_index=page.page_index,
        )
        answers = body["answers"]
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        result = Result(
            sample_id=f"case-{index:03d}",
            cohort=cohort,
            document_id=page.document_id,
            page_index=page.page_index,
            change_class=classify_change(first, second),
            legal_disagreement_count=len(legal_span_disagreements(first, second)),
            anomaly_count=len(detect_anomalies(first)),
            requires_repair_probability=_noul(answers.get("requires_repair")),
            missing_visible_text_probability=_noul(answers.get("missing_visible_text")),
            reading_order_error_probability=_noul(answers.get("reading_order_error")),
            legal_critical_error_probability=_noul(answers.get("legal_critical_error")),
            input_tokens=(
                usage.get("input_tokens")
                if isinstance(usage.get("input_tokens"), int)
                else None
            ),
            output_tokens=(
                usage.get("output_tokens")
                if isinstance(usage.get("output_tokens"), int)
                else None
            ),
            cost_usd=(
                float(usage["cost"])
                if isinstance(usage.get("cost"), (int, float))
                and not isinstance(usage.get("cost"), bool)
                else None
            ),
            latency_ms=latency_ms,
            model=str(body.get("model") or DECISION_MODEL),
            provider=str(body.get("provider") or ""),
        )
        results.append(result)
        _write_checkpoint(output, results, total)
        print(
            json.dumps(
                {
                    "status": "page_completed",
                    "done": index,
                    "total": total,
                    "percent": round(index / total * 100, 2),
                    "cohort": cohort,
                    "page": f"{page.document_id}/{page.page_index}",
                    "repair_p": result.requires_repair_probability,
                    "legal_p": result.legal_critical_error_probability,
                    "cost": result.cost_usd,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    difficult = [result for result in results if result.cohort == "difficult"]
    controls = [result for result in results if result.cohort == "control"]
    threshold = 0.80
    metrics = {
        "difficult_flag_rate": (
            sum(result.requires_repair_probability >= threshold for result in difficult)
            / len(difficult)
        ),
        "control_false_flag_rate": (
            sum(result.requires_repair_probability >= threshold for result in controls)
            / len(controls)
        ),
        "repair_probability_difficult": _metric(
            [result.requires_repair_probability for result in difficult]
        ),
        "repair_probability_control": _metric(
            [result.requires_repair_probability for result in controls]
        ),
        "legal_error_probability_difficult": _metric(
            [result.legal_critical_error_probability for result in difficult]
        ),
        "legal_error_probability_control": _metric(
            [result.legal_critical_error_probability for result in controls]
        ),
        "missing_text_probability_difficult": _metric(
            [result.missing_visible_text_probability for result in difficult]
        ),
        "missing_text_probability_control": _metric(
            [result.missing_visible_text_probability for result in controls]
        ),
        "reading_order_probability_difficult": _metric(
            [result.reading_order_error_probability for result in difficult]
        ),
        "reading_order_probability_control": _metric(
            [result.reading_order_error_probability for result in controls]
        ),
        "total_cost_usd": sum(result.cost_usd or 0.0 for result in results),
        "mean_latency_ms": statistics.fmean(result.latency_ms for result in results),
        "total_input_tokens": sum(result.input_tokens or 0 for result in results),
        "total_output_tokens": sum(result.output_tokens or 0 for result in results),
    }
    report = {
        "schema_version": 1,
        "benchmark": "ling-pass1-vs-luna-decisions-visual-audit",
        "sample_size": len(results),
        "cohorts": {"difficult": len(difficult), "control": len(controls)},
        "model": DECISION_MODEL,
        "ling_plan_sha256": resolved_plan_sha,
        "threshold": threshold,
        "metrics": metrics,
        "interpretation": {
            "difficult_cohort_is_not_gold": True,
            "note": (
                "Difficult pages are selected from deterministic disagreement signals "
                "between Ling pass 1 and pass 2. This measures Luna's ability to "
                "separate suspicious from stable pages; it does not by itself prove "
                "which transcription is correct."
            ),
        },
        "records": [asdict(result) for result in results],
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    (output / "records.jsonl").write_text(
        "".join(
            json.dumps(asdict(result), ensure_ascii=False, sort_keys=True) + "\\n"
            for result in results
        ),
        encoding="utf-8",
    )
    summary = (
        "# Ling 3.0 Flash-VL vs GPT-6 Luna Decisions visual audit\\n\\n"
        f"- Pages: {len(results)} (50 difficult / 50 control)\\n"
        f"- Threshold: {threshold:.2f}\\n"
        f"- Difficult pages flagged: {metrics['difficult_flag_rate']:.1%}\\n"
        f"- Control false-flag rate: {metrics['control_false_flag_rate']:.1%}\\n"
        f"- Mean repair probability, difficult: "
        f"{metrics['repair_probability_difficult']['mean']:.4f}\\n"
        f"- Mean repair probability, control: "
        f"{metrics['repair_probability_control']['mean']:.4f}\\n"
        f"- Cost: ${metrics['total_cost_usd']:.8f}\\n"
        f"- Mean latency: {metrics['mean_latency_ms']:.1f} ms/page\\n\\n"
        "Important: the difficult cohort is a routing signal, not independent "
        "semantic gold.\\n"
    )
    (output / "summary.md").write_text(summary, encoding="utf-8")
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return run(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
