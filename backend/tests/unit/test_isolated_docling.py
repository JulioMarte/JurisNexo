from __future__ import annotations

from jurisnexo.normalization.isolated_docling import (
    IsolatedDoclingStructuralNormalizer,
    sanitized_worker_environment,
)


def test_isolated_worker_environment_strips_authority_credentials() -> None:
    environment = {
        "PATH": "/usr/bin",
        "HOME": "/tmp/home",
        "DATABASE_URL": "postgresql://secret",
        "OPENROUTER_API_KEY": "secret",
        "JURISNEXO_S3_BUCKET": "bucket",
        "JURISNEXO_S3_ACCESS_KEY_ID": "key",
        "UNRELATED_SAFE_VALUE": "keep-me",
    }

    sanitized = sanitized_worker_environment(environment)

    assert sanitized["PATH"] == "/usr/bin"
    assert sanitized["HOME"] == "/tmp/home"
    assert sanitized["UNRELATED_SAFE_VALUE"] == "keep-me"
    assert "DATABASE_URL" not in sanitized
    assert "OPENROUTER_API_KEY" not in sanitized
    assert "JURISNEXO_S3_BUCKET" not in sanitized
    assert "JURISNEXO_S3_ACCESS_KEY_ID" not in sanitized


def test_isolated_worker_rejects_unbounded_inputs_before_spawning() -> None:
    normalizer = IsolatedDoclingStructuralNormalizer(max_source_bytes=4)
    try:
        normalizer.normalize(
            b"12345",
            inspection=type(
                "Inspection",
                (),
                {
                    "media_type": "application/pdf",
                    "detected_format": "application/pdf",
                },
            )(),
            filename="fixture.pdf",
        )
    except ValueError as exc:
        assert "source exceeds isolated worker limit" in str(exc)
    else:
        raise AssertionError("oversized source should fail before worker spawn")
