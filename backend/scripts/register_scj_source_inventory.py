from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import psycopg

from jurisnexo.corpus.source_inventory import (
    PostgresSourceDocumentInventory,
    scj_source_observation_from_record,
)

PORTAL = "https://consultasentenciascj.poderjudicial.gob.do/"
INPUT = Path(os.environ["SCJ_SOURCE_INVENTORY_FILE"])
OUTPUT_DIR = Path(os.environ["SCJ_SOURCE_INVENTORY_OUTPUT"])


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    artifact_ready = OUTPUT_DIR / "scj-artifact-ready.inventory.jsonl"
    observed = 0
    available = 0
    metadata_only = 0
    normalized = 0

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
        inventory = PostgresSourceDocumentInventory(connection=connection)
        with INPUT.open(encoding="utf-8") as source, artifact_ready.open("w", encoding="utf-8") as output:
            for line in source:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise TypeError("SCJ certified inventory contains a non-object record")
                observation = scj_source_observation_from_record(record=record, discovery_url=PORTAL)
                inventory.observe(observation)
                observed += 1
                if observation.normalization_notes.get("document_url_normalization"):
                    normalized += 1
                if observation.artifact_availability != "available":
                    metadata_only += 1
                    continue
                available += 1
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
                output.write(json.dumps(prepared, ensure_ascii=False, sort_keys=True) + "\n")

    summary = {
        "status": "COMPLETE",
        "source": "supreme_court",
        "observed_source_record_count": observed,
        "artifact_available_record_count": available,
        "metadata_only_record_count": metadata_only,
        "normalized_document_url_count": normalized,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
