from __future__ import annotations

import hashlib
import re
from typing import Protocol
from uuid import UUID

from jurisnexo.modules.acquisition.adapters.db import PostgresAcquisitionLedger
from jurisnexo.modules.acquisition.contracts import AcquisitionRunRecord

_SOURCE_STORAGE_CODES = {
    "supreme_court": "scj",
    "constitutional_court": "tc",
}
_STORAGE_SEGMENT = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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


def storage_key_for(*, source_code: str, collection: str, sha256: str) -> str:
    if len(sha256) != 64 or any(
        character not in "0123456789abcdef" for character in sha256
    ):
        raise ValueError("sha256 must be a lowercase 64-character hexadecimal digest")
    source_segment = _SOURCE_STORAGE_CODES.get(source_code, source_code.replace("_", "-"))
    if not _STORAGE_SEGMENT.fullmatch(source_segment):
        raise ValueError("source code cannot be mapped to a safe storage segment")
    if not _STORAGE_SEGMENT.fullmatch(collection):
        raise ValueError("collection must be lowercase kebab-case")
    return (
        f"jurisdictions/do/{source_segment}/{collection}/"
        f"{sha256[:2]}/{sha256}.pdf"
    )


def _safe_failure(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, ValueError):
        return (
            "invalid_source_artifact",
            "The source returned bytes that failed acquisition validation.",
        )
    return "acquisition_failed", f"Acquisition failed ({type(exc).__name__})."


def execute_acquisition_run(
    *,
    run_id: UUID,
    ledger: PostgresAcquisitionLedger,
    fetcher: HttpFetcher,
    object_store: ObjectStore,
) -> AcquisitionRunRecord:
    """Execute one durable run without holding a database transaction over network I/O."""

    ledger.claim_run(run_id)
    targets = ledger.pending_targets(run_id)
    for target in targets:
        ledger.mark_item_started(target.item_id)
        try:
            content = fetcher.get_bytes(target.document_url)
            if not content.startswith(b"%PDF"):
                raise ValueError("official source artifact is not a PDF")
            digest = hashlib.sha256(content).hexdigest()
            object_key = storage_key_for(
                source_code=target.source_code,
                collection=target.source_collection,
                sha256=digest,
            )
            already_stored = object_store.exists(object_key)
            if not already_stored:
                object_store.put(
                    key=object_key,
                    content=content,
                    content_type="application/pdf",
                    metadata={
                        "source": target.source_code,
                        "collection": target.source_collection,
                        "source_identifier": target.source_identifier,
                        "source_url": target.document_url,
                        "sha256": digest,
                    },
                )
            ledger.register_acquired_artifact(
                target=target,
                sha256=digest,
                byte_size=len(content),
                object_key=object_key,
            )
        except Exception as exc:
            # One malformed or unavailable source record should be represented as
            # an item failure instead of erasing the rest of the durable run.
            error_code, error_message = _safe_failure(exc)
            ledger.mark_item_failed(
                item_id=target.item_id,
                error_code=error_code,
                error_message=error_message,
            )

    return ledger.finalize_run(run_id)
