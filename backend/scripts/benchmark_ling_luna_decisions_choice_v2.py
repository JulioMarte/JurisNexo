from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import statistics
import time
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pypdfium2 as pdfium
from PIL import Image

from benchmark_ling_luna_decisions_audit import DECISION_MODEL, Page, _load_pages, _sha256
from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import get_openrouter_settings

DEFAULT_RESOLUTIONS = (1600, 2200, 3000)
DEFAULT_CASES = 24
DEFAULT_CONCURRENCY = 8
MAX_ATTEMPTS = 4


@dataclass(frozen=True, slots=True)
class Case:
    case_id: str
    document_id: str
    page_index: int
    object_key: str
    source_pdf_sha256: str
    candidate_a: str
    candidate_b: str
    context_a: str
    context_b: str


@dataclass(frozen=True, slots=True)
class Observation:
    observation_id: str
    case_id: str
    document_id: str
    page_index: int
    max_long_side: int
    choice: str
    probability_a: float
    probability_b: float
    probability_neither: float
    confidence: float | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    latency_ms: int
    attempts: int
    model: str
    provider: str


def _candidate_pair(first: str, second: str) -> tuple[str, str, str, str] | None:
    matcher = SequenceMatcher(None, first, second, autojunk=False)
    changes = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    if not changes:
        return None

    def score(op: tuple[str, int, int, int, int]) -> tuple[int, int]:
        _, i1, i2, j1, j2 = op
        a, b = first[i1:i2], second[j1:j2]
        return (1 if any(ch.isdigit() for ch in a + b) else 0, max(len(a), len(b)))

    _, i1, i2, j1, j2 = max(changes, key=score)
    a, b = first[i1:i2].strip(), second[j1:j2].strip()
    if not a or not b or a == b:
        return None
    a, b = a[:240], b[:240]
    radius = 220
    return (
        a,
        b,
        first[max(0, i1 - radius):min(len(first), i2 + radius)],
        second[max(0, j1 - radius):min(len(second), j2 + radius)],
    )


def _build_cases(pages: list[Page], limit: int) -> list[Case]:
    cases: list[Case] = []
    for page in sorted(pages, key=lambda item: (item.document_id, item.page_index)):
        pair = _candidate_pair(
            str(page.first.get("transcription") or ""),
            str(page.second.get("transcription") or ""),
        )
        if pair is None:
            continue
        a, b, context_a, context_b = pair
        identity = _sha256(
            f"{page.source_pdf_sha256}:{page.page_index}:{a}:{b}:choice-v2".encode()
        )[:20]
        cases.append(
            Case(
                case_id=f"diff-{identity}",
                document_id=page.document_id,
                page_index=page.page_index,
                object_key=page.object_key,
                source_pdf_sha256=page.source_pdf_sha256,
                candidate_a=a,
                candidate_b=b,
                context_a=context_a,
                context_b=context_b,
            )
        )
        if len(cases) >= limit:
            break
    if len(cases) < limit:
        raise RuntimeError(f"requested {limit} discrepancy cases; found {len(cases)}")
    return cases


def _encode_jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88, optimize=True)
    return buffer.getvalue()


def _render_ladder(
    pdf_bytes: bytes,
    page_index: int,
    resolutions: tuple[int, ...],
) -> dict[int, bytes]:
    """Render once with PDFium, then derive lower resolutions with Pillow.

    PDFium rendering stays synchronous on one thread. Network inference remains async.
    """
    maximum = max(resolutions)
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page_count = len(document)
        if not 0 <= page_index < page_count:
            raise RuntimeError(
                f"page index {page_index} outside PDF bounds 0..{page_count - 1}"
            )
        page = document[page_index]
        try:
            width, height = page.get_size()
            bitmap = page.render(scale=maximum / max(width, height))
            try:
                source = bitmap.to_pil().convert("RGB")
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()

    images: dict[int, bytes] = {}
    try:
        for resolution in sorted(set(resolutions), reverse=True):
            if max(source.size) == resolution:
                rendered = source.copy()
            else:
                ratio = resolution / max(source.size)
                rendered = source.resize(
                    (
                        max(1, round(source.width * ratio)),
                        max(1, round(source.height * ratio)),
                    ),
                    Image.Resampling.LANCZOS,
                )
            try:
                images[resolution] = _encode_jpeg(rendered)
            finally:
                rendered.close()
    finally:
        source.close()
    return images


