from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass
class MemoryFetcher:
    documents: dict[str, bytes]
    requested: list[str] = field(default_factory=list)

    def get_bytes(self, url: str) -> bytes:
        self.requested.append(url)
        return self.documents[url]


@dataclass
class MemoryObjectStore:
    keys: set[str] = field(default_factory=set)

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
        del content, content_type, metadata
        self.keys.add(key)


@dataclass
class MemoryCatalog:
    observations: list[RegisteredArtifactObservation] = field(default_factory=list)

    def observations_for(self, source: SourceName) -> tuple[RegisteredArtifactObservation, ...]:
        return tuple(item for item in self.observations if item.source == source)

    def register(self, artifact: StoredOfficialArtifact) -> RegisteredArtifactObservation:
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


def test_object_keys_are_partitioned_by_jurisdiction_source_and_collection() -> None:
    digest = "a" * 64
    tc_key = object_key_for(source="constitutional_court", sha256=digest)
    scj_key = object_key_for(source="supreme_court", sha256=digest)

    assert tc_key == f"jurisdictions/do/tc/decisions/aa/{digest}.pdf"
    assert scj_key == f"jurisdictions/do/scj/decisions/aa/{digest}.pdf"
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
    fetcher = MemoryFetcher(documents={missing.document_url: missing_pdf})
    store = MemoryObjectStore(keys={present_key})

    result = reconcile_source(
        snapshot=SourceInventorySnapshot(
            source="constitutional_court",
            candidates=(present, missing),
            enumeration_complete=True,
            enumeration_basis="complete fixture",
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
    missing_key = object_key_for(
        source="constitutional_court",
        sha256=sha256_hex(missing_pdf),
    )
    assert missing_key in store.keys


def test_reconciliation_repairs_missing_object_for_registered_document() -> None:
    candidate = _candidate(
        "TC/0100/26",
        "https://blob.example/TC-0100-26.pdf",
    )
    content = b"%PDF-1.7 restore"
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
    fetcher = MemoryFetcher(documents={candidate.document_url: content})
    store = MemoryObjectStore()

    result = reconcile_source(
        snapshot=SourceInventorySnapshot(
            source="constitutional_court",
            candidates=(candidate,),
            enumeration_complete=True,
            enumeration_basis="complete fixture",
        ),
        inventory=catalog,
        fetcher=fetcher,
        object_store=store,
        artifact_catalog=catalog,
    )

    assert fetcher.requested == [candidate.document_url]
    assert result.plan.storage_repair_count == 1
    assert result.report.complete is True


def test_incomplete_source_inventory_cannot_be_certified() -> None:
    candidate = _candidate(
        "TC/0200/26",
        "https://blob.example/TC-0200-26.pdf",
    )
    content = b"%PDF-1.7 fixture"
    fetcher = MemoryFetcher(documents={candidate.document_url: content})
    store = MemoryObjectStore()
    catalog = MemoryCatalog()

    result = reconcile_source(
        snapshot=SourceInventorySnapshot(
            source="constitutional_court",
            candidates=(candidate,),
            enumeration_complete=False,
            enumeration_basis="bounded test inventory",
        ),
        inventory=catalog,
        fetcher=fetcher,
        object_store=store,
        artifact_catalog=catalog,
    )

    assert result.report.complete is False
    assert "enumeration" in result.report.reason.casefold()
