from __future__ import annotations

from pydantic import SecretStr

from jurisnexo.bootstrap.settings import PostgresSettings, build_postgres_sqlalchemy_url


def test_build_postgres_sqlalchemy_url_from_component_settings() -> None:
    settings = PostgresSettings(
        host="db.example.internal",
        port=6543,
        db="jurisnexo_dev",
        user="jurisnexo_app",
        password=SecretStr("p@ss/word:with?reserved"),
        sslmode="require",
    )

    url = build_postgres_sqlalchemy_url(settings)

    assert url == (
        "postgresql+psycopg://jurisnexo_app:p%40ss%2Fword%3Awith%3Freserved"
        "@db.example.internal:6543/jurisnexo_dev?sslmode=require"
    )
    assert "p@ss/word" not in url
