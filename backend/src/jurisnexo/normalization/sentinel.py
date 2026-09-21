from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SentinelCandidate:
    source_artifact_id: str
    page_id: str
    stratum: str


def select_sentinel_sample(
    candidates: tuple[SentinelCandidate, ...],
    *,
    rate: float,
    seed: str,
) -> tuple[SentinelCandidate, ...]:
    if not 0 <= rate <= 1:
        raise ValueError("rate must be between 0 and 1")
    selected: list[SentinelCandidate] = []
    threshold = int(rate * (2**256 - 1))
    for item in candidates:
        material = (
            f"{seed}\n{item.stratum}\n{item.source_artifact_id}\n{item.page_id}".encode()
        )
        value = int.from_bytes(hashlib.sha256(material).digest(), "big")
        if value <= threshold:
            selected.append(item)
    return tuple(
        sorted(
            selected,
            key=lambda item: (item.stratum, item.source_artifact_id, item.page_id),
        )
    )
