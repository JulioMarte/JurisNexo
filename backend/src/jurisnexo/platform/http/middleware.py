from __future__ import annotations

import base64
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from jurisnexo.platform.http.errors import ApiError

CORRELATION_HEADER = "X-Correlation-ID"


def install_correlation_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get(CORRELATION_HEADER, "").strip()
        request_id = supplied if supplied and len(supplied) <= 128 else uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[CORRELATION_HEADER] = request_id
        return response


def encode_uuid_cursor(value: UUID) -> str:
    return base64.urlsafe_b64encode(value.bytes).decode("ascii").rstrip("=")


def decode_uuid_cursor(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        return UUID(bytes=raw)
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise ApiError(
            status_code=400,
            code="invalid_cursor",
            message="The pagination cursor is invalid.",
        ) from exc
