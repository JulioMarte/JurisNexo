from __future__ import annotations

from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field

from jurisnexo.modules.acquisition.adapters.db import PostgresAcquisitionLedger
from jurisnexo.modules.acquisition.application.execute import execute_acquisition_run
from jurisnexo.modules.acquisition.contracts import (
    AcquisitionRunItemRecord,
    AcquisitionRunRecord,
    ArtifactRecord,
)
from jurisnexo.platform.http.errors import ApiError
from jurisnexo.platform.http.middleware import decode_uuid_cursor, encode_uuid_cursor


class HttpFetcher(Protocol):
    def get_bytes(self, url: str) -> bytes: ...


class ObjectStore(Protocol):
    def exists(self, key: str) -> bool: ...

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None: ...


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AcquisitionRunCreate(StrictModel):
    source_collection_id: UUID
    source_document_ids: list[UUID] | None = Field(default=None, max_length=500)
    limit: int = Field(default=100, ge=1, le=500)


class AcquisitionRunView(StrictModel):
    id: UUID
    source_collection_id: UUID
    source_code: str
    collection_code: str
    status: str
    selected_count: int
    acquired_count: int
    already_present_count: int
    failed_count: int


class AcquisitionRunItemView(StrictModel):
    id: UUID
    run_id: UUID
    source_document_id: UUID
    source_identifier: str
    status: str
    artifact_id: UUID | None
    error_code: str | None
    error_message: str | None


class ArtifactView(StrictModel):
    id: UUID
    source_registry_id: UUID | None
    source_code: str | None
    sha256: str
    mime_type: str
    byte_size: int
    parser_status: str
    storage_locator: str | None


class AcquisitionRunPage(StrictModel):
    data: list[AcquisitionRunView]
    next_cursor: str | None = None
    has_more: bool


class AcquisitionRunItemPage(StrictModel):
    data: list[AcquisitionRunItemView]
    next_cursor: str | None = None
    has_more: bool


class ArtifactPage(StrictModel):
    data: list[ArtifactView]
    next_cursor: str | None = None
    has_more: bool


def _run_view(value: AcquisitionRunRecord) -> AcquisitionRunView:
    return AcquisitionRunView(
        **{field: getattr(value, field) for field in AcquisitionRunView.model_fields}
    )


def _item_view(value: AcquisitionRunItemRecord) -> AcquisitionRunItemView:
    return AcquisitionRunItemView(
        **{field: getattr(value, field) for field in AcquisitionRunItemView.model_fields}
    )


def _artifact_view(value: ArtifactRecord) -> ArtifactView:
    return ArtifactView(**{field: getattr(value, field) for field in ArtifactView.model_fields})


