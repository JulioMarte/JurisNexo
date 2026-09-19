from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

Resolution = Literal["fix_request", "retry", "contact_operator"]


class ApiErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool
    resolution: Resolution
    details: dict[str, Any]
    request_id: str


class ApiErrorEnvelope(BaseModel):
    error: ApiErrorPayload


class ApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        resolution: Resolution = "fix_request",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code: int = status_code
        self.code: str = code
        self.message: str = message
        self.retryable: bool = retryable
        self.resolution: Resolution = resolution
        self.details: dict[str, Any] = details or {}


def request_id_for(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) and value else uuid4().hex


def _response(error: ApiError, request: Request) -> JSONResponse:
    payload = ApiErrorEnvelope(
        error=ApiErrorPayload(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            resolution=error.resolution,
            details=error.details,
            request_id=request_id_for(request),
        )
    )
    return JSONResponse(status_code=error.status_code, content=payload.model_dump(mode="json"))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _response(exc, request)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        error = ApiError(
            status_code=400,
            code="invalid_request",
            message="The request does not satisfy the API contract.",
            details={"errors": exc.errors()},
        )
        return _response(error, request)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Never serialize provider/SQL exception text across the HTTP boundary.
        del exc
        error = ApiError(
            status_code=500,
            code="internal_error",
            message="The server could not complete the request.",
            retryable=False,
            resolution="contact_operator",
        )
        return _response(error, request)
