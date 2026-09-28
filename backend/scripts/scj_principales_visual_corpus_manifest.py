from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import random
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.gold import assess_reference_text_health
from jurisnexo.normalization.visual_reference_alignment import (
    VisualReferencePolicy,
    assess_visual_reference_alignment,
)

from scj_principales_visual_corpus_benchmark import (
    PREFIX,
    _download,
    _list_pdf_keys,
    _native_text,
    _page_count,
)

PAGE_COUNT = int(os.environ.get("SCJ_VISUAL_PAGE_COUNT", "1"))
SEED = os.environ.get(
    "SCJ_VISUAL_CORPUS_SEED",
    "jurisnexo-principales-visual-v1",
)
MANIFEST = Path(
    os.environ.get(
        "SCJ_VISUAL_CORPUS_MANIFEST",
        "scj-visual-corpus-manifest.json",
    )
)
EVIDENCE_DIR = Path(
    os.environ.get(
        "SCJ_VISUAL_REFERENCE_EVIDENCE_DIR",
        str(MANIFEST.with_suffix("")) + "-evidence",
    )
)
MAX_PAGES_PER_PDF_TO_SCAN = int(
    os.environ.get(
        "SCJ_VISUAL_MAX_PAGES_PER_PDF_TO_SCAN",
        "120",
    )
)
AUDIT_CANDIDATE_LIMIT = int(
    os.environ.get(
        "SCJ_VISUAL_ALIGNMENT_AUDIT_LIMIT",
        str(max(PAGE_COUNT * 2, 30)),
    )
)
TESSERACT_LANGUAGE = os.environ.get(
    "SCJ_VISUAL_TESSERACT_LANGUAGE",
    "spa+eng",
)
REJECTED_EVIDENCE_LIMIT = int(
    os.environ.get(
        "SCJ_VISUAL_REJECTED_EVIDENCE_LIMIT",
        "10",
    )
)

POLICY = VisualReferencePolicy(
    minimum_native_characters=int(
        os.environ.get("SCJ_VISUAL_MIN_NATIVE_CHARS", "800")
    ),
    minimum_ocr_characters=int(
        os.environ.get("SCJ_VISUAL_MIN_OCR_CHARS", "600")
    ),
    minimum_ocr_mean_confidence=float(
        os.environ.get("SCJ_VISUAL_MIN_OCR_CONFIDENCE", "85")
    ),
    maximum_word_error_rate=float(
        os.environ.get("SCJ_VISUAL_MAX_ALIGNMENT_WER", "0.08")
    ),
    maximum_character_error_rate=float(
        os.environ.get("SCJ_VISUAL_MAX_ALIGNMENT_CER", "0.05")
    ),
    minimum_token_content_recall=float(
        os.environ.get("SCJ_VISUAL_MIN_ALIGNMENT_RECALL", "0.985")
    ),
    minimum_token_content_precision=float(
        os.environ.get("SCJ_VISUAL_MIN_ALIGNMENT_PRECISION", "0.985")
    ),
    minimum_token_order_preservation=float(
        os.environ.get("SCJ_VISUAL_MIN_ALIGNMENT_ORDER", "0.97")
    ),
    minimum_legal_critical_recall=float(
        os.environ.get("SCJ_VISUAL_MIN_ALIGNMENT_CRITICAL", "1.0")
    ),
)


def _render_page_png(pdf_bytes: bytes, page_index: int) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[page_index]
        try:
            bitmap = page.render(scale=3.0)
            try:
                image = bitmap.to_pil()
                output = io.BytesIO()
                image.save(output, format="PNG")
                return output.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()


def _parse_tesseract_tsv(tsv_text: str) -> tuple[str, float | None]:
    reader = csv.DictReader(
        io.StringIO(tsv_text),
        delimiter="\t",
    )
    lines: list[str] = []
    current_line: tuple[str, str, str, str] | None = None
    words: list[str] = []
    confidences: list[float] = []

    def flush_line() -> None:
        if words:
            lines.append(" ".join(words))
            words.clear()

    for row in reader:
        if row.get("level") != "5":
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        line_key = (
            row.get("page_num") or "",
            row.get("block_num") or "",
            row.get("par_num") or "",
            row.get("line_num") or "",
        )
        if current_line is not None and line_key != current_line:
            flush_line()
        current_line = line_key
        words.append(text)
        try:
            confidence = float(row.get("conf") or "-1")
        except ValueError:
            confidence = -1.0
        if confidence >= 0:
            confidences.append(confidence)
    flush_line()

    mean_confidence = (
        sum(confidences) / len(confidences)
        if confidences
        else None
    )
    return "\n".join(lines), mean_confidence


