from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import psycopg

from jurisnexo.corpus.source_inventory import (
    PostgresSourceDocumentInventory,
    SourceDocumentObservation,
    scj_source_observation_from_record,
)

PORTAL = "https://consultasentenciascj.poderjudicial.gob.do/"
INPUT = Path(os.environ["SCJ_SOURCE_INVENTORY_FILE"])
OUTPUT_DIR = Path(os.environ["SCJ_SOURCE_INVENTORY_OUTPUT"])
BATCH_SIZE = int(os.environ.get("SCJ_SOURCE_REGISTRATION_BATCH_SIZE", "1000"))


def prepare_artifact_record(
    *, record: dict[str, Any], observation: SourceDocumentObservation
) -> dict[str, Any]:
    prepared: dict[str, Any] = dict(record)
    row = record.get("row")
    if not isinstance(row, dict):
        raise TypeError("SCJ inventory record is missing row")
    prepared_row = dict(row)
    if str(record.get("surface") or "") == "bulletins":
        prepared_row["urlCuerpo"] = observation.document_url
    prepared["row"] = prepared_row
    prepared["_document_url"] = observation.document_url
    prepared["_artifact_availability"] = observation.artifact_availability
    prepared["_normalization_notes"] = observation.normalization_notes
    return prepared


def main() -> None:
    if BATCH_SIZE < 1 or BATCH_SIZE > 5000:
        raise ValueError("SCJ_SOURCE_REGISTRATION_BATCH_SIZE must be between 1 and 5000")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    artifact_ready = OUTPUT_DIR / "scj-artifact-ready.inventory.jsonl"
    observed = 0
    available = 0
    metadata_only = 0
    normalized = 0
    committed_batches = 0

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
        inventory = PostgresSourceDocumentInventory(connection=connection)
        with INPUT.open(encoding="utf-8") as source, artifact_ready.open(
            "w", encoding="utf-8"
        ) as output:
            pending_observations: list[SourceDocumentObservation] = []
            pending_artifacts: list[dict[str, Any]] = []

            def flush() -> None:
                nonlocal committed_batches
                if not pending_observations:
                    return
                inventory.observe_many(pending_observations)
                for prepared in pending_artifacts:
                    output.write(json.dumps(prepared, ensure_ascii=False, sort_keys=True) + "\n")
                output.flush()
                committed_batches += 1
                print(
                    json.dumps(
                        {
                            "event": "scj_source_registration_progress",
                            "committed_batches": committed_batches,
                            "observed_source_records": observed,
                            "artifact_available_records": available,
                            "metadata_only_records": metadata_only,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                pending_observations.clear()
                pending_artifacts.clear()

            for line in source:
                if not line.strip():
                    continue
                record_value = json.loads(line)
                if not isinstance(record_value, dict):
                    raise TypeError("SCJ certified inventory contains a non-object record")
                record: dict[str, Any] = record_value
                observation = scj_source_observation_from_record(
                    record=record,
                    discovery_url=PORTAL,
                )
                pending_observations.append(observation)
                observed += 1
                if observation.normalization_notes.get("document_url_normalization"):
                    normalized += 1
                if observation.artifact_availability != "available":
                    metadata_only += 1
                else:
                    available += 1
                    pending_artifacts.append(
                        prepare_artifact_record(record=record, observation=observation)
                    )

                if len(pending_observations) >= BATCH_SIZE:
                    flush()

            flush()

    summary = {
        "status": "COMPLETE",
        "source": "supreme_court",
        "observed_source_record_count": observed,
        "artifact_available_record_count": available,
        "metadata_only_record_count": metadata_only,
        "normalized_document_url_count": normalized,
        "registration_batch_size": BATCH_SIZE,
        "committed_batch_count": committed_batches,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
