"""Filesystem-backed object store mirroring object-store keys under one root.

The local store is a first-class alternative to the S3-compatible store used by
the SCJ Principales OCR benchmark workers. It reads and writes objects by the
same key layout the durable store uses, so a local bucket snapshot can replace
network calls during tests and development while preserving source identity and
the immutable evidence contract.

Immutability is enforced from the object bytes themselves: ``head_metadata``
computes the payload SHA-256 of the stored file, so a later ``put`` of different
bytes for the same key is rejected exactly as the S3 store rejects a metadata
mismatch.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from jurisnexo.acquisition.object_store import ObjectNotFoundError, StoredObject


@dataclass(slots=True)
class LocalObjectStore:
    """Object store over a directory that mirrors bucket keys."""

    root: Path

    def __post_init__(self) -> None:
        resolved = self.root.expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"local object root is not a directory: {resolved}")
        self.root = resolved

    def _path(self, key: str) -> Path:
        parts = key.split("/")
        if not key or key.startswith("/") or key.endswith("/"):
            raise ValueError(f"invalid object key: {key!r}")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError(f"invalid object key: {key!r}")
        return self.root.joinpath(*parts)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        return path.read_bytes()

    def head_metadata(self, key: str) -> dict[str, str] | None:
        path = self._path(key)
        if not path.is_file():
            return None
        return {"payload-sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        del content_type, metadata
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def list_objects(self, prefix: str) -> list[StoredObject]:
        clean = prefix.strip("/")
        base = self.root if not clean else self.root.joinpath(*clean.split("/"))
        if not base.is_dir():
            return []
        out: list[StoredObject] = []
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            key = path.relative_to(self.root).as_posix()
            if clean and not key.startswith(f"{clean}/"):
                continue
            stat = path.stat()
            out.append(
                StoredObject(
                    key=key,
                    size=stat.st_size,
                    last_modified=stat.st_mtime,
                )
            )
        out.sort(key=lambda item: item.key)
        return out
