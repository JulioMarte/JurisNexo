from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AcquisitionRunRecord:
    id: UUID
    source_collection_id: UUID
    source_code: str
    collection_code: str
    status: str
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    selected_count: int
    acquired_count: int
    already_present_count: int
    failed_count: int


@dataclass(frozen=True, slots=True)
class AcquisitionRunItemRecord:
    id: UUID
    run_id: UUID
    source_document_id: UUID
    source_identifier: str
    status: str
    artifact_id: UUID | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class AcquisitionTarget:
    item_id: UUID
    run_id: UUID
    source_document_id: UUID
    source_registry_id: UUID
    source_code: str
    source_identifier: str
    source_collection: str
    discovery_url: str
    document_url: str


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    id: UUID
    source_registry_id: UUID | None
    source_code: str | None
    sha256: str
    mime_type: str
    byte_size: int
    parser_status: str
    storage_locator: str | None
    acquired_at: datetime
