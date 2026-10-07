from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ocr_spatial_evidence import (
    Region,
    opaque_observation_id,
    region_to_json,
    regions_from_parallel,
)
from PIL import Image


@dataclass(frozen=True, slots=True)
class Prediction:
    observation_id: str
    sample_id: str
    engine: str
    engine_version: str
    engine_config_id: str
    source_pdf_sha256: str
    page_index: int
    image_sha256: str
    text: str
    elapsed_ms: int
    error: str | None
    regions: list[dict[str, Any]]


def _join_lines(lines: list[str]) -> str:
    return "\n".join(line.strip() for line in lines if line and line.strip()).strip()


def _peak_rss_kib() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def _extract_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        for key in ("rec_texts", "texts", "text_lines", "lines", "blocks"):
            candidate = value.get(key)
            if candidate:
                return _extract_strings(candidate)
        for key in ("text", "value", "html"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return [candidate]
        result: list[str] = []
        for child in value.values():
            result.extend(_extract_strings(child))
        return result
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for child in value:
            result.extend(_extract_strings(child))
        return result
    for attr in ("json", "model_dump"):
        candidate = getattr(value, attr, None)
        if candidate is None:
            continue
        try:
            payload = candidate() if callable(candidate) else candidate
        except (AttributeError, TypeError, ValueError):
            continue
        return _extract_strings(payload)
    return []


class Engine:
    def __init__(self, name: str) -> None:
        self.name = name
        self.version = "unknown"
        self._predict: Callable[[Path], tuple[str, list[Region]]]
        if name == "tesseract":
            self._predict = self._init_tesseract()
        elif name == "easyocr":
            self._predict = self._init_easyocr()
        elif name == "paddleocr":
            self._predict = self._init_paddleocr()
        elif name == "rapidocr":
            self._predict = self._init_rapidocr()
        elif name == "doctr":
            self._predict = self._init_doctr()
        elif name == "surya":
            self._predict = self._init_surya()
        else:
            raise ValueError(f"unsupported engine: {name}")

    def _init_tesseract(self) -> Callable[[Path], str]:
        version = subprocess.run(
            ["tesseract", "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()[0]
        self.version = version

        def predict(path: Path) -> tuple[str, list[Region]]:
            args = ["tesseract", str(path), "stdout", "-l", os.environ.get("OCR_BAKEOFF_TESSERACT_LANG", "spa+eng"), "--psm", os.environ.get("OCR_BAKEOFF_TESSERACT_PSM", "6")]
            text = subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()
            tsv = subprocess.run(args + ["tsv"], check=True, capture_output=True, text=True).stdout
            rows = []
            for line in tsv.splitlines()[1:]:
                cols = line.split("\\t", 11)
                if len(cols) != 12 or not cols[11].strip():
                    continue
                try:
                    x,y,w,h,conf = int(cols[6]),int(cols[7]),int(cols[8]),int(cols[9]),float(cols[10])
                except ValueError:
                    continue
                rows.append(Region(cols[11].strip(), ((x,y),(x+w,y),(x+w,y+h),(x,y+h)), conf/100 if conf >= 0 else None))
            return text, rows

        return predict

    def _init_easyocr(self) -> Callable[[Path], str]:
        import easyocr

        self.version = getattr(easyocr, "__version__", "unknown")
        reader = easyocr.Reader(["es", "en"], gpu=False, verbose=False)

        def predict(path: Path) -> str:
            rows = reader.readtext(str(path), detail=1, paragraph=False)
            ordered = sorted(
                rows,
                key=lambda row: (
                    min(point[1] for point in row[0]),
                    min(point[0] for point in row[0]),
                ),
            )
            return _join_lines([str(row[1]) for row in ordered])

        return predict

    def _init_paddleocr(self) -> Callable[[Path], str]:
        import paddleocr
        from paddleocr import PaddleOCR

        self.version = getattr(paddleocr, "__version__", "unknown")
        ocr = PaddleOCR(
            lang="es",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

        def predict(path: Path) -> tuple[str, list[Region]]:
            result = list(ocr.predict(str(path)))
            texts: list[str] = []
            regions: list[Region] = []
            for item in result:
                payload = getattr(item, "json", item)
                if isinstance(payload, str): payload = json.loads(payload)
                if isinstance(payload, dict) and isinstance(payload.get("res"), dict): payload = payload["res"]
                texts.extend(_extract_strings(payload))
                if isinstance(payload, dict):
                    boxes = payload.get("rec_polys")
                    if boxes is None:
                        boxes = payload.get("dt_polys")
                    regions.extend(
                        regions_from_parallel(
                            payload.get("rec_texts"), boxes, payload.get("rec_scores")
                        )
                    )
            return _join_lines(texts), regions

        return predict

    def _init_rapidocr(self) -> Callable[[Path], str]:
        import rapidocr
        from rapidocr import RapidOCR

        self.version = getattr(rapidocr, "__version__", "unknown")
        ocr = RapidOCR()

        def predict(path: Path) -> tuple[str, list[Region]]:
            result = ocr(str(path))
            txts = getattr(result, "txts", None)
            boxes = getattr(result, "boxes", None)
            scores = getattr(result, "scores", None)
            text = (
                _join_lines([str(item) for item in txts])
                if txts is not None and len(txts) > 0
                else _join_lines(_extract_strings(result))
            )
            return text, regions_from_parallel(txts, boxes, scores)

        return predict

    def _init_doctr(self) -> Callable[[Path], str]:
        import doctr
        from doctr.io import DocumentFile
        from doctr.models import ocr_predictor

        self.version = getattr(doctr, "__version__", "unknown")
        predictor = ocr_predictor(pretrained=True)

        def predict(path: Path) -> str:
            document = DocumentFile.from_images([str(path)])
            result = predictor(document)
            exported = result.export()
            lines: list[str] = []
            for page in exported.get("pages", []):
                for block in page.get("blocks", []):
                    for line in block.get("lines", []):
                        words = [
                            str(word.get("value", ""))
                            for word in line.get("words", [])
                            if str(word.get("value", "")).strip()
                        ]
                        if words:
                            lines.append(" ".join(words))
            return _join_lines(lines)

        return predict

    def _init_surya(self) -> Callable[[Path], str]:
        import html
        import re

        import surya
        from surya.inference import SuryaInferenceManager
        from surya.recognition import RecognitionPredictor

        self.version = getattr(surya, "__version__", "unknown")
        manager = SuryaInferenceManager()
        predictor = RecognitionPredictor(manager)

        def predict(path: Path) -> str:
            image = Image.open(path).convert("RGB")
            result = predictor([image])[0]
            lines: list[str] = []
            for block in getattr(result, "blocks", []):
                raw = str(getattr(block, "html", "") or "")
                if not raw.strip():
                    continue
                plain = re.sub(r"<[^>]+>", " ", raw)
                plain = html.unescape(plain)
                plain = re.sub(r"[ \\t]+", " ", plain)
                plain = re.sub(r" *\\n *", "\\n", plain)
                lines.append(plain.strip())
            return _join_lines(lines)

        return predict

    def predict(self, path: Path) -> tuple[str, list[Region]]:
        value = self._predict(path)
        if isinstance(value, tuple):
            return value
        return value, []


def _engine_config(engine_name: str) -> dict[str, Any]:
    if engine_name == "tesseract":
        return {
            "lang": os.environ.get("OCR_BAKEOFF_TESSERACT_LANG", "spa+eng"),
            "psm": os.environ.get("OCR_BAKEOFF_TESSERACT_PSM", "6"),
        }
    if engine_name == "paddleocr":
        return {
            "lang": "es",
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
    if engine_name == "rapidocr":
        return {"defaults": True}
    return {"defaults": True}


def _stable_json_sha256(payload: dict[str, Any]) -> str:
    import hashlib

    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _observation_identity(
    engine_name: str,
    engine_version: str,
    engine_config_id: str,
    case: dict[str, Any],
) -> str:
    digest = _stable_json_sha256(
        {
            "engine": engine_name,
            "engine_version": engine_version,
            "engine_config_id": engine_config_id,
            "source_pdf_sha256": str(case["source_pdf_sha256"]),
            "page_index": int(case["page_index"]),
            "image_sha256": str(case["image_sha256"]),
        }
    )
    return opaque_observation_id({"digest": digest})


def _manifest_cases(manifest_path: Path, limit: int | None) -> list[dict[str, Any]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("prepared manifest has no cases")
    selected = cases if limit is None else cases[:limit]
    if limit is not None and len(selected) != limit:
        raise RuntimeError(
            f"requested {limit} pages but manifest contains only {len(cases)}"
        )
    benchmark_kind = str(payload.get("benchmark_kind") or "")
    if benchmark_kind == "hard_rescue_ocr_disagreement":
        for row in selected:
            if row.get("reference_reliable") is not False:
                raise RuntimeError("hard/rescue cases must explicitly have no reliable gold")
            if row.get("reference_authority") != "none_hard_rescue":
                raise RuntimeError("hard/rescue cases must not claim reference authority")
        return selected

    for row in selected:
        if row.get("reference_reliable") is not True:
            raise RuntimeError("OCR bakeoff requires reliable prepared references")
        if row.get("reference_authority") != "dual_channel_aligned":
            raise RuntimeError("OCR bakeoff reference authority is not dual-channel")
    return selected


def run(
    engine_name: str,
    manifest_path: Path,
    output_dir: Path,
    limit: int | None,
    shard_index: int = 0,
    shard_count: int = 1,
) -> int:
    cases = _manifest_cases(manifest_path, limit)
    if shard_count < 1 or shard_index < 0 or shard_index >= shard_count:
        raise ValueError("invalid shard index/count")
    cases = [case for index, case in enumerate(cases) if index % shard_count == shard_index]
    if not cases:
        raise RuntimeError("selected OCR shard has no cases")
    engine = Engine(engine_name)
    engine_config = _engine_config(engine_name)
    engine_config_id = _stable_json_sha256(engine_config)
    root = manifest_path.parent
    predictions: list[Prediction] = []
    started_all = time.perf_counter()

    for index, case in enumerate(cases, start=1):
        image_path = root / str(case["image_path"])
        started = time.perf_counter()
        error: str | None = None
        text = ""
        regions: list[Region] = []
        try:
            text, regions = engine.predict(image_path)
            if not text.strip():
                error = "empty_output"
        except Exception as exc:  # noqa: BLE001 - engine failures are benchmark data
            error = f"{type(exc).__name__}: {exc}"
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        prediction = Prediction(
            observation_id=_observation_identity(
                engine_name, engine.version, engine_config_id, case
            ),
            sample_id=str(case["sample_id"]),
            engine=engine_name,
            engine_version=engine.version,
            engine_config_id=engine_config_id,
            source_pdf_sha256=str(case["source_pdf_sha256"]),
            page_index=int(case["page_index"]),
            image_sha256=str(case["image_sha256"]),
            text=text,
            elapsed_ms=elapsed_ms,
            error=error,
            regions=[region_to_json(region) for region in regions],
        )
        predictions.append(prediction)
        print(
            json.dumps(
                {
                    "engine": engine_name,
                    "page": index,
                    "total": len(cases),
                    "sample_id": prediction.sample_id,
                    "elapsed_ms": elapsed_ms,
                    "error": error,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = output_dir / "predictions.jsonl"
    prediction_path.write_text(
        "".join(
            json.dumps(asdict(item), ensure_ascii=False, sort_keys=True) + "\n"
            for item in predictions
        ),
        encoding="utf-8",
    )
    failures = sum(item.error is not None for item in predictions)
    elapsed_seconds = time.perf_counter() - started_all
    summary = {
        "schema_version": 2,
        "engine": engine_name,
        "engine_version": engine.version,
        "engine_config": engine_config,
        "engine_config_id": engine_config_id,
        "pages": len(predictions),
        "successful_pages": len(predictions) - failures,
        "failed_pages": failures,
        "wall_seconds": elapsed_seconds,
        "mean_wall_seconds_per_page": elapsed_seconds / len(predictions),
        "peak_rss_kib": _peak_rss_kib(),
        "python": sys.version,
    }
    (output_dir / "runtime-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if failures == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--engine",
        required=True,
        choices=("tesseract", "easyocr", "paddleocr", "rapidocr", "doctr", "surya"),
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be positive")
    return run(
        args.engine,
        args.manifest,
        args.output,
        args.limit,
        args.shard_index,
        args.shard_count,
    )


if __name__ == "__main__":
    raise SystemExit(main())
