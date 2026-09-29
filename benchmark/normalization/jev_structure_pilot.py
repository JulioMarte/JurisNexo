"""JEV structural-navigation pilot over the durable SCJ Principales census.

JEV is a probabilistic page-role/boundary classifier, not a generative parser or
source of truth. Deterministic code extracts index references and printed-page
anchors, then triangulates candidate decision spans.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import re
import tarfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.bootstrap.settings import (
    get_normalization_model_settings,
    get_openrouter_settings,
)
from jurisnexo.model_providers.openrouter_decisions import OpenRouterDecisionProvider
from jurisnexo.normalization.jev_structure import (
    build_structure_questions,
    parse_structure_probabilities,
)

PREFIX = "benchmarks/scj-principales/corpus-verification/v1/"
OUTPUT = Path(
    os.environ.get(
        "JEV_STRUCTURE_OUTPUT",
        ".artifacts/jev-structure-pilot.json",
    )
)
DOCUMENTS = int(os.environ.get("JEV_STRUCTURE_DOCUMENTS", "3"))
MAX_CANDIDATE_PAGES = int(
    os.environ.get("JEV_STRUCTURE_MAX_CANDIDATE_PAGES", "40")
)
EXCERPT_CHARS = int(os.environ.get("JEV_STRUCTURE_EXCERPT_CHARS", "2600"))
BATCH_SIZE = int(os.environ.get("JEV_STRUCTURE_BATCH_SIZE", "10"))
MAX_COST_USD = float(os.environ.get("JEV_STRUCTURE_MAX_COST_USD", "0.05"))

_INDEX_HINT = re.compile(
    r"\b(?:índice|indice|sumario|contenido)\b",
    re.IGNORECASE,
)
_INDEX_LINE = re.compile(
    r"^\s*(.{8,}?)\s*(?:\.{2,}|\s{2,})\s*(\d{1,4})\s*$"
)
_STANDALONE_NUMBER = re.compile(r"(?m)^\s*(\d{1,4})\s*$")
_DECISION_HINT = re.compile(
    r"\b(?:sentencia|suprema corte de justicia|recurso de casaci[oó]n|"
    r"dios, patria y libertad)\b",
    re.IGNORECASE,
)


def _get_json(store: Any, key: str) -> dict[str, Any]:
    response = store.client.get_object(
        Bucket=store.config.bucket,
        Key=key,
    )
    return json.loads(response["Body"].read())


def _latest_complete_generation(store: Any) -> str:
    response = store.client.list_objects_v2(
        Bucket=store.config.bucket,
        Prefix=PREFIX,
    )
    successes = [
        item
        for item in response.get("Contents", [])
        if str(item.get("Key", "")).endswith("/_SUCCESS.json")
    ]
    while response.get("IsTruncated"):
        token = response.get("NextContinuationToken")
        if not token:
            raise RuntimeError(
                "truncated census listing omitted continuation token"
            )
        response = store.client.list_objects_v2(
            Bucket=store.config.bucket,
            Prefix=PREFIX,
            ContinuationToken=token,
        )
        successes.extend(
            item
            for item in response.get("Contents", [])
            if str(item.get("Key", "")).endswith("/_SUCCESS.json")
        )
    if not successes:
        raise RuntimeError(
            "no completed SCJ Principales census generation found"
        )
    latest = max(successes, key=lambda item: item["LastModified"])
    return str(latest["Key"]).removesuffix("_SUCCESS.json")


def _archive_files(store: Any, key: str) -> dict[str, bytes]:
    response = store.client.get_object(
        Bucket=store.config.bucket,
        Key=key,
    )
    body = response["Body"].read()
    result: dict[str, bytes] = {}
    with gzip.GzipFile(
        fileobj=io.BytesIO(body),
        mode="rb",
    ) as compressed, tarfile.open(
        fileobj=compressed,
        mode="r:",
    ) as archive:
        for member in archive.getmembers():
            if member.isfile():
                handle = archive.extractfile(member)
                if handle is not None:
                    result[member.name] = handle.read()
    return result


def _load_document(
    files: dict[str, bytes],
) -> tuple[dict[int, str], dict[int, str]]:
    texts: dict[int, str] = {}
    classifications: dict[int, str] = {}
    for name, payload in files.items():
        match = re.fullmatch(
            r"observations/native/page-(\d{5})\.txt",
            name,
        )
        if match:
            texts[int(match.group(1))] = payload.decode(
                "utf-8",
                errors="replace",
            )
    pages = files.get("pages.jsonl")
    if pages is None:
        raise RuntimeError("document archive omitted pages.jsonl")
    for line in pages.decode("utf-8").splitlines():
        item = json.loads(line)
        classifications[int(item["page_index"])] = str(
            item["classification"]
        )
    return texts, classifications


def _index_score(page_index: int, text: str) -> int:
    head_bonus = max(0, 20 - page_index)
    entries = sum(
        bool(_INDEX_LINE.match(line))
        for line in text.splitlines()
    )
    return (
        head_bonus
        + 20 * bool(_INDEX_HINT.search(text))
        + min(entries, 20) * 3
    )


def _candidate_pages(texts: dict[int, str]) -> tuple[int, ...]:
    ranked = sorted(
        texts,
        key=lambda index: (-_index_score(index, texts[index]), index),
    )
    mandatory = set(range(min(15, len(texts))))
    for index, text in texts.items():
        if _DECISION_HINT.search(text):
            mandatory.add(index)
    selected = list(sorted(mandatory))[: MAX_CANDIDATE_PAGES // 2]
    for index in ranked:
        if index not in selected:
            selected.append(index)
        if len(selected) >= MAX_CANDIDATE_PAGES:
            break
    return tuple(sorted(selected))


def _printed_marker(text: str) -> int | None:
    sample = text[:500] + "\n" + text[-500:]
    values = [
        int(match.group(1))
        for match in _STANDALONE_NUMBER.finditer(sample)
    ]
    plausible = [value for value in values if 0 < value < 5000]
    return plausible[-1] if plausible else None


def _index_entries(
    text: str,
    *,
    source_page: int,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = _INDEX_LINE.match(line)
        if match:
            entries.append(
                {
                    "raw": line.strip(),
                    "title": match.group(1).strip(" .\t"),
                    "printed_start_page": int(match.group(2)),
                    "source_index_page": source_page,
                }
            )
    return entries


def _dominant_offset(
    texts: dict[int, str],
) -> tuple[int | None, list[dict[str, int]]]:
    anchors: list[dict[str, int]] = []
    offsets: dict[int, int] = {}
    for page_index, text in texts.items():
        printed = _printed_marker(text)
        if printed is None:
            continue
        pdf_page = page_index + 1
        offset = pdf_page - printed
        anchors.append(
            {
                "pdf_page": pdf_page,
                "printed_page": printed,
                "offset": offset,
            }
        )
        offsets[offset] = offsets.get(offset, 0) + 1
    dominant = max(offsets, key=offsets.__getitem__) if offsets else None
    return dominant, anchors


def _evaluate_pages(
    provider: OpenRouterDecisionProvider,
    *,
    object_key: str,
    page_indices: tuple[int, ...],
    texts: dict[int, str],
    classifications: dict[int, str],
) -> tuple[dict[int, dict[str, float]], list[dict[str, Any]]]:
    results: dict[int, dict[str, float]] = {}
    telemetry: list[dict[str, Any]] = []
    for batch_start in range(0, len(page_indices), BATCH_SIZE):
        batch = page_indices[batch_start : batch_start + BATCH_SIZE]
        ids = tuple(f"p{index:05d}" for index in batch)
        started = time.perf_counter()
        decision = provider.decide(
            state_description=(
                "SCJ Principales PDF page excerpts. Classify observable "
                "editorial/legal structure only. Physical PDF page numbers and "
                "independent text-fidelity labels are supplied as metadata."
            ),
            records=tuple(
                {
                    "id": record_id,
                    "record": (
                        f"source={object_key}\n"
                        f"pdf_page={index + 1}\n"
                        f"fidelity={classifications.get(index, 'unknown')}\n\n"
                        f"{texts.get(index, '')[:EXCERPT_CHARS]}"
                    ),
                }
                for record_id, index in zip(ids, batch, strict=True)
            ),
            questions=build_structure_questions(record_ids=ids),
        )
        latency = int((time.perf_counter() - started) * 1000)
        for record_id, index in zip(ids, batch, strict=True):
            results[index] = asdict(
                parse_structure_probabilities(
                    decision.answers,
                    record_id=record_id,
                )
            )
        telemetry.append(
            {
                "pages": [index + 1 for index in batch],
                "model": decision.model,
                "model_version": decision.model_version,
                "response_id": decision.response_id,
                "input_tokens": decision.usage.input_tokens,
                "output_tokens": decision.usage.output_tokens,
                "total_tokens": decision.usage.total_tokens,
                "cost_usd": decision.cost_usd,
                "latency_ms": latency,
            }
        )
    return results, telemetry


def _inventory_ids(inventory: dict[str, Any]) -> dict[str, str]:
    return {
        str(item["object_key"]): str(item["document_id"])
        for item in inventory["documents"]
    }


def main() -> int:
    if not 1 <= DOCUMENTS <= 5:
        raise ValueError(
            "JEV_STRUCTURE_DOCUMENTS must be between 1 and 5"
        )
    settings = get_openrouter_settings()
    models = get_normalization_model_settings()
    if settings.api_key is None:
        raise RuntimeError("OPENROUTER_API_KEY is required")
    provider = OpenRouterDecisionProvider(
        api_key=settings.api_key.get_secret_value(),
        model=models.jev_model,
    )
    store = build_s3_object_store()
    generation = _latest_complete_generation(store)
    summary = _get_json(store, generation + "census-summary.json")
    inventory = _get_json(store, generation + "inventory.json")
    document_ids = _inventory_ids(inventory)
    ranking = list(summary["document_ranking"])
    chosen = sorted(
        ranking,
        key=lambda item: (
            -float(item["verified_share_of_all_pages"]),
            -int(item["longest_verified_run_pages"]),
        ),
    )[:DOCUMENTS]

    reports: list[dict[str, Any]] = []
    all_telemetry: list[dict[str, Any]] = []
    for document in chosen:
        object_key = str(document["object_key"])
        document_id = document_ids[object_key]
        files = _archive_files(
            store,
            generation + f"documents/{document_id}.tar.gz",
        )
        texts, classifications = _load_document(files)
        first_pass_pages = _candidate_pages(texts)
        first_eval, telemetry = _evaluate_pages(
            provider,
            object_key=object_key,
            page_indices=first_pass_pages,
            texts=texts,
            classifications=classifications,
        )
        all_telemetry.extend(telemetry)
        index_pages = sorted(
            index
            for index, score in first_eval.items()
            if score["index"] >= 0.60
        )
        entries: list[dict[str, Any]] = []
        for index in index_pages:
            entries.extend(
                _index_entries(
                    texts[index],
                    source_page=index + 1,
                )
            )
        dominant_offset, anchors = _dominant_offset(texts)

        mapped: list[dict[str, Any]] = []
        if dominant_offset is not None:
            for entry in entries:
                pdf_start = (
                    int(entry["printed_start_page"])
                    + dominant_offset
                )
                if 1 <= pdf_start <= len(texts):
                    mapped.append(
                        {
                            **entry,
                            "candidate_pdf_start": pdf_start,
                        }
                    )
            mapped.sort(
                key=lambda item: int(item["candidate_pdf_start"])
            )
            for index, item in enumerate(mapped):
                next_start = (
                    int(mapped[index + 1]["candidate_pdf_start"])
                    if index + 1 < len(mapped)
                    else None
                )
                item["candidate_pdf_end"] = (
                    next_start - 1 if next_start else None
                )

        boundary_pages: set[int] = set()
        for item in mapped[:40]:
            start_index = int(item["candidate_pdf_start"]) - 1
            boundary_pages.update(
                index
                for index in range(start_index - 1, start_index + 2)
                if index in texts
            )
            if item["candidate_pdf_end"] is not None:
                end_index = int(item["candidate_pdf_end"]) - 1
                boundary_pages.update(
                    index
                    for index in range(end_index - 1, end_index + 2)
                    if index in texts
                )
        missing = tuple(sorted(boundary_pages - first_eval.keys()))
        boundary_eval: dict[int, dict[str, float]] = {}
        if missing:
            boundary_eval, telemetry = _evaluate_pages(
                provider,
                object_key=object_key,
                page_indices=missing,
                texts=texts,
                classifications=classifications,
            )
            all_telemetry.extend(telemetry)
        combined = {**first_eval, **boundary_eval}
        for item in mapped:
            start = int(item["candidate_pdf_start"]) - 1
            item["start_jev"] = combined.get(start)
            end = item.get("candidate_pdf_end")
            item["end_jev"] = (
                combined.get(int(end) - 1) if end else None
            )
            item["start_fidelity"] = classifications.get(start)
            item["end_fidelity"] = (
                classifications.get(int(end) - 1) if end else None
            )

        reports.append(
            {
                "object_key": object_key,
                "document_id": document_id,
                "source_pdf_sha256": document["source_pdf_sha256"],
                "verified_share": document[
                    "verified_share_of_all_pages"
                ],
                "longest_verified_run_pages": document[
                    "longest_verified_run_pages"
                ],
                "first_pass_pages": [
                    index + 1 for index in first_pass_pages
                ],
                "jev_index_pages": [
                    index + 1 for index in index_pages
                ],
                "printed_page_anchor_count": len(anchors),
                "dominant_pdf_minus_printed_offset": dominant_offset,
                "offset_anchors": anchors,
                "index_entries": entries,
                "decision_candidates": mapped,
                "page_evaluations": {
                    str(index + 1): value
                    for index, value in combined.items()
                },
            }
        )

    total_cost = sum(
        float(item.get("cost_usd") or 0.0)
        for item in all_telemetry
    )
    if total_cost > MAX_COST_USD:
        raise RuntimeError(
            "JEV structure pilot exceeded cost cap: "
            f"${total_cost:.6f}"
        )
    output = {
        "schema_version": 1,
        "census_generation": generation,
        "census_inventory_sha256": summary.get("inventory_sha256"),
        "model": models.jev_model,
        "documents": reports,
        "telemetry": all_telemetry,
        "total_cost_usd": total_cost,
        "interpretation": (
            "JEV outputs are probabilistic structural hypotheses. Index parsing, "
            "printed-page anchors, offsets, and candidate spans are deterministic "
            "evidence; none are semantic gold."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