def _choice_payload(image: bytes, case: Case) -> dict[str, Any]:
    encoded = base64.b64encode(image).decode("ascii")
    return {
        "model": DECISION_MODEL,
        "state": [
            {
                "type": "input_text",
                "text": (
                    "The judicial page image is authoritative. Two independent OCR passes "
                    "disagree on one bounded span. Select the alternative visibly supported "
                    "by the image. Use neither when neither candidate faithfully matches. "
                    "Nearby OCR context helps locate the span but is not ground truth.\n\n"
                    f"Candidate A: {case.candidate_a}\nCandidate B: {case.candidate_b}\n\n"
                    f"Context A: {case.context_a}\n\nContext B: {case.context_b}"
                ),
            },
            {
                "type": "input_image",
                "image_url": "data:image/jpeg;base64," + encoded,
                "detail": "high",
            },
        ],
        "questions": {
            "ocr_winner": {
                "type": "choice",
                "instructions": "Which candidate most faithfully transcribes the disputed visible span?",
                "criteria": {
                    "a": "Candidate A exactly or materially matches the visible disputed span.",
                    "b": "Candidate B exactly or materially matches the visible disputed span.",
                    "neither": "Neither candidate faithfully matches the visible disputed span.",
                },
            }
        },
        "provider": {"order": ["OpenAI"], "allow_fallbacks": False},
    }


def _sync_post(*, url: str, api_key: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    request = Request(
        url=url,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "JurisNexo Luna Decisions OCR choice benchmark v2",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=180) as response:
            body = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:3000]
        error = RuntimeError(f"HTTP {exc.code}: {detail}")
        setattr(error, "status_code", exc.code)
        setattr(error, "retry_after", exc.headers.get("Retry-After"))
        raise error from exc
    except URLError as exc:
        raise RuntimeError(f"transport error: {exc.reason}") from exc
    return body, int((time.perf_counter() - started) * 1000)


async def _post_with_retry(
    *, url: str, api_key: str, payload: dict[str, Any]
) -> tuple[dict[str, Any], int, int]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            body, latency_ms = await asyncio.to_thread(
                _sync_post, url=url, api_key=api_key, payload=payload
            )
            return body, latency_ms, attempt
        except RuntimeError as exc:
            status = getattr(exc, "status_code", None)
            if status not in {429, 500, 502, 503, 504, None} or attempt == MAX_ATTEMPTS:
                raise
            retry_after = getattr(exc, "retry_after", None)
            try:
                delay = float(retry_after) if retry_after else 2 ** (attempt - 1)
            except ValueError:
                delay = 2 ** (attempt - 1)
            await asyncio.sleep(min(delay, 20.0))
    raise AssertionError("unreachable")


def _parse_choice(body: dict[str, Any]) -> tuple[str, dict[str, float], float | None]:
    answers = body.get("answers")
    if not isinstance(answers, dict):
        raise RuntimeError(f"invalid decisions answers: {str(body)[:1500]}")
    answer = answers.get("ocr_winner")
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise RuntimeError(f"invalid choice answer: {answer}")
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict):
        raise RuntimeError(f"missing choice probabilities: {answer}")
    parsed = {key: float(probabilities.get(key, 0.0)) for key in ("a", "b", "neither")}
    confidence = answer.get("confidence")
    return (
        str(answer.get("choice") or ""),
        parsed,
        float(confidence) if isinstance(confidence, (int, float)) else None,
    )


def _load_completed(path: Path) -> dict[str, Observation]:
    if not path.exists():
        return {}
    completed: dict[str, Observation] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = Observation(**json.loads(line))
            completed[item.observation_id] = item
    return completed


def _append(path: Path, observation: Observation) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(observation), ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


