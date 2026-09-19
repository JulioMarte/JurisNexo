from __future__ import annotations

from typing import Protocol
from uuid import UUID

from jurisnexo.modules.acquisition.contracts import (
    AcquisitionRunRecord,
    AcquisitionTarget,
)


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


class AcquisitionLedger(Protocol):
    def claim_run(self, run_id: UUID) -> AcquisitionRunRecord: ...

    def pending_targets(self, run_id: UUID) -> tuple[AcquisitionTarget, ...]: ...

    def mark_item_started(self, item_id: UUID) -> None: ...

    def register_acquired_artifact(
        self,
        *,
        target: AcquisitionTarget,
        sha256: str,
        byte_size: int,
        object_key: str,
    ) -> UUID: ...

    def mark_item_failed(
        self,
        *,
        item_id: UUID,
        error_code: str,
        error_message: str,
    ) -> None: ...

    def finalize_run(self, run_id: UUID) -> AcquisitionRunRecord: ...
