from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from jurisnexo.acquisition.official_corpus import (
    ArtifactCatalog,
    HttpFetcher,
    ObjectStore,
    OfficialDocumentCandidate,
    SourceName,
    StoredOfficialArtifact,
    acquire_candidates,
)


@dataclass(frozen=True, slots=True)
class AcquisitionManifestRecord:
    source: SourceName
    source_identifier: str
    discovery_url: str
    document_url: str
    sha256: str
    byte_count: int
    object_key: str

    def to_artifact(self, candidate: OfficialDocumentCandidate) -> StoredOfficialArtifact:
        return StoredOfficialArtifact(
            candidate=candidate,
            sha256=self.sha256,
            byte_count=self.byte_count,
            object_key=self.object_key,
            already_present=True,
        )


class FileAcquisitionManifest:
    """Append-only JSONL history and latest checkpoint for deterministic acquisition."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._records: dict[tuple[SourceName, str], AcquisitionManifestRecord] = {}
        if path.exists():
            self._load()

    @staticmethod
    def _key(source: SourceName, document_url: str) -> tuple[SourceName, str]:
        return source, document_url

    def _load(self) -> None:
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                record = AcquisitionManifestRecord(**payload)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"invalid acquisition manifest record at line {line_number}"
                ) from exc
            self._records[self._key(record.source, record.document_url)] = record

    def get(self, candidate: OfficialDocumentCandidate) -> AcquisitionManifestRecord | None:
        return self._records.get(self._key(candidate.source, candidate.document_url))

    def append(self, artifact: StoredOfficialArtifact) -> None:
        record = AcquisitionManifestRecord(
            source=artifact.candidate.source,
            source_identifier=artifact.candidate.source_identifier,
            discovery_url=artifact.candidate.discovery_url,
            document_url=artifact.candidate.document_url,
            sha256=artifact.sha256,
            byte_count=artifact.byte_count,
            object_key=artifact.object_key,
        )
        key = self._key(record.source, record.document_url)
        existing = self._records.get(key)
        if existing == record:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
        self._records[key] = record


def acquire_candidates_resumable(
    *,
    candidates: tuple[OfficialDocumentCandidate, ...],
    fetcher: HttpFetcher,
    object_store: ObjectStore,
    manifest: FileAcquisitionManifest,
    artifact_catalog: ArtifactCatalog | None = None,
    refresh: bool = False,
) -> tuple[StoredOfficialArtifact, ...]:
    """Acquire candidates and preserve every successful URL-to-content observation."""

    results: list[StoredOfficialArtifact] = []
    seen_urls: set[tuple[SourceName, str]] = set()
    for candidate in candidates:
        key = (candidate.source, candidate.document_url)
        if key in seen_urls:
            continue
        seen_urls.add(key)

        existing = manifest.get(candidate)
        if existing is not None and not refresh:
            artifact = existing.to_artifact(candidate)
            if artifact_catalog is not None:
                artifact_catalog.register(artifact)
            results.append(artifact)
            continue

        acquired = acquire_candidates(
            candidates=(candidate,),
            fetcher=fetcher,
            object_store=object_store,
            artifact_catalog=artifact_catalog,
        )[0]
        manifest.append(acquired)
        results.append(acquired)
    return tuple(results)
