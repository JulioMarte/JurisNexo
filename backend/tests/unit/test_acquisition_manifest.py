from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from jurisnexo.acquisition.manifest import (
    FileAcquisitionManifest,
    acquire_candidates_resumable,
)
from jurisnexo.acquisition.official_corpus import (
    OfficialDocumentCandidate,
    StoredOfficialArtifact,
    sha256_hex,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _empty_calls() -> list[str]:
    return []


def _empty_objects() -> dict[str, bytes]:
    return {}


def _empty_artifacts() -> list[StoredOfficialArtifact]:
    return []


@dataclass(slots=True)
class FakeFetcher:
    payloads: dict[str, bytes]
    calls: list[str] = field(default_factory=_empty_calls)

    def get_bytes(self, url: str) -> bytes:
        self.calls.append(url)
        return self.payloads[url]


@dataclass(slots=True)
class MemoryObjectStore:
    objects: dict[str, bytes] = field(default_factory=_empty_objects)

    def exists(self, key: str) -> bool:
        return key in self.objects

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        assert content_type == "application/pdf"
        assert metadata["sha256"] == sha256_hex(content)
        self.objects[key] = content


@dataclass(slots=True)
class RecordingCatalog:
    artifacts: list[StoredOfficialArtifact] = field(default_factory=_empty_artifacts)

    def register(self, artifact: StoredOfficialArtifact) -> object:
        self.artifacts.append(artifact)
        return artifact.sha256


def _candidate(url: str = "https://official.example/a.pdf") -> OfficialDocumentCandidate:
    return OfficialDocumentCandidate(
        source="constitutional_court",
        source_identifier="TC/0001/26",
        discovery_url="https://official.example/detail",
        document_url=url,
    )


def test_success_is_checkpointed_and_second_run_skips_network(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.jsonl"
    candidate = _candidate()
    fetcher = FakeFetcher(payloads={candidate.document_url: b"%PDF first"})
    store = MemoryObjectStore()

    first = acquire_candidates_resumable(
        candidates=(candidate,),
        fetcher=fetcher,
        object_store=store,
        manifest=FileAcquisitionManifest(manifest_path),
    )
    second = acquire_candidates_resumable(
        candidates=(candidate,),
        fetcher=fetcher,
        object_store=store,
        manifest=FileAcquisitionManifest(manifest_path),
    )

    assert first[0].already_present is False
    assert second[0].already_present is True
    assert fetcher.calls == [candidate.document_url]
    assert len(manifest_path.read_text(encoding="utf-8").splitlines()) == 1


def test_resume_hit_is_still_registered_in_durable_catalog(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.jsonl"
    candidate = _candidate()
    fetcher = FakeFetcher(payloads={candidate.document_url: b"%PDF first"})
    store = MemoryObjectStore()
    acquire_candidates_resumable(
        candidates=(candidate,),
        fetcher=fetcher,
        object_store=store,
        manifest=FileAcquisitionManifest(manifest_path),
    )

    catalog = RecordingCatalog()
    acquire_candidates_resumable(
        candidates=(candidate,),
        fetcher=fetcher,
        object_store=store,
        manifest=FileAcquisitionManifest(manifest_path),
        artifact_catalog=catalog,
    )

    assert fetcher.calls == [candidate.document_url]
    assert len(catalog.artifacts) == 1
    assert catalog.artifacts[0].already_present is True


def test_checkpoint_is_written_after_each_success(tmp_path: Path) -> None:
    first = _candidate("https://official.example/a.pdf")
    second = OfficialDocumentCandidate(
        source="constitutional_court",
        source_identifier="TC/0002/26",
        discovery_url="https://official.example/detail-2",
        document_url="https://official.example/b.pdf",
    )
    fetcher = FakeFetcher(
        payloads={
            first.document_url: b"%PDF first",
            second.document_url: b"not-a-pdf",
        }
    )
    manifest_path = tmp_path / "manifest.jsonl"

    with pytest.raises(ValueError, match="not a PDF"):
        acquire_candidates_resumable(
            candidates=(first, second),
            fetcher=fetcher,
            object_store=MemoryObjectStore(),
            manifest=FileAcquisitionManifest(manifest_path),
        )

    restored = FileAcquisitionManifest(manifest_path)
    assert restored.get(first) is not None
    assert restored.get(second) is None


def test_refresh_preserves_same_url_with_new_content_as_new_history(tmp_path: Path) -> None:
    candidate = _candidate()
    path = tmp_path / "manifest.jsonl"
    store = MemoryObjectStore()
    first = acquire_candidates_resumable(
        candidates=(candidate,),
        fetcher=FakeFetcher(payloads={candidate.document_url: b"%PDF first"}),
        object_store=store,
        manifest=FileAcquisitionManifest(path),
    )[0]

    second = acquire_candidates_resumable(
        candidates=(candidate,),
        fetcher=FakeFetcher(payloads={candidate.document_url: b"%PDF replaced"}),
        object_store=store,
        manifest=FileAcquisitionManifest(path),
        refresh=True,
    )[0]

    assert first.sha256 != second.sha256
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    latest = FileAcquisitionManifest(path).get(candidate)
    assert latest is not None
    assert latest.sha256 == second.sha256
    assert len(store.objects) == 2


def test_invalid_manifest_line_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "manifest.jsonl"
    path.write_text('{"unexpected": true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid acquisition manifest"):
        FileAcquisitionManifest(path)
