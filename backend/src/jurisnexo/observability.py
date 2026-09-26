from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

_ACQUISITION_TRACER = trace.get_tracer("jurisnexo.acquisition")
_NORMALIZATION_TRACER = trace.get_tracer("jurisnexo.normalization")


@contextmanager
def _span(
    tracer: trace.Tracer,
    name: str,
    **attributes: Any,
) -> Generator[Span]:
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


@contextmanager
def acquisition_span(name: str, **attributes: Any) -> Generator[Span]:
    """Create an acquisition span without choosing an exporter."""

    with _span(_ACQUISITION_TRACER, name, **attributes) as span:
        yield span


@contextmanager
def normalization_span(name: str, **attributes: Any) -> Generator[Span]:
    """Create a normalization span without coupling the core to a vendor."""

    with _span(_NORMALIZATION_TRACER, name, **attributes) as span:
        yield span


def span_event(name: str, **attributes: Any) -> None:
    trace.get_current_span().add_event(
        name,
        attributes={
            key: value
            for key, value in attributes.items()
            if value is not None
        },
    )


def normalization_event(name: str, **attributes: Any) -> None:
    """Emit an event on the active normalization span when tracing is enabled."""

    span_event(name, **attributes)
