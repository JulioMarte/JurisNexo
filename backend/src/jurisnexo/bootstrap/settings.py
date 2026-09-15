from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_postgres_settings() -> PostgresSettings:
    return PostgresSettings()  # pyright: ignore[reportCallIssue]


@lru_cache
def get_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings()
