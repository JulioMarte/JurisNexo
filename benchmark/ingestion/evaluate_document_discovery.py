from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

from jurisnexo.ingestion.discovery_evaluation import (
    DiscoveryStructuralTruth,
    evaluate_discovery_structure,
)
from jurisnexo.ingestion.document_discovery import DocumentStructureHypothesis
from jurisnexo.model_providers.contracts import JsonObject


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score a JurisNexo discovery result")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result_payload = cast(JsonObject, json.loads(args.result.read_text(encoding="utf-8")))
    truth_payload = cast(JsonObject, json.loads(args.truth.read_text(encoding="utf-8")))

    raw_hypothesis = result_payload.get("hypothesis")
    if not isinstance(raw_hypothesis, dict):
        raise SystemExit("discovery result does not contain an object hypothesis")

    hypothesis = DocumentStructureHypothesis.model_validate(raw_hypothesis)
    truth = DiscoveryStructuralTruth.model_validate(truth_payload)
    score = evaluate_discovery_structure(hypothesis=hypothesis, truth=truth)

    output = {
        "score": asdict(score),
        "expected": truth.model_dump(mode="json"),
        "predicted": {
            "artifact_class": hypothesis.artifact_class,
            "has_index": hypothesis.has_index,
            "index_pages": hypothesis.index_page_candidates,
            "segments": [
                segment.model_dump(mode="json") for segment in hypothesis.candidate_segments
            ],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