def _tesseract_ocr(image: bytes) -> tuple[str, float | None, str]:
    with tempfile.NamedTemporaryFile(suffix=".png") as temporary:
        temporary.write(image)
        temporary.flush()
        command = [
            "tesseract",
            temporary.name,
            "stdout",
            "-l",
            TESSERACT_LANGUAGE,
            "--psm",
            "6",
            "tsv",
        ]
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )
    if result.returncode != 0:
        detail = result.stderr.strip() or "tesseract failed"
        raise RuntimeError(detail)
    text, mean_confidence = _parse_tesseract_tsv(result.stdout)
    return text, mean_confidence, " ".join(command)


def _tesseract_version() -> str:
    result = subprocess.run(
        ["tesseract", "--version"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("tesseract is required to build aligned references")
    first_line = (result.stdout or result.stderr).splitlines()
    return first_line[0] if first_line else "tesseract unknown"


def _candidate_pages(
    store: Any,
    rng: random.Random,
) -> list[tuple[str, int, str]]:
    keys = _list_pdf_keys(store)
    rng.shuffle(keys)
    pools: list[tuple[str, list[tuple[int, str]]]] = []

    for key in keys:
        try:
            source = _download(store, key)
            page_count = _page_count(source)
        except Exception:
            continue
        indexes = list(range(page_count))
        rng.shuffle(indexes)
        pages: list[tuple[int, str]] = []
        for page_index in indexes[: min(page_count, MAX_PAGES_PER_PDF_TO_SCAN)]:
            try:
                native_text = _native_text(source, page_index)
            except Exception:
                continue
            if len(native_text.strip()) < POLICY.minimum_native_characters:
                continue
            if not assess_reference_text_health(native_text).is_reliable:
                continue
            pages.append((page_index, native_text))
        if pages:
            pools.append((key, pages))

    candidates: list[tuple[str, int, str]] = []
    depth = 0
    while len(candidates) < AUDIT_CANDIDATE_LIMIT:
        added = False
        for key, pages in pools:
            if depth >= len(pages):
                continue
            page_index, text = pages[depth]
            candidates.append((key, page_index, text))
            added = True
            if len(candidates) >= AUDIT_CANDIDATE_LIMIT:
                break
        if not added:
            break
        depth += 1
    return candidates


def _write_evidence(
    *,
    sample_id: str,
    image: bytes,
    native_text: str,
    ocr_text: str,
    assessment: dict[str, object],
    accepted: bool,
) -> None:
    category = "accepted" if accepted else "rejected"
    target = EVIDENCE_DIR / category / sample_id
    target.mkdir(parents=True, exist_ok=True)
    (target / "page.png").write_bytes(image)
    (target / "native.txt").write_text(native_text, encoding="utf-8")
    (target / "visual-ocr.txt").write_text(ocr_text, encoding="utf-8")
    (target / "alignment.json").write_text(
        json.dumps(
            assessment,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if PAGE_COUNT < 1:
        raise ValueError("SCJ_VISUAL_PAGE_COUNT must be positive")
    if AUDIT_CANDIDATE_LIMIT < PAGE_COUNT:
        raise ValueError(
            "SCJ_VISUAL_ALIGNMENT_AUDIT_LIMIT must be >= page count"
        )

    tesseract_version = _tesseract_version()
    store = build_s3_object_store()
    rng = random.Random(SEED)
    candidates = _candidate_pages(store, rng)
    if len(candidates) < PAGE_COUNT:
        raise RuntimeError(
            f"only {len(candidates)} candidate pages available for "
            f"{PAGE_COUNT} requested aligned references"
        )

    accepted_samples: list[dict[str, Any]] = []
    audit_records: list[dict[str, Any]] = []
    rejection_reasons: Counter[str] = Counter()
    rejected_evidence_written = 0
    cached_key = ""
    cached_source = b""

    for key, page_index, native_text in candidates:
        if key != cached_key:
            cached_source = _download(store, key)
            cached_key = key

        image = _render_page_png(cached_source, page_index)
        ocr_text, ocr_confidence, command = _tesseract_ocr(image)
        assessment = assess_visual_reference_alignment(
            native_text=native_text,
            ocr_text=ocr_text,
            ocr_mean_confidence=ocr_confidence,
            policy=POLICY,
        )
        sample_id = (
            f"{hashlib.sha256(key.encode()).hexdigest()[:12]}"
            f"-p{page_index + 1}"
        )
        assessment_json = assessment.to_json_dict()
        record = {
            "sample_id": sample_id,
            "object_key": key,
            "page_index": page_index,
            "accepted": assessment.accepted,
            "assessment": assessment_json,
            "image_sha256": hashlib.sha256(image).hexdigest(),
            "native_text_sha256": hashlib.sha256(
                native_text.encode("utf-8")
            ).hexdigest(),
            "visual_ocr_sha256": hashlib.sha256(
                ocr_text.encode("utf-8")
            ).hexdigest(),
        }
        audit_records.append(record)

        if assessment.accepted:
            _write_evidence(
                sample_id=sample_id,
                image=image,
                native_text=native_text,
                ocr_text=ocr_text,
                assessment=assessment_json,
                accepted=True,
            )
            accepted_samples.append(
                {
                    "sample_id": sample_id,
                    "object_key": key,
                    "page_index": page_index,
                    "reference_sha256": hashlib.sha256(
                        native_text.encode("utf-8")
                    ).hexdigest(),
                    "image_sha256": hashlib.sha256(image).hexdigest(),
                    "reference_characters": len(native_text),
                    "reference_status": "aligned_native_visual",
                    "gold_authority": (
                        "native PDF text admitted only after independent "
                        "OCR agreement with rendered visual evidence"
                    ),
                    "alignment": assessment_json,
                    "evidence_path": (
                        f"accepted/{sample_id}"
                    ),
                }
            )
        else:
            rejection_reasons.update(assessment.rejection_reasons)
            if rejected_evidence_written < REJECTED_EVIDENCE_LIMIT:
                _write_evidence(
                    sample_id=sample_id,
                    image=image,
                    native_text=native_text,
                    ocr_text=ocr_text,
                    assessment=assessment_json,
                    accepted=False,
                )
                rejected_evidence_written += 1

        if len(accepted_samples) >= PAGE_COUNT:
            break

    if len(accepted_samples) < PAGE_COUNT:
        raise RuntimeError(
            f"needed {PAGE_COUNT} aligned pages, found "
            f"{len(accepted_samples)} after auditing "
            f"{len(audit_records)} candidates"
        )

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = EVIDENCE_DIR / "alignment-audit.jsonl"
    audit_path.write_text(
        "".join(
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
            for record in audit_records
        ),
        encoding="utf-8",
    )

    audited = len(audit_records)
    accepted = sum(bool(record["accepted"]) for record in audit_records)
    payload = {
        "schema_version": 2,
        "seed": SEED,
        "page_count": PAGE_COUNT,
        "reference_policy": {
            "kind": "dual-channel visual/native admission",
            "native_reference": "PDFium native text",
            "visual_reference": "Tesseract OCR over PDFium PNG render",
            "tesseract_version": tesseract_version,
            "tesseract_language": TESSERACT_LANGUAGE,
            "policy": {
                "minimum_native_characters": POLICY.minimum_native_characters,
                "minimum_ocr_characters": POLICY.minimum_ocr_characters,
                "minimum_ocr_mean_confidence": (
                    POLICY.minimum_ocr_mean_confidence
                ),
                "maximum_word_error_rate": POLICY.maximum_word_error_rate,
                "maximum_character_error_rate": (
                    POLICY.maximum_character_error_rate
                ),
                "minimum_token_content_recall": (
                    POLICY.minimum_token_content_recall
                ),
                "minimum_token_content_precision": (
                    POLICY.minimum_token_content_precision
                ),
                "minimum_token_order_preservation": (
                    POLICY.minimum_token_order_preservation
                ),
                "minimum_legal_critical_recall": (
                    POLICY.minimum_legal_critical_recall
                ),
            },
        },
        "alignment_audit": {
            "candidate_limit": AUDIT_CANDIDATE_LIMIT,
            "audited_candidates": audited,
            "accepted_candidates": accepted,
            "rejected_candidates": audited - accepted,
            "observed_acceptance_rate": (
                accepted / audited if audited else 0.0
            ),
            "rejection_reasons": dict(
                sorted(rejection_reasons.items())
            ),
            "audit_jsonl": str(audit_path),
        },
        "selection": (
            "deterministic pseudo-random candidate pool, round-robin across "
            "PDFs; only dual-channel aligned pages admitted"
        ),
        "samples": accepted_samples[:PAGE_COUNT],
    }

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "manifest_pages": PAGE_COUNT,
                "audited_candidates": audited,
                "accepted_candidates": accepted,
                "observed_acceptance_rate": (
                    accepted / audited if audited else 0.0
                ),
                "tesseract_version": tesseract_version,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
