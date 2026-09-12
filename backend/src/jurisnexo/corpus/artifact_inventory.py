from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from jurisnexo.acquisition.completeness import RegisteredArtifactObservation
from jurisnexo.acquisition.official_corpus import SourceName


@dataclass(slots=True)
class PostgresRegisteredArtifactInventory:
    connection: psycopg.Connection[Any]

    def observations_for(self, source: SourceName) -> tuple[RegisteredArtifactObservation, ...]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                select
                    r.code,
                    l.source_identifier,
                    l.locator,
                    a.sha256
                from corpus.source_artifact_locations l
                join corpus.source_artifacts a on a.id = l.artifact_id
                join corpus.source_registries r on r.id = l.source_registry_id
                where r.code = %s
                  and l.locator_type = 'official_url'
                  and l.source_identifier is not null
                order by l.source_identifier, l.last_seen_at, l.id
                """,
                (source,),
            )
            rows = cursor.fetchall()

        return tuple(
            RegisteredArtifactObservation(
                source=row[0],
                source_identifier=row[1],
                document_url=row[2],
                sha256=row[3],
            )
            for row in rows
        )
