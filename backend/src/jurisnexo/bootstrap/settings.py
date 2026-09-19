from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class PostgresSettings(BaseSettings):
    """Runtime PostgreSQL settings sourced from POSTGRES_* variables."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", extra="ignore")

    host: str
    port: int = 5432
    db: str
    user: str
    password: SecretStr
    sslmode: str = "require"


class RuntimeSettings(BaseSettings):
    """Process-level settings that are safe to consume only from composition roots."""

    model_config = SettingsConfigDict(env_prefix="JURISNEXO_", extra="ignore")

    environment: str = "development"
    api_title: str = "JurisNexo API"
    api_version: str = "0.1.0"


def build_postgres_sqlalchemy_url(settings: PostgresSettings) -> str:
    """Build the canonical SQLAlchemy/psycopg URL from POSTGRES_* settings.

    ``DATABASE_URL`` is therefore an optional compatibility override, not a
    required JurisNexo configuration value. SQLAlchemy's URL builder handles
    credentials containing URL-reserved characters without hand-rolled quoting.
    """

    return URL.create(
        drivername="postgresql+psycopg",
        username=settings.user,
        password=settings.password.get_secret_value(),
        host=settings.host,
        port=settings.port,
        database=settings.db,
        query={"sslmode": settings.sslmode},
    ).render_as_string(hide_password=False)


@lru_cache
def get_postgres_settings() -> PostgresSettings:
    return PostgresSettings()  # pyright: ignore[reportCallIssue]


@lru_cache
def get_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings()
