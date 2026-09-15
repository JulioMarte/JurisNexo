from __future__ import annotations

from fastapi import FastAPI

from jurisnexo.bootstrap.settings import RuntimeSettings, get_runtime_settings


def create_http_app(settings: RuntimeSettings | None = None) -> FastAPI:
    """Build the HTTP process at the composition root.

    Business routers are installed here as modules become API-capable. The
    composition root may know concrete adapters; business modules must not import
    back into bootstrap.
    """

    runtime = settings or get_runtime_settings()
    app = FastAPI(title=runtime.api_title, version=runtime.api_version)

    @app.get("/health/live", tags=["health"])
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def readiness() -> dict[str, str]:
        # Readiness will include DB/storage checks once those platform clients
        # are composed here. Keep this transport probe free of business logic.
        return {"status": "ready"}

    return app
