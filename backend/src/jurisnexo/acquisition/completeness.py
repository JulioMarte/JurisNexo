from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jurisnexo.acquisition.official_corpus import (
    ObjectStore,
    OfficialDocumentCandidate,
    SourceName,
    object_key_for,
)


@dataclass(frozen=True, slots=True)
class RegisteredArtifactObservation:
    source: SourceName
    source_identifier: str
    document_url: str
    sha256: str


class RegisteredArtifactInventory(Protocol):
    def observations_for(self, source: SourceName) -> tuple[RegisteredArtifactObservation, ...]: ...


@dataclass(frozen=True, slots=True)
class SourceInventorySnapshot:
    source: SourceName
    candidates: tuple[OfficialDocumentCandidate, ...]
    enumeration_complete: bool
    enumeration_basis: str


@dataclass(frozen=True, slots=True)
class CorpusCompletenessReport:
    source: SourceName
    enumeration_complete: bool
    enumeration_basis: str
    discovered_count: int
    registered_count: int
    storage_verified_count: int
    missing_identifiers: tuple[str, ...]
    missing_storage_identifiers: tuple[str, ...]
    ambiguous_identifiers: tuple[str, ...]
    unexpected_current_catalog_identifiers: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return (
            self.enumeration_complete
            and not self.missing_identifiers
            and not self.missing_storage_identifiers
            and not self.ambiguous_identifiers
            and self.discovered_count == self.registered_count
            and self.registered_count == self.storage_verified_count
        )

    def require_complete(self) -> None:
        if not self.enumeration_complete:
            raise ValueError(
                f"{self.source} inventory cannot be certified complete: {self.enumeration_basis}"
            )
        if not self.complete:
            raise ValueError(
                f"{self.source} corpus is incomplete: "
                f"discovered={self.discovered_count}, registered={self.registered_count}, "
                f"storage_verified={self.storage_verified_count}, "
                f"missing={list(self.missing_identifiers)}, "
                f"missing_storage={list(self.missing_storage_identifiers)}, "
                f"ambiguous={list(self.ambiguous_identifiers)}"
            )


def verify_source_completeness(
    *,
    snapshot: SourceInventorySnapshot,
    inventory: RegisteredArtifactInventory,
    object_store: ObjectStore,
) -> CorpusCompletenessReport:
    """Certify current official inventory against PostgreSQL observations and object storage."""

    expected_by_identifier: dict[str, OfficialDocumentCandidate] = {}
    ambiguous: set[str] = set()
    for candidate in snapshot.candidates:
        if candidate.source != snapshot.source:
            raise ValueError("source inventory snapshot contains a candidate from another source")
        existing = expected_by_identifier.get(candidate.source_identifier)
        if existing is not None and existing.document_url != candidate.document_url:
            ambiguous.add(candidate.source_identifier)
        expected_by_identifier[candidate.source_identifier] = candidate

    current_observations = inventory.observations_for(snapshot.source)
    observations_by_identifier: dict[str, list[RegisteredArtifactObservation]] = {}
    for observation in current_observations:
        observations_by_identifier.setdefault(observation.source_identifier, []).append(observation)

    missing: list[str] = []
    missing_storage: list[str] = []
    registered_count = 0
    storage_verified_count = 0

    for identifier, candidate in expected_by_identifier.items():
        matches = [
            observation
            for observation in observations_by_identifier.get(identifier, [])
            if observation.document_url == candidate.document_url
        ]
        unique_hashes = {observation.sha256 for observation in matches}
        if len(unique_hashes) > 1:
            ambiguous.add(identifier)
            continue
        if not matches:
            missing.append(identifier)
            continue

        registered_count += 1
        digest = matches[-1].sha256
        object_key = object_key_for(source=snapshot.source, sha256=digest)
        if object_store.exists(object_key):
            storage_verified_count += 1
        else:
            missing_storage.append(identifier)

    unexpected = sorted(
        identifier
        for identifier in observations_by_identifier
        if identifier not in expected_by_identifier
    )

    return CorpusCompletenessReport(
        source=snapshot.source,
        enumeration_complete=snapshot.enumeration_complete,
        enumeration_basis=snapshot.enumeration_basis,
        discovered_count=len(expected_by_identifier),
        registered_count=registered_count,
        storage_verified_count=storage_verified_count,
        missing_identifiers=tuple(sorted(missing)),
        missing_storage_identifiers=tuple(sorted(missing_storage)),
        ambiguous_identifiers=tuple(sorted(ambiguous)),
        unexpected_current_catalog_identifiers=tuple(unexpected),
    )
