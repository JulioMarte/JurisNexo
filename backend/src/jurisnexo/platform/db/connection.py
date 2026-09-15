from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg

ConnectionFactory = Callable[[], psycopg.Connection[Any]]


@dataclass(frozen=True, slots=True)
class PostgresConnectionConfig:
    host: str
    port: int
    db: str
    user: str
    password: str
    sslmode: str = "require"
    connect_timeout_seconds: int = 10

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("PostgreSQL host must not be empty")
        if not self.db.strip():
            raise ValueError("PostgreSQL database must not be empty")
        if not self.user.strip():
            raise ValueError("PostgreSQL user must not be empty")
        if self.port <= 0 or self.port > 65535:
            raise ValueError("PostgreSQL port must be between 1 and 65535")
        if self.connect_timeout_seconds <= 0:
            raise ValueError("PostgreSQL connect timeout must be positive")


def build_connection_factory(config: PostgresConnectionConfig) -> ConnectionFactory:
    """Return short-lived autocommit connections for request/application adapters.

    Business commands still open explicit ``connection.transaction()`` blocks when
    atomic mutation is required. Autocommit prevents an innocent read from leaving
    a transaction open while acquisition performs HTTP or S3 network I/O.
    """

    def open_connection() -> psycopg.Connection[Any]:
        return psycopg.connect(
            host=config.host,
            port=config.port,
            dbname=config.db,
            user=config.user,
            password=config.password,
            sslmode=config.sslmode,
            connect_timeout=config.connect_timeout_seconds,
            autocommit=True,
        )

    return open_connection


def database_is_ready(connection_factory: ConnectionFactory) -> bool:
    try:
        with connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)
    except psycopg.Error:
        return False
