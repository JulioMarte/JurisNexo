from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jurisnexo.acquisition.completeness import (
    RegisteredArtifactObservation,
    SourceInventorySnapshot,
)
from jurisnexo.acquisition.official_corpus import (
    OfficialDocumentCandidate,
    SourceName,
    StoredOfficialArtifact,
    object_key_for,
    sha256_hex,
)
from jurisnexo.acquisition.reconciliation import reconcile_source

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _empty_keys() -> set[str]:
    return set()


def _empty_observations() -> list[RegisteredArtifactObservation]:
    return []


def _empty_requests() -> list[str]:
    return []


@dataclass(slots=True)
class MemoryFetcher:
    documents: dict[str, bytes]
    requested: list[str] = field(default_factory=_empty_requests)

    def get_bytes(self, url: str) -> bytes:
        self.requested.append(url)
        return self.documents[url]


@dataclass(slots=True)
class MemoryObjectStore:
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
        assert content.startswith(b"%PDF")
        assert content_type == "application/pdf"
        assert metadata["sha256"] == sha256_hex(content)
        self.keys.add(key)


@dataclass(slots=True)
class MemoryCatalog:
    observations: list[RegisteredArtifactObservation] = field(
        default_factory=_empty_observations
    )

    def observations_for(self, source: SourceName) -> tuple[RegisteredArtifactObservation, ...]:
        return tuple(item for item in self.observations if item.source == source)

    def register(self, artifact: StoredOfficialArtifact) -> object:
        observation = RegisteredArtifactObservation(
            source=artifact.candidate.source,
            source_identifier=artifact.candidate.source_identifier,
            document_url=artifact.candidate.document_url,
            sha256=artifact.sha256,
        )
        self.observations = [
            item
            for item in self.observations
            if not (
                item.source == observation.source
                and item.source_identifier == observation.source_identifier
                and item.document_url == observation.document_url
            )
        ]
        self.observations.append(observation)
        return observation


def _candidate(
    identifier: str,
    url: str,
    *,
    source: SourceName = "constitutional_court",
) -> OfficialDocumentCandidate:
    return OfficialDocumentCandidate(
        source=source,
        source_identifier=identifier,
        discovery_url=f"https://official.example/details/{identifier}",
        document_url=url,
    )


def test_object_keys_are_partitioned_by_official_source() -> None:
    digest = "a" * 64
    tc_key = object_key_for(source="constitutional_court", sha256=digest)
    scj_key = object_key_for(source="supreme_court", sha256=digest)

    assert tc_key == f"official/constitutional_court/aa/{digest}.pdf"
    assert scj_key == f"official/supreme_court/aa/{digest}.pdf"
    assert tc_key != scj_key


def test_reconciliation_fetches_only_documents_missing_from_catalog() -> None:
    present = _candidate(
        "TC/0001/26",
        "https://blob.example/TC-0001-26.pdf",
    )
    missing = _candidate(
        "TC/0002/26",
        "https://blob.example/TC-0002-26.pdf",
    )
    present_pdf = b"%PDF-1.7 present"
    missing_pdf = b"%PDF-1.7 missing"
    present_digest = sha256_hex(present_pdf)
    present_key = object_key_for(source="constitutional_court", sha256=present_digest)

    catalog = MemoryCatalog(
        observations=[
            RegisteredArtifactObservation(
                source="constitutional_court",
                source_identifier=present.source_identifier,
                document_url=present.document_url,
                sha256=present_digest,
            )
        ]
    )
    store = MemoryObjectStore(keys={present_key})
    fetcher = MemoryFetcher(documents={missing.document_url: missing_pdf})

    result = reconcile_source(
        snapshot=SourceInventorySnapshot(
            source="constitutional_court",
            candidates=(present, missing),
            enumeration_complete=True,
            enumeration_basis="complete fixture inventory",
        ),
        inventory=catalog,
        fetcher=fetcher,
        object_store=store,
        artifact_catalog=catalog,
    )

    assert fetcher.requested == [missing.document_url]
    assert result.plan.acquisition_count == 1
    assert result.acquired_count == 1
    assert result.report.complete is True
    assert result.report.discovered_count == 2
    assert result.report.registered_count == 2
    assert result.report.storage_verified_count == 2


def test_reconciliation_repairs_missing_object_without_losing_registration() -> None:
    candidate = _candidate(
        "TC/0003/26",
        "https://blob.example/TC-0003-26.pdf",
    )
    content = b"%PDF-1.7 restore-me"
    digest = sha256_hex(content)
    catalog = MemoryCatalog(
        observations=[
            RegisteredArtifactObservation(
                source="constitutional_court",
                source_identifier=candidate.source_identifier,
                document_url=candidate.document_url,
                sha256=digest,
            )
        ]
    )
    store = MemoryObjectStore()
    fetcher = MemoryFetcher(documents={candidate.document_url: content})

    result = reconcile_source(
        snapshot=SourceInventorySnapshot(
            source="constitutional_court",
            candidates=(candidate,),
            enumeration_complete=True,
            enumeration_basis="complete fixture inventory",
        ),
        inventory=catalog,
        fetcher=fetcher,
        object_store=store,
        artifact_catalog=catalog,
    )

    assert result.plan.missing_registration == ()
    assert result.plan.missing_storage == (candidate,)
    assert result.report.complete is True
    assert object_key_for(source="constitutional_court", sha256=digest) in store.keys
