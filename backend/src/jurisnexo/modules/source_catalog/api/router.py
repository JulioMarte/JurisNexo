from __future__ import annotations

from typing import Literal, TypeVar
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field

from jurisnexo.modules.source_catalog.adapters.db import PostgresSourceCatalog
from jurisnexo.modules.source_catalog.contracts import (
    SourceCollectionRecord,
    SourceDocumentRecord,
    SourceRecord,
)
from jurisnexo.platform.http.errors import ApiError
from jurisnexo.platform.http.middleware import decode_uuid_cursor, encode_uuid_cursor

T = TypeVar("T")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceCreate(StrictModel):
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=300)
    institution: str = Field(min_length=1, max_length=300)
    authority_class: Literal[
        "official_primary", "official_secondary", "trusted_mirror", "manual_import"
    ]
    base_locator: str | None = None
    active: bool = True


class SourceActiveCommand(StrictModel):
    active: bool


class CollectionCreate(StrictModel):
    source_id: UUID
    code: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
    )
    document_kind: str = Field(min_length=1, max_length=100)
    acquisition_policy: Literal["enabled", "catalog_only", "paused", "blocked"] = (
        "catalog_only"
    )
    agent_visibility: Literal["hidden", "discoverable", "searchable"] = "hidden"
    active: bool = True


class CollectionPolicyCommand(StrictModel):
    acquisition_policy: Literal["enabled", "catalog_only", "paused", "blocked"]
    agent_visibility: Literal["hidden", "discoverable", "searchable"]
    active: bool
    expected_revision: int = Field(gt=0)


class SourceView(StrictModel):
    id: UUID
    code: str
    name: str
    institution: str
    authority_class: str
    base_locator: str | None
    active: bool


class CollectionView(StrictModel):
    id: UUID
    source_registry_id: UUID
    source_code: str
    code: str
    document_kind: str
    acquisition_policy: str
    agent_visibility: str
    active: bool
    revision: int


class SourceDocumentView(StrictModel):
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


class SourcePage(StrictModel):
    data: list[SourceView]
    next_cursor: str | None = None
    has_more: bool


class CollectionPage(StrictModel):
    data: list[CollectionView]
    next_cursor: str | None = None
    has_more: bool


class SourceDocumentPage(StrictModel):
    data: list[SourceDocumentView]
    next_cursor: str | None = None
    has_more: bool


def _source_view(value: SourceRecord) -> SourceView:
    return SourceView(**{field: getattr(value, field) for field in SourceView.model_fields})


def _collection_view(value: SourceCollectionRecord) -> CollectionView:
    return CollectionView(
        **{field: getattr(value, field) for field in CollectionView.model_fields}
    )


def _document_view(value: SourceDocumentRecord) -> SourceDocumentView:
    return SourceDocumentView(
        **{field: getattr(value, field) for field in SourceDocumentView.model_fields}
    )


def _page(records: tuple[T, ...], limit: int) -> tuple[tuple[T, ...], str | None, bool]:
    has_more = len(records) > limit
    visible = records[:limit]
    next_cursor = None
    if has_more and visible:
        record_id = getattr(visible[-1], "id")
        if not isinstance(record_id, UUID):
            raise TypeError("paginated records must expose a UUID id")
        next_cursor = encode_uuid_cursor(record_id)
    return visible, next_cursor, has_more


