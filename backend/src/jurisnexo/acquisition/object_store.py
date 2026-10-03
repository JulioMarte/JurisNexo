from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Provider-neutral identity of one stored object."""

    key: str
    size: int
    last_modified: float = 0.0


class ObjectNotFoundError(FileNotFoundError):
    """Raised by a store when the requested object key does not exist."""

    def __init__(self, key: str) -> None:
        super().__init__(f"object not found: {key}")
        self.key = key
