from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

import pytest

from jurisnexo.acquisition.manifest import (
    AcquisitionRunManifestBuilder,
    FileAcquisitionManifest,
    acquire_candidates_resumable,
    parse_acquisition_run_manifest,
)
from jurisnexo.acquisition.official_corpus import (
    OfficialDocumentCandidate,
    StoredOfficialArtifact,
    object_key_for,
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
        content: bytes | BinaryIO,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        payload = content if isinstance(content, bytes) else content.read()
        if content_type in {
            "application/pdf",
            "application/msword",
            "application/rtf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }:
            assert metadata["sha256"] == sha256_hex(payload)
        elif content_type == "application/json":
            assert metadata["payload_sha256"] == hashlib.sha256(payload).hexdigest()
            json.loads(payload)
        else:
            raise AssertionError(f"unexpected content type: {content_type}")
        self.objects[key] = payload


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

    with pytest.raises(ValueError, match="unsupported official document response"):
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


def test_run_manifest_commits_complete_observation_set_as_immutable_json() -> None:
    started = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    completed = datetime(2026, 9, 19, 12, 5, tzinfo=UTC)
    builder = AcquisitionRunManifestBuilder(
        source="scj",
        scope="principales-sentencias",
        storage_bucket="official-corpus",
        ingestion_id="run-001",
        batch_id="batch-001",
        partition_index=2,
        partition_count=4,
        certified_inventory_sha256="c" * 64,
        started_at=started,
    )
    uploaded_candidate = OfficialDocumentCandidate(
        source="supreme_court",
        source_identifier="principal:2025:001",
        discovery_url="https://official.example/principales",
        document_url="https://official.example/001.pdf",
        collection="principales-sentencias",
    )
    uploaded_content = b"%PDF principal"
    uploaded_sha = sha256_hex(uploaded_content)
    builder.record_artifact(
        StoredOfficialArtifact(
            candidate=uploaded_candidate,
            sha256=uploaded_sha,
            byte_count=len(uploaded_content),
            object_key=object_key_for(
                source="supreme_court",
                collection="principales-sentencias",
                sha256=uploaded_sha,
            ),
            already_present=False,
        )
    )
    existing_candidate = OfficialDocumentCandidate(
        source="supreme_court",
        source_identifier="principal:2024:002",
        discovery_url="https://official.example/principales",
        document_url="https://official.example/002.pdf",
        collection="principales-sentencias",
    )
    existing_sha = sha256_hex(b"%PDF existing")
    builder.record_existing(
        candidate=existing_candidate,
        sha256=existing_sha,
        object_key=object_key_for(
            source="supreme_court",
            collection="principales-sentencias",
            sha256=existing_sha,
        ),
    )
    failure = RuntimeError("publisher returned 503")
    builder.record_failure(
        collection="principales-sentencias",
        source_identifier="principal:2026:003",
        discovery_url="https://official.example/principales",
        document_url="https://official.example/003.pdf",
        error=failure,
    )

    store = MemoryObjectStore()
    stored = builder.commit(object_store=store, completed_at=completed)

    assert stored.object_key == (
        "_manifests/scj/principales-sentencias/2026/09/19/run-001.json"
    )
    assert stored.manifest.status == "partial"
    assert stored.manifest.discovered_count == 3
    assert stored.manifest.uploaded_count == 1
    assert stored.manifest.already_present_count == 1
    assert stored.manifest.failed_count == 1
    assert stored.manifest.unavailable_count == 0
    assert len(stored.manifest.source_inventory_sha256) == 64
    assert len(stored.manifest.artifact_set_sha256) == 64
    assert hashlib.sha256(store.objects[stored.object_key]).hexdigest() == stored.payload_sha256

    payload = json.loads(store.objects[stored.object_key])
    assert payload["schema_version"] == 3
    assert payload["ingestion_id"] == "run-001"
    assert payload["batch_id"] == "batch-001"
    assert payload["partition_index"] == 2
    assert payload["partition_count"] == 4
    assert payload["storage_bucket"] == "official-corpus"
    assert payload["certified_inventory_sha256"] == "c" * 64
    stored_item = next(item for item in payload["items"] if item["status"] == "uploaded")
    existing_item = next(
        item for item in payload["items"] if item["status"] == "already_present"
    )
    assert stored_item["verification_method"] == "downloaded_and_hashed"
    assert stored_item["content_type"] == "application/pdf"
    assert stored_item["file_extension"] == "pdf"
    assert existing_item["verification_method"] == "prior_manifest_and_head"
    assert existing_item["content_type"] == "application/pdf"
    assert existing_item["file_extension"] == "pdf"
    assert (
        f"s3://{payload['storage_bucket']}/{stored_item['object_key']}"
        == f"s3://official-corpus/{stored_item['object_key']}"
    )
    assert [item["status"] for item in payload["items"]] == [
        "already_present",
        "uploaded",
        "failed",
    ]


def test_run_manifest_refuses_overwrite_and_mutation_after_commit() -> None:
    builder = AcquisitionRunManifestBuilder(
        source="tc",
        scope="decisions",
        storage_bucket="official-corpus",
        ingestion_id="same-id",
        started_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
    )
    candidate = _candidate()
    sha = sha256_hex(b"%PDF first")
    builder.record_existing(
        candidate=candidate,
        sha256=sha,
        object_key=object_key_for(
            source="constitutional_court",
            collection="decisions",
            sha256=sha,
        ),
    )
    store = MemoryObjectStore()
    builder.commit(
        object_store=store,
        completed_at=datetime(2026, 9, 19, 12, 1, tzinfo=UTC),
    )

    with pytest.raises(RuntimeError, match="already committed"):
        builder.record_unavailable(
            collection="decisions",
            source_identifier="TC/9999/26",
            discovery_url="https://official.example/detail-9999",
        )

    collision = AcquisitionRunManifestBuilder(
        source="tc",
        scope="decisions",
        storage_bucket="official-corpus",
        ingestion_id="same-id",
        started_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
    )
    collision.record_existing(
        candidate=candidate,
        sha256=sha,
        object_key=object_key_for(
            source="constitutional_court",
            collection="decisions",
            sha256=sha,
        ),
    )
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        collision.commit(
            object_store=store,
            completed_at=datetime(2026, 9, 19, 12, 1, tzinfo=UTC),
        )


def test_run_manifest_digests_are_order_independent() -> None:
    completed = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
    first = AcquisitionRunManifestBuilder(
        source="scj",
        scope="decisions",
        storage_bucket="official-corpus",
        ingestion_id="first",
        started_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
    )
    second = AcquisitionRunManifestBuilder(
        source="scj",
        scope="decisions",
        storage_bucket="official-corpus",
        ingestion_id="second",
        started_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
    )
    candidates = (
        OfficialDocumentCandidate(
            source="supreme_court",
            source_identifier="a",
            discovery_url="https://official.example/list",
            document_url="https://official.example/a.pdf",
        ),
        OfficialDocumentCandidate(
            source="supreme_court",
            source_identifier="b",
            discovery_url="https://official.example/list",
            document_url="https://official.example/b.pdf",
        ),
    )
    for builder, ordered in ((first, candidates), (second, tuple(reversed(candidates)))):
        for candidate in ordered:
            digest = sha256_hex(("%PDF " + candidate.source_identifier).encode())
            builder.record_existing(
                candidate=candidate,
                sha256=digest,
                object_key=object_key_for(source="supreme_court", sha256=digest),
            )

    first_manifest = first.build(completed_at=completed)
    second_manifest = second.build(completed_at=completed)
    assert first_manifest.source_inventory_sha256 == second_manifest.source_inventory_sha256
    assert first_manifest.artifact_set_sha256 == second_manifest.artifact_set_sha256


def test_unavailable_source_item_does_not_make_successful_run_partial() -> None:
    builder = AcquisitionRunManifestBuilder(
        source="scj",
        scope="bulletins",
        storage_bucket="official-corpus",
        ingestion_id="run-unavailable",
        started_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
    )
    builder.record_unavailable(
        collection="bulletins",
        source_identifier="bulletin:2020:01",
        discovery_url="https://official.example/bulletins",
        error_type="UnsupportedOfficialDocumentResponse",
        reason="html_or_xml_response",
    )

    manifest = builder.build(
        completed_at=datetime(2026, 9, 19, 12, 1, tzinfo=UTC)
    )
    assert manifest.status == "succeeded"
    assert manifest.unavailable_count == 1
    assert manifest.failed_count == 0
    assert manifest.items[0].error_type == "UnsupportedOfficialDocumentResponse"
    assert manifest.items[0].error == "html_or_xml_response"


def test_run_manifest_rejects_invalid_partition_coordinates() -> None:
    with pytest.raises(ValueError, match="partition_index"):
        AcquisitionRunManifestBuilder(
            source="scj",
            scope="decisions",
            storage_bucket="official-corpus",
            ingestion_id="bad-partition",
            partition_index=4,
            partition_count=4,
        )


def test_stored_run_items_require_verification_method() -> None:
    from jurisnexo.acquisition.manifest import AcquisitionRunItem

    with pytest.raises(ValueError, match="verification_method"):
        AcquisitionRunItem(
            collection="decisions",
            source_identifier="x",
            discovery_url="https://official.example/list",
            document_url="https://official.example/x.pdf",
            status="already_present",
            sha256="a" * 64,
            object_key="jurisdictions/do/scj/decisions/aa/" + ("a" * 64) + ".pdf",
            content_type="application/pdf",
            file_extension="pdf",
        )


def test_run_manifest_rejects_invalid_certified_inventory_digest() -> None:
    with pytest.raises(ValueError, match="certified_inventory_sha256"):
        AcquisitionRunManifestBuilder(
            source="scj",
            scope="decisions",
            storage_bucket="official-corpus",
            certified_inventory_sha256="not-a-digest",
        )


def test_parse_canonical_run_manifest_round_trips() -> None:
    builder = AcquisitionRunManifestBuilder(
        source="tc",
        scope="decisions",
        storage_bucket="official-corpus",
        ingestion_id="parse-roundtrip",
        started_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
    )
    candidate = _candidate()
    sha = sha256_hex(b"%PDF roundtrip")
    builder.record_existing(
        candidate=candidate,
        sha256=sha,
        object_key=object_key_for(
            source="constitutional_court",
            collection="decisions",
            sha256=sha,
        ),
    )
    manifest = builder.build(
        completed_at=datetime(2026, 9, 19, 12, 1, tzinfo=UTC)
    )

    restored = parse_acquisition_run_manifest(manifest.canonical_bytes())

    assert restored == manifest
    assert restored.items[0].sha256 == sha


def test_parse_run_manifest_rejects_noncanonical_or_tampered_counts() -> None:
    builder = AcquisitionRunManifestBuilder(
        source="tc",
        scope="decisions",
        storage_bucket="official-corpus",
        ingestion_id="parse-invalid",
        started_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
    )
    candidate = _candidate()
    sha = sha256_hex(b"%PDF invalid")
    builder.record_existing(
        candidate=candidate,
        sha256=sha,
        object_key=object_key_for(
            source="constitutional_court",
            collection="decisions",
            sha256=sha,
        ),
    )
    manifest = builder.build(
        completed_at=datetime(2026, 9, 19, 12, 1, tzinfo=UTC)
    )
    noncanonical = json.dumps(
        json.loads(manifest.canonical_bytes()),
        indent=2,
    ).encode()
    with pytest.raises(ValueError, match="not canonical JSON"):
        parse_acquisition_run_manifest(noncanonical)

    tampered = json.loads(manifest.canonical_bytes())
    tampered["already_present_count"] = 0
    tampered_payload = (
        json.dumps(
            tampered,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    with pytest.raises(ValueError, match="status counts"):
        parse_acquisition_run_manifest(tampered_payload)


def test_parse_run_manifest_rejects_digest_tampering() -> None:
    builder = AcquisitionRunManifestBuilder(
        source="tc",
        scope="decisions",
        storage_bucket="official-corpus",
        ingestion_id="parse-digest-invalid",
        started_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
    )
    candidate = _candidate()
    sha = sha256_hex(b"%PDF digest")
    builder.record_existing(
        candidate=candidate,
        sha256=sha,
        object_key=object_key_for(
            source="constitutional_court",
            collection="decisions",
            sha256=sha,
        ),
    )
    manifest = builder.build(
        completed_at=datetime(2026, 9, 19, 12, 1, tzinfo=UTC)
    )
    tampered = json.loads(manifest.canonical_bytes())
    tampered["source_inventory_sha256"] = "0" * 64
    payload = (
        json.dumps(
            tampered,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()

    with pytest.raises(ValueError, match="source inventory digest"):
        parse_acquisition_run_manifest(payload)
