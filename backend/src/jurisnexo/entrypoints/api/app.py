from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="JurisNexo API", version="0.1.0")


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict[str, str]:
    # Database/storage/provider checks will be added as their runtime clients land.
    return {"status": "ready"}