def create_acquisition_router(
    *,
    ledger: PostgresAcquisitionLedger,
    fetcher_factory: Callable[[], HttpFetcher],
    object_store_factory: Callable[[], ObjectStore],
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["acquisition"])

    @router.post(
        "/acquisition-runs",
        response_model=AcquisitionRunView,
        status_code=status.HTTP_201_CREATED,
        summary="Create an acquisition run",
    )
    def create_run(body: AcquisitionRunCreate) -> AcquisitionRunView:
        try:
            record = ledger.create_run(
                source_collection_id=body.source_collection_id,
                source_document_ids=(
                    tuple(body.source_document_ids) if body.source_document_ids else None
                ),
                limit=body.limit,
            )
        except LookupError as exc:
            raise ApiError(
                status_code=404,
                code="source_collection_not_found",
                message="The source collection does not exist.",
                details={"source_collection_id": str(body.source_collection_id)},
            ) from exc
        except ValueError as exc:
            reason = str(exc)
            if reason.startswith("acquisition_policy:"):
                policy = reason.split(":", 1)[1]
                raise ApiError(
                    status_code=409,
                    code="acquisition_policy_blocks_run",
                    message="The collection policy does not allow acquisition.",
                    details={"acquisition_policy": policy},
                ) from exc
            codes = {
                "source_collection_inactive": "The source collection is inactive.",
                "source_documents_not_eligible": (
                    "One or more requested documents are outside this collection or not available."
                ),
                "no_acquirable_documents": "No eligible source documents were found.",
            }
            if reason in codes:
                raise ApiError(
                    status_code=409,
                    code=reason,
                    message=codes[reason],
                ) from exc
            raise
        return _run_view(record)

    @router.get(
        "/acquisition-runs",
        response_model=AcquisitionRunPage,
        summary="List acquisition runs",
    )
    def list_runs(
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> AcquisitionRunPage:
        records = ledger.list_runs(after_id=decode_uuid_cursor(cursor), limit=limit + 1)
        has_more = len(records) > limit
        visible = records[:limit]
        return AcquisitionRunPage(
            data=[_run_view(record) for record in visible],
            next_cursor=(
                encode_uuid_cursor(visible[-1].id) if has_more and visible else None
            ),
            has_more=has_more,
        )

    @router.get(
        "/acquisition-runs/{run_id}",
        response_model=AcquisitionRunView,
        summary="Get an acquisition run",
    )
    def get_run(run_id: UUID) -> AcquisitionRunView:
        try:
            return _run_view(ledger.get_run(run_id))
        except LookupError as exc:
            raise ApiError(
                status_code=404,
                code="acquisition_run_not_found",
                message="The acquisition run does not exist.",
                details={"run_id": str(run_id)},
            ) from exc

    @router.get(
        "/acquisition-runs/{run_id}/items",
        response_model=AcquisitionRunItemPage,
        summary="List acquisition run items",
    )
    def list_run_items(
        run_id: UUID,
        cursor: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> AcquisitionRunItemPage:
        try:
            records = ledger.list_run_items(
                run_id=run_id,
                after_id=decode_uuid_cursor(cursor),
                limit=limit + 1,
            )
        except LookupError as exc:
            raise ApiError(
                status_code=404,
                code="acquisition_run_not_found",
                message="The acquisition run does not exist.",
                details={"run_id": str(run_id)},
            ) from exc
        has_more = len(records) > limit
        visible = records[:limit]
        return AcquisitionRunItemPage(
            data=[_item_view(record) for record in visible],
            next_cursor=(
                encode_uuid_cursor(visible[-1].id) if has_more and visible else None
            ),
            has_more=has_more,
        )

    @router.post(
        "/acquisition-runs/{run_id}:execute",
        response_model=AcquisitionRunView,
        summary="Execute a queued acquisition run",
    )
    def execute_run(run_id: UUID) -> AcquisitionRunView:
        try:
            fetcher = fetcher_factory()
            object_store = object_store_factory()
            result = execute_acquisition_run(
                run_id=run_id,
                ledger=ledger,
                fetcher=fetcher,
                object_store=object_store,
            )
        except LookupError as exc:
            raise ApiError(
                status_code=404,
                code="acquisition_run_not_found",
                message="The acquisition run does not exist.",
                details={"run_id": str(run_id)},
            ) from exc
        except ValueError as exc:
            reason = str(exc)
            if reason.startswith("acquisition_run_not_queued:"):
                current = reason.split(":", 1)[1]
                raise ApiError(
                    status_code=409,
                    code="acquisition_run_state_conflict",
                    message="Only queued acquisition runs can be executed.",
                    details={"run_id": str(run_id), "current_status": current},
                ) from exc
            raise
        except RuntimeError as exc:
            raise ApiError(
                status_code=503,
                code="acquisition_runtime_unavailable",
                message="The acquisition runtime is not available.",
                retryable=True,
                resolution="retry",
            ) from exc
        return _run_view(result)

    @router.get("/artifacts", response_model=ArtifactPage, summary="List acquired artifacts")
    def list_artifacts(
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> ArtifactPage:
        records = ledger.list_artifacts(after_id=decode_uuid_cursor(cursor), limit=limit + 1)
        has_more = len(records) > limit
        visible = records[:limit]
        return ArtifactPage(
            data=[_artifact_view(record) for record in visible],
            next_cursor=(
                encode_uuid_cursor(visible[-1].id) if has_more and visible else None
            ),
            has_more=has_more,
        )

    return router
