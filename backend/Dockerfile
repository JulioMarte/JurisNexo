FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.4 /uv /uvx /bin/

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock alembic.ini ./
COPY migrations ./migrations
COPY src ./src

FROM base AS runtime
RUN uv sync --frozen --no-dev \
    && uv pip install "boto3==1.43.93"
EXPOSE 8000
CMD ["uvicorn", "jurisnexo.entrypoints.http.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS test
ENV RUFF_CACHE_DIR=/tmp/ruff-cache
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY tests ./tests
# The SCJ Principales OCR benchmark workers under scripts/ import boto3, httpx,
# pillow and pypdfium2 at module scope, and their unit tests import those
# workers. These dependencies are benchmark-only and intentionally stay out of
# the slim uv.lock, matching the runtime stage's explicit boto3 install.
RUN uv sync --frozen --all-groups \
    && uv pip install \
        "boto3==1.43.93" \
        "httpx==0.28.1" \
        "pillow==12.3.0" \
        "pypdfium2==5.13.0"
CMD ["pytest", "-q"]
