from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FailureClass = Literal[
    "permanent_document",
    "quality_review",
    "retryable_infrastructure",
    "systemic",
]


@dataclass(frozen=True, slots=True)
class NormalizationFailure:
    failure_class: FailureClass
    code: str
    retryable: bool
    detail: str


def classify_normalization_error(exc: Exception) -> NormalizationFailure:
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    haystack = f"{name} {message}"

    if any(token in haystack for token in ("unsupported", "encrypted", "corrupt")):
        return NormalizationFailure(
            "permanent_document", type(exc).__name__, False, str(exc)[:1000]
        )
    if any(token in haystack for token in ("quality_review", "unresolved", "poor ocr")):
        return NormalizationFailure(
            "quality_review", type(exc).__name__, False, str(exc)[:1000]
        )
    if any(
        token in haystack
        for token in ("429", "rate limit", "timeout", "temporar", "connection reset", "503")
    ):
        return NormalizationFailure(
            "retryable_infrastructure", type(exc).__name__, True, str(exc)[:1000]
        )
    return NormalizationFailure("systemic", type(exc).__name__, False, str(exc)[:1000])


@dataclass(slots=True)
class CircuitBreaker:
    threshold: int = 5
    consecutive_systemic_failures: int = 0
    open: bool = False

    def __post_init__(self) -> None:
        if self.threshold < 1:
            raise ValueError("threshold must be at least 1")

    def record_success(self) -> None:
        self.consecutive_systemic_failures = 0

    def record_failure(self, failure: NormalizationFailure) -> None:
        if failure.failure_class != "systemic":
            return
        self.consecutive_systemic_failures += 1
        if self.consecutive_systemic_failures >= self.threshold:
            self.open = True

    def ensure_closed(self) -> None:
        if self.open:
            raise RuntimeError("normalization circuit breaker is open")
