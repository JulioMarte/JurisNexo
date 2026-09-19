from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SourceRecord:
    id: UUID
    code: str
    name: str
    institution: str
    authority_class: str
    base_locator: str | None
    active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SourceCollectionRecord:
    id: UUID
    source_registry_id: UUID
    source_code: str
    code: str
    document_kind: str
    acquisition_policy: str
    agent_visibility: str
    active: bool
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SourceDocumentRecord:
    id: UUID
    source_registry_id: UUID
    source_code: str
    source_identifier: str
    source_collection: str
    document_kind: str
    discovery_url: str
    current_document_url: str | None
    artifact_availability: str
    acquired: bool
    first_seen_at: datetime
    last_seen_at: datetime
