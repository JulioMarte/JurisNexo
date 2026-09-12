from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jurisnexo.acquisition.completeness import (
    RegisteredArtifactObservation,
    SourceInventorySnapshot,
    verify_source_completeness,
)
from jurisnexo.acquisition.official_corpus import OfficialDocumentCandidate, object_key_for

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _empty_keys() -> set[str]:
    return set()


@dataclass(slots=True)
class FakeInventory:
    observations: tuple[RegisteredArtifactObservation, ...]

    def observations_for(self, source: str) -> tuple[RegisteredArtifactObservation, ...]:
        return tuple(item for item in self.observations if item.source == source)


@dataclass(slots=True)
class FakeObjectStore:
    keys: set[str] = field(default_factory=_empty_keys)

    def exists(self, key: str) -> bool:
        return key in self.keys

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        self.keys.add(key)


def _candidate(identifier: str = "TC/0001/26") -> OfficialDocumentCandidate:
    return OfficialDocumentCandidate(
        source="constitutional_court",
        source_identifier=identifier,
        discovery_url=f"https://official.example/{identifier}",
        document_url=f"https://blob.example/{identifier.replace('/', '-')}.pdf",
    )


def test_complete_requires_database_and_object_storage_match() -> None:
    candidate = _candidate()
    digest = "a" * 64
    report = verify_source_completeness(
        snapshot=SourceInventorySnapshot(
            source="constitutional_court",
            candidates=(candidate,),
            enumeration_complete=True,
            enumeration_basis="fixture complete listing",
        ),
        inventory=FakeInventory(
            observations=(
                RegisteredArtifactObservation(
                    source="constitutional_court",
                    source_identifier=candidate.source_identifier,
                    document_url=candidate.document_url,
                    sha256=digest,
                ),
            )
        ),
        object_store=FakeObjectStore(
            keys={object_key_for(source="constitutional_court", sha256=digest)}
        ),
    )

    assert report.complete is True
    report.require_complete()


def test_missing_postgres_registration_fails_certification() -> None:
    candidate = _candidate()
    report = verify_source_completeness(
        snapshot=SourceInventorySnapshot(
            source="constitutional_court",
            candidates=(candidate,),
            enumeration_complete=True,
            enumeration_basis="fixture complete listing",
        ),
        inventory=FakeInventory(observations=()),
        object_store=FakeObjectStore(),
    )

    assert report.missing_identifiers == (candidate.source_identifier,)
    with pytest.raises(ValueError, match="corpus is incomplete"):
        report.require_complete()


def test_missing_storage_object_fails_even_when_postgres_exists() -> None:
    candidate = _candidate()
    report = verify_source_completeness(
        snapshot=SourceInventorySnapshot(
            source="constitutional_court",
            candidates=(candidate,),
            enumeration_complete=True,
            enumeration_basis="fixture complete listing",
        ),
        inventory=FakeInventory(
            observations=(
                RegisteredArtifactObservation(
                    source="constitutional_court",
                    source_identifier=candidate.source_identifier,
                    document_url=candidate.document_url,
                    sha256="b" * 64,
                ),
            )
        ),
        object_store=FakeObjectStore(),
    )

    assert report.missing_storage_identifiers == (candidate.source_identifier,)
    assert report.complete is False


def test_uncertified_enumerator_can_never_claim_one_hundred_percent() -> None:
    report = verify_source_completeness(
        snapshot=SourceInventorySnapshot(
            source="supreme_court",
            candidates=(),
            enumeration_complete=False,
            enumeration_basis="landing page only",
        ),
        inventory=FakeInventory(observations=()),
        object_store=FakeObjectStore(),
    )

    assert report.complete is False
    with pytest.raises(ValueError, match="cannot be certified complete"):
        report.require_complete()


def test_ambiguous_same_identifier_is_rejected() -> None:
    first = _candidate("TC/0002/26")
    second = OfficialDocumentCandidate(
        source=first.source,
        source_identifier=first.source_identifier,
        discovery_url=first.discovery_url,
        document_url="https://blob.example/replacement.pdf",
    )
    report = verify_source_completeness(
        snapshot=SourceInventorySnapshot(
            source="constitutional_court",
            candidates=(first, second),
            enumeration_complete=True,
            enumeration_basis="fixture complete listing",
        ),
        inventory=FakeInventory(observations=()),
        object_store=FakeObjectStore(),
    )

    assert report.ambiguous_identifiers == (first.source_identifier,)
    assert report.complete is False