async def _run_async(
    *, cases: list[Case], resolutions: tuple[int, ...], concurrency: int,
    output: Path, store: Any, api_key: str, base_url: str,
) -> list[Observation]:
    records_path = output / "observations.jsonl"
    completed = _load_completed(records_path)
    write_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(concurrency)
    total = len(cases) * len(resolutions)
    finished = len(completed)

    # Prepare all requested visual states before launching network concurrency.
    # This intentionally keeps PDFium single-threaded; each page is rendered only
    # once at the highest requested resolution and lower sizes are Pillow resizes.
    prepared: dict[tuple[str, int], bytes] = {}
    pdf_cache: dict[str, bytes] = {}
    for case_index, case in enumerate(cases, start=1):
        needed = [
            resolution
            for resolution in resolutions
            if f"{case.case_id}-px{resolution}" not in completed
        ]
        if not needed:
            continue
        pdf_bytes = pdf_cache.get(case.object_key)
        if pdf_bytes is None:
            pdf_bytes = await asyncio.to_thread(store.get_bytes, case.object_key)
            if _sha256(pdf_bytes) != case.source_pdf_sha256:
                raise RuntimeError(f"source PDF drift: {case.object_key}")
            pdf_cache[case.object_key] = pdf_bytes
        print(json.dumps({
            "status": "render_started",
            "case": f"{case_index}/{len(cases)}",
            "case_id": case.case_id,
            "resolutions": needed,
        }, sort_keys=True), flush=True)
        try:
            ladder = _render_ladder(pdf_bytes, case.page_index, tuple(needed))
        except Exception as exc:
            failure = {
                "status": "render_failed",
                "case_id": case.case_id,
                "document_id": case.document_id,
                "page_index": case.page_index,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            (output / "render-failures.jsonl").open("a", encoding="utf-8").write(
                json.dumps(failure, ensure_ascii=False, sort_keys=True) + "\n"
            )
            raise
        for resolution, image in ladder.items():
            prepared[(case.case_id, resolution)] = image
        print(json.dumps({
            "status": "render_completed",
            "case_id": case.case_id,
            "prepared": sorted(ladder),
        }, sort_keys=True), flush=True)

    async def one(case: Case, resolution: int) -> None:
        nonlocal finished
        observation_id = f"{case.case_id}-px{resolution}"
        if observation_id in completed:
            return
        image = prepared[(case.case_id, resolution)]
        async with semaphore:
            print(json.dumps({
                "status": "request_started", "observation_id": observation_id,
                "resolution": resolution, "concurrency": concurrency,
            }, sort_keys=True), flush=True)
            body, latency_ms, attempts = await _post_with_retry(
                url=f"{base_url.rstrip('/')}/decisions", api_key=api_key,
                payload=_choice_payload(image, case),
            )
            choice, probabilities, confidence = _parse_choice(body)
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
            observation = Observation(
                observation_id=observation_id, case_id=case.case_id,
                document_id=case.document_id, page_index=case.page_index,
                max_long_side=resolution, choice=choice,
                probability_a=probabilities["a"], probability_b=probabilities["b"],
                probability_neither=probabilities["neither"], confidence=confidence,
                input_tokens=usage.get("input_tokens") if isinstance(usage.get("input_tokens"), int) else None,
                output_tokens=usage.get("output_tokens") if isinstance(usage.get("output_tokens"), int) else None,
                cost_usd=float(usage["cost"]) if isinstance(usage.get("cost"), (int, float)) else None,
                latency_ms=latency_ms, attempts=attempts,
                model=str(body.get("model") or DECISION_MODEL), provider=str(body.get("provider") or ""),
            )
            async with write_lock:
                _append(records_path, observation)
                completed[observation_id] = observation
                finished += 1
                print(json.dumps({
                    "status": "request_completed", "progress": f"{finished}/{total}",
                    "percent": round(finished / total * 100, 2),
                    "observation_id": observation_id, "choice": choice,
                    "confidence": confidence, "input_tokens": observation.input_tokens,
                    "cost_usd": observation.cost_usd, "latency_ms": latency_ms,
                    "attempts": attempts,
                }, sort_keys=True), flush=True)

    await asyncio.gather(*(one(case, resolution) for case in cases for resolution in resolutions))
    return list(completed.values())


def _summarize(
    observations: list[Observation], cases: list[Case],
    resolutions: tuple[int, ...], concurrency: int,
) -> dict[str, Any]:
    by_resolution: dict[str, Any] = {}
    for resolution in resolutions:
        rows = [row for row in observations if row.max_long_side == resolution]
        token_rows = [row.input_tokens for row in rows if row.input_tokens is not None]
        confidence_rows = [row.confidence for row in rows if row.confidence is not None]
        by_resolution[str(resolution)] = {
            "observations": len(rows),
            "mean_input_tokens": statistics.fmean(token_rows) if token_rows else None,
            "mean_latency_ms": statistics.fmean(row.latency_ms for row in rows) if rows else None,
            "total_cost_usd": sum(row.cost_usd or 0.0 for row in rows),
            "mean_confidence": statistics.fmean(confidence_rows) if confidence_rows else None,
            "neither_rate": sum(row.choice == "neither" for row in rows) / len(rows) if rows else None,
        }
    stable = []
    for case in cases:
        choices = [
            row.choice for row in sorted(
                (row for row in observations if row.case_id == case.case_id),
                key=lambda row: row.max_long_side,
            )
        ]
        stable.append(bool(choices) and len(set(choices)) == 1)
    return {
        "schema_version": 2,
        "benchmark": "ling-pass-disagreement-luna-choice-resolution",
        "semantic_gold": False,
        "semantic_gold_note": (
            "Ling Pass 1/Pass 2 generate candidates only. This run measures mechanics, "
            "cost, latency, resolution sensitivity and choice stability, not semantic accuracy."
        ),
        "case_count": len(cases), "observation_count": len(observations),
        "resolutions": list(resolutions), "concurrency": concurrency,
        "by_resolution": by_resolution,
        "stable_case_rate": sum(stable) / len(stable) if stable else None,
        "total_cost_usd": sum(row.cost_usd or 0.0 for row in observations),
        "total_input_tokens": sum(row.input_tokens or 0 for row in observations),
        "cases": [asdict(case) for case in cases],
    }


async def run(args: argparse.Namespace) -> int:
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    store = build_s3_object_store()
    settings = get_openrouter_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    pages, plan_sha = await asyncio.to_thread(_load_pages, store)
    cases = _build_cases(pages, args.cases)
    (output / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "ling_plan_sha256": plan_sha,
        "cases": [asdict(case) for case in cases],
    }, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "v2_started", "cases": len(cases),
        "resolutions": list(args.resolutions), "concurrency": args.concurrency,
        "observations": len(cases) * len(args.resolutions),
    }, sort_keys=True), flush=True)
    observations = await _run_async(
        cases=cases, resolutions=args.resolutions, concurrency=args.concurrency,
        output=output, store=store, api_key=settings.api_key.get_secret_value(),
        base_url=settings.decisions_base_url,
    )
    report = _summarize(observations, cases, args.resolutions, args.concurrency)
    (output / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = (
        "# Luna Decisions OCR choice/resolution benchmark v2\n\n"
        f"- Cases: {len(cases)}\n- Observations: {len(observations)}\n"
        f"- Resolutions: {', '.join(map(str, args.resolutions))} px long side\n"
        f"- Async concurrency: {args.concurrency}\n"
        f"- Total input tokens: {report['total_input_tokens']:,}\n"
        f"- Total cost: ${report['total_cost_usd']:.6f}\n"
        f"- Choice stable across all resolutions: {report['stable_case_rate']:.1%}\n\n"
        "This is mechanical/resolution evidence, not semantic accuracy evidence.\n"
    )
    (output / "summary.md").write_text(summary, encoding="utf-8")
    print(json.dumps({"status": "v2_complete", "by_resolution": report["by_resolution"]}, sort_keys=True), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=int, default=DEFAULT_CASES)
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument(
        "--resolutions", type=lambda value: tuple(int(part) for part in value.split(",")),
        default=DEFAULT_RESOLUTIONS,
    )
    args = parser.parse_args()
    if args.cases < 1:
        parser.error("--cases must be >= 1")
    if not 1 <= args.concurrency <= 64:
        parser.error("--concurrency must be between 1 and 64")
    if not args.resolutions or any(value < 800 or value > 5000 for value in args.resolutions):
        parser.error("--resolutions must be comma-separated values between 800 and 5000")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
