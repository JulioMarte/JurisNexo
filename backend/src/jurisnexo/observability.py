from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

_TRACER = trace.get_tracer("jurisnexo.acquisition")


@contextmanager
def acquisition_span(name: str, **attributes: Any) -> Generator[Span, None, None]:
    """Create an OpenTelemetry acquisition span without choosing an exporter.

    JurisNexo's core only depends on the OpenTelemetry API. The runtime (for example the live
    GitHub Actions backfill) installs/configures the SDK and exporter. This keeps acquisition
    code observable without coupling durable pipeline logic to a telemetry vendor.
    """

    with _TRACER.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def span_event(name: str, **attributes: Any) -> None:
    trace.get_current_span().add_event(
        name,
        attributes={key: value for key, value in attributes.items() if value is not None},
    )
