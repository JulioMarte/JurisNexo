FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY src ./src

FROM base AS runtime
RUN uv sync --no-dev
EXPOSE 8000
CMD ["uvicorn", "jurisnexo.entrypoints.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS test
COPY tests ./tests
RUN uv sync --all-groups
CMD ["pytest", "-q"]
