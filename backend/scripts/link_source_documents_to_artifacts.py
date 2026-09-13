from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg

SOURCE = os.environ["SOURCE_DOCUMENT_LINK_SOURCE"]
COLLECTION = os.environ.get("SOURCE_DOCUMENT_LINK_COLLECTION", "").strip() or None
OUTPUT_DIR = Path(os.environ["SOURCE_DOCUMENT_LINK_OUTPUT"])


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(
                """
                WITH candidates AS (
                    SELECT DISTINCT ON (sd.id)
                        sd.id AS source_document_id,
                        sal.artifact_id
                    FROM corpus.source_documents sd
                    JOIN corpus.source_registries sr
                      ON sr.id = sd.source_registry_id
                    JOIN corpus.source_artifact_locations sal
                      ON sal.source_registry_id = sd.source_registry_id
                     AND sal.locator_type = 'official_url'
                     AND sal.locator = sd.current_document_url
                    WHERE sr.code = %s
                      AND (%s IS NULL OR sd.source_collection = %s)
                      AND sd.artifact_availability = 'available'
                      AND sd.current_document_url IS NOT NULL
                    ORDER BY sd.id, sal.last_seen_at DESC, sal.id DESC
                )
                INSERT INTO corpus.source_document_artifacts (
                    source_document_id, artifact_id, relationship_type
                )
                SELECT source_document_id, artifact_id, 'primary'
                FROM candidates
                ON CONFLICT (source_document_id, artifact_id, relationship_type)
                DO UPDATE SET last_seen_at = clock_timestamp()
                """,
                (SOURCE, COLLECTION, COLLECTION),
            )
            cursor.execute(
                """
                SELECT
                    count(*) FILTER (WHERE sd.artifact_availability = 'available') AS available,
                    count(*) FILTER (WHERE sd.artifact_availability = 'not_published') AS not_published,
                    count(*) FILTER (
                        WHERE sd.artifact_availability = 'available'
                          AND sda.source_document_id IS NULL
                    ) AS available_unlinked,
                    count(*) FILTER (WHERE sda.source_document_id IS NOT NULL) AS linked
                FROM corpus.source_documents sd
                JOIN corpus.source_registries sr ON sr.id = sd.source_registry_id
                LEFT JOIN corpus.source_document_artifacts sda
                  ON sda.source_document_id = sd.id
                 AND sda.relationship_type = 'primary'
                WHERE sr.code = %s
                  AND (%s IS NULL OR sd.source_collection = %s)
                """,
                (SOURCE, COLLECTION, COLLECTION),
            )
            row = cursor.fetchone()
    if row is None:
        raise RuntimeError("source document linkage summary query returned no row")
    available, not_published, available_unlinked, linked = (int(value or 0) for value in row)
    summary = {
        "status": "COMPLETE" if available_unlinked == 0 else "INCOMPLETE",
        "source": SOURCE,
        "source_collection": COLLECTION,
        "available_source_documents": available,
        "not_published_source_documents": not_published,
        "linked_source_documents": linked,
        "available_unlinked_source_documents": available_unlinked,
    }
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    if available_unlinked:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