def create_source_catalog_router(catalog: PostgresSourceCatalog) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["source-catalog"])

    @router.get("/sources", response_model=SourcePage, summary="List source registries")
    def list_sources(
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> SourcePage:
        records = catalog.list_sources(after_id=decode_uuid_cursor(cursor), limit=limit + 1)
        visible, next_cursor, has_more = _page(records, limit)
        return SourcePage(
            data=[_source_view(record) for record in visible],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    @router.post(
        "/sources",
        response_model=SourceView,
        status_code=status.HTTP_201_CREATED,
        summary="Register a source",
    )
    def create_source(body: SourceCreate) -> SourceView:
        try:
            record = catalog.create_source(**body.model_dump())
        except ValueError as exc:
            if str(exc) == "source_code_exists":
                raise ApiError(
                    status_code=409,
                    code="source_code_conflict",
                    message="A source with that code already exists.",
                    details={"code": body.code},
                ) from exc
            raise
        return _source_view(record)

    @router.post(
        "/sources/{source_id}:set-active",
        response_model=SourceView,
        summary="Enable or disable a source",
    )
    def set_source_active(source_id: UUID, body: SourceActiveCommand) -> SourceView:
        try:
            return _source_view(
                catalog.set_source_active(source_id=source_id, active=body.active)
            )
        except LookupError as exc:
            raise ApiError(
                status_code=404,
                code="source_not_found",
                message="The source does not exist.",
                details={"source_id": str(source_id)},
            ) from exc

    @router.get(
        "/source-collections",
        response_model=CollectionPage,
        summary="List source collections",
    )
    def list_collections(
        source_id: UUID | None = None,
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> CollectionPage:
        records = catalog.list_collections(
            source_id=source_id,
            after_id=decode_uuid_cursor(cursor),
            limit=limit + 1,
        )
        visible, next_cursor, has_more = _page(records, limit)
        return CollectionPage(
            data=[_collection_view(record) for record in visible],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    @router.post(
        "/source-collections",
        response_model=CollectionView,
        status_code=status.HTTP_201_CREATED,
        summary="Create a source collection policy",
    )
    def create_collection(body: CollectionCreate) -> CollectionView:
        try:
            return _collection_view(catalog.create_collection(**body.model_dump()))
        except LookupError as exc:
            raise ApiError(
                status_code=404,
                code="source_not_found",
                message="The source does not exist.",
                details={"source_id": str(body.source_id)},
            ) from exc
        except ValueError as exc:
            if str(exc) == "source_collection_exists":
                raise ApiError(
                    status_code=409,
                    code="source_collection_conflict",
                    message="That collection already exists for the source.",
                    details={"source_id": str(body.source_id), "code": body.code},
                ) from exc
            raise

    @router.post(
        "/source-collections/{collection_id}:set-policy",
        response_model=CollectionView,
        summary="Set acquisition and visibility policy",
    )
    def set_collection_policy(
        collection_id: UUID, body: CollectionPolicyCommand
    ) -> CollectionView:
        try:
            return _collection_view(
                catalog.set_collection_policy(
                    collection_id=collection_id,
                    **body.model_dump(),
                )
            )
        except LookupError as exc:
            raise ApiError(
                status_code=404,
                code="source_collection_not_found",
                message="The source collection does not exist.",
                details={"collection_id": str(collection_id)},
            ) from exc
        except ValueError as exc:
            text = str(exc)
            if text.startswith("revision_conflict:"):
                current = int(text.split(":", 1)[1])
                raise ApiError(
                    status_code=409,
                    code="revision_conflict",
                    message="The source collection policy changed since it was read.",
                    details={
                        "collection_id": str(collection_id),
                        "expected_revision": body.expected_revision,
                        "current_revision": current,
                    },
                ) from exc
            raise

    @router.get(
        "/source-documents",
        response_model=SourceDocumentPage,
        summary="List discovered source documents",
    )
    def list_source_documents(
        source_id: UUID | None = None,
        source_collection: str | None = None,
        artifact_availability: Literal[
            "available", "not_published", "unavailable", "unknown"
        ]
        | None = None,
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> SourceDocumentPage:
        records = catalog.list_documents(
            source_id=source_id,
            collection=source_collection,
            availability=artifact_availability,
            after_id=decode_uuid_cursor(cursor),
            limit=limit + 1,
        )
        visible, next_cursor, has_more = _page(records, limit)
        return SourceDocumentPage(
            data=[_document_view(record) for record in visible],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    return router
