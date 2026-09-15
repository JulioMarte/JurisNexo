from __future__ import annotations

import argparse
import json

from jurisnexo.bootstrap.settings import get_postgres_settings
from jurisnexo.modules.legal_reference.bootstrap import (
    apply_database_bootstrap,
    verify_database_bootstrap,
)
from jurisnexo.platform.db.connection import PostgresConnectionConfig, build_connection_factory


def _connection_factory():  # pyright: ignore[reportUnknownParameterType,reportMissingParameterType]
    settings = get_postgres_settings()
    return build_connection_factory(
        PostgresConnectionConfig(
            host=settings.host,
            port=settings.port,
            db=settings.db,
            user=settings.user,
            password=settings.password.get_secret_value(),
            sslmode=settings.sslmode,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply or verify the JurisNexo legal-system database bootstrap."
    )
    parser.add_argument(
        "command",
        choices=("apply", "verify"),
        nargs="?",
        default="apply",
    )
    args = parser.parse_args()

    connection_factory = _connection_factory()
    if args.command == "apply":
        apply_database_bootstrap(connection_factory)
    result = verify_database_bootstrap(connection_factory)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
