from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from fastapi import FastAPI, Response, status
from pydantic import ValidationError

from jurisnexo.acquisition.http_fetcher import BoundedHttpFetcher, OFFICIAL_SOURCE_HOSTS
from jurisnexo.acquisition.s3_object_store import (
    S3ObjectStore,
    S3RuntimeSettings,
    build_s3_object_store,
)
from jurisnexo.bootstrap.settings import (
    RuntimeSettings,
    get_postgres_settings,
    get_runtime_settings,
)
from jurisnexo.modules.acquisition.adapters.db import PostgresAcquisitionLedger
from jurisnexo.modules.acquisition.api.router import create_acquisition_router
from jurisnexo.modules.source_catalog.adapters.db import PostgresSourceCatalog
from jurisnexo.modules.source_catalog.api.router import create_source_catalog_router
from jurisnexo.platform.db.connection import (
    ConnectionFactory,
    PostgresConnectionConfig,
    build_connection_factory,
    database_is_ready,
)
from jurisnexo.platform.http.errors import install_error_handlers
from jurisnexo.platform.http.middleware import install_correlation_middleware


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


def _default_connection_factory() -> ConnectionFactory:
    settings = get_postgres_settings()
    config = PostgresConnectionConfig(
        host=settings.host,
        port=settings.port,
        db=settings.db,
        user=settings.user,
        password=settings.password.get_secret_value(),
        sslmode=settings.sslmode,
    )
    return build_connection_factory(config)


def _configured_s3_settings() -> S3RuntimeSettings | None:
    try:
        return S3RuntimeSettings()  # pyright: ignore[reportCallIssue]
    except ValidationError:
        return None


def create_http_app(
    settings: RuntimeSettings | None = None,
    *,
    connection_factory: ConnectionFactory | None = None,
    s3_settings: S3RuntimeSettings | None = None,
    fetcher_factory: Callable[[], HttpFetcher] | None = None,
    object_store_factory: Callable[[], ObjectStore] | None = None,
) -> FastAPI:
    """Build the HTTP process and compose concrete infrastructure adapters."""

    runtime = settings or get_runtime_settings()
    connections = connection_factory or _default_connection_factory()
    resolved_s3 = s3_settings or _configured_s3_settings()

    app = FastAPI(title=runtime.api_title, version=runtime.api_version)
    install_correlation_middleware(app)
    install_error_handlers(app)

    source_catalog = PostgresSourceCatalog(connections)
    storage_bucket = resolved_s3.bucket if resolved_s3 is not None else "unconfigured"
    acquisition_ledger = PostgresAcquisitionLedger(
        connections,
        storage_bucket=storage_bucket,
    )

    if fetcher_factory is None:

        def configured_fetcher() -> BoundedHttpFetcher:
            return BoundedHttpFetcher(allowed_hosts=OFFICIAL_SOURCE_HOSTS)

        fetcher_factory = configured_fetcher

    if object_store_factory is None:

        def configured_object_store() -> S3ObjectStore:
            if resolved_s3 is None:
                raise RuntimeError("S3 runtime settings are not configured")
            return build_s3_object_store(resolved_s3)

        object_store_factory = configured_object_store

    app.include_router(create_source_catalog_router(source_catalog))
    app.include_router(
        create_acquisition_router(
            ledger=acquisition_ledger,
            fetcher_factory=fetcher_factory,
            object_store_factory=object_store_factory,
        )
    )

    @app.get("/health/live", tags=["health"], summary="Liveness probe")
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"], summary="Readiness probe")
    def readiness(response: Response) -> dict[str, object]:
        database_ready = database_is_ready(connections)
        storage_configured = resolved_s3 is not None
        ready = database_ready and storage_configured
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ready" if ready else "not_ready",
            "checks": {
                "database": "ready" if database_ready else "unavailable",
                "storage_configuration": (
                    "ready" if storage_configured else "unconfigured"
                ),
            },
        }

    return app
