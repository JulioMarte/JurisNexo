from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ENGINES = ("paddleocr", "rapidocr", "tesseract")


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b), autojunk=False).ratio()


def _load_predictions(path: Path, expected_engine: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    observation_ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        sample_id = str(row["sample_id"])
        if sample_id in rows:
            raise RuntimeError(f"duplicate sample_id for {expected_engine}: {sample_id}")
        if row.get("engine") != expected_engine:
            raise RuntimeError(
                f"engine provenance mismatch: expected {expected_engine}, got {row.get('engine')}"
            )
        observation_id = str(row.get("observation_id") or "")
        if not observation_id.startswith(f"ocr:{expected_engine}:"):
            raise RuntimeError(f"invalid observation_id for {expected_engine}: {observation_id}")
        if observation_id in observation_ids:
            raise RuntimeError(f"duplicate observation_id: {observation_id}")
        observation_ids.add(observation_id)
        rows[sample_id] = row
    return rows


def _labels(sample_id: str) -> dict[str, str]:
    ranked = sorted(
        ENGINES,
        key=lambda engine: hashlib.sha256(f"20260930:{sample_id}:{engine}".encode()).hexdigest(),
    )
    return {engine: chr(ord("A") + idx) for idx, engine in enumerate(ranked)}


def aggregate(manifest_path: Path, inputs: dict[str, Path], output: Path) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    predictions = {
        engine: _load_predictions(path, engine) for engine, path in inputs.items()
    }
    output.mkdir(parents=True, exist_ok=True)
    blind_root = output / "blind-cases"
    reveal: dict[str, dict[str, str]] = {}
    records: list[dict[str, Any]] = []

    for case in cases:
        sample_id = str(case["sample_id"])
        labels = _labels(sample_id)
        missing = [engine for engine in ENGINES if sample_id not in predictions[engine]]
        if missing:
            raise RuntimeError(f"missing candidate observations for {sample_id}: {missing}")
        for engine in ENGINES:
            observation = predictions[engine][sample_id]
            for field in ("source_pdf_sha256", "page_index", "image_sha256"):
                if str(observation[field]) != str(case[field]):
                    raise RuntimeError(
                        f"{field} provenance mismatch for {sample_id}/{engine}"
                    )
        reveal[sample_id] = {
            labels[engine]: {
                "engine": engine,
                "observation_id": predictions[engine][sample_id]["observation_id"],
                "engine_version": predictions[engine][sample_id]["engine_version"],
                "engine_config_id": predictions[engine][sample_id]["engine_config_id"],
            }
            for engine in ENGINES
        }
        texts = {engine: str(predictions[engine][sample_id].get("text") or "") for engine in ENGINES}
        errors = {engine: predictions[engine][sample_id].get("error") for engine in ENGINES}
        similarities = {
            "paddleocr_rapidocr": _similarity(texts["paddleocr"], texts["rapidocr"]),
            "paddleocr_tesseract": _similarity(texts["paddleocr"], texts["tesseract"]),
            "rapidocr_tesseract": _similarity(texts["rapidocr"], texts["tesseract"]),
        }
        minimum_similarity = min(similarities.values())
        exact_consensus = len({_normalize(text) for text in texts.values()}) == 1 and not any(errors.values())
        priority = 0 if exact_consensus else (2 if minimum_similarity < 0.95 else 1)
        record = {
            "sample_id": sample_id,
            "object_key": case["object_key"],
            "page_index": case["page_index"],
            "image_sha256": case["image_sha256"],
            "exact_consensus": exact_consensus,
            "minimum_pairwise_similarity": minimum_similarity,
            "pairwise_similarity": similarities,
            "priority": priority,
            "engine_errors": errors,
        }
        records.append(record)

        case_dir = blind_root / sample_id
        case_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_path.parent / case["image_path"], case_dir / "input-page.png")
        for engine, text in texts.items():
            label = labels[engine]
            observation = predictions[engine][sample_id]
            (case_dir / f"candidate-{label}.txt").write_text(text, encoding="utf-8")
            (case_dir / f"candidate-{label}.json").write_text(
                json.dumps(
                    {
                        "candidate_id": f"{sample_id}:{label}",
                        "observation_id": observation["observation_id"],
                        "sample_id": sample_id,
                        "blind_label": label,
                        "source_pdf_sha256": observation["source_pdf_sha256"],
                        "page_index": observation["page_index"],
                        "image_sha256": observation["image_sha256"],
                        "text_file": f"candidate-{label}.txt",
                        "engine_identity_blinded": True,
                    },
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
        (case_dir / "adjudication-template.json").write_text(
            json.dumps({
                "sample_id": sample_id,
                "visual_transcription": None,
                "decision": None,
                "confidence": None,
                "ambiguous": None,
                "notes": None,
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (case_dir / "triage.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    records.sort(key=lambda row: (-row["priority"], row["minimum_pairwise_similarity"], row["sample_id"]))
    (output / "triage.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in records), encoding="utf-8"
    )
    (output / "blind-manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "cases": records,
            "instructions": (
                "Inspect input-page.png first. Record an independent visual transcription before "
                "comparing anonymous candidates A/B/C. ambiguous is a valid result."
            ),
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "candidate-reveal.json").write_text(
        json.dumps(reveal, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = {
        "pages": len(records),
        "exact_consensus_pages": sum(row["exact_consensus"] for row in records),
        "material_disagreement_pages": sum(row["priority"] == 2 for row in records),
        "minor_disagreement_pages": sum(row["priority"] == 1 for row in records),
        "failed_engine_observations": sum(
            bool(error) for row in records for error in row["engine_errors"].values()
        ),
        "mean_minimum_pairwise_similarity": (
            sum(row["minimum_pairwise_similarity"] for row in records) / len(records)
            if records else None
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--paddleocr", type=Path, required=True)
    parser.add_argument("--rapidocr", type=Path, required=True)
    parser.add_argument("--tesseract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return aggregate(
        args.manifest,
        {"paddleocr": args.paddleocr, "rapidocr": args.rapidocr, "tesseract": args.tesseract},
        args.output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
