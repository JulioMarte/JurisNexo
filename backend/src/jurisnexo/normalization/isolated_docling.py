from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from jurisnexo.model_providers.contracts import JsonObject
from jurisnexo.normalization.contracts import FormatInspection, NormalizedDocument

_SENSITIVE_ENV_PREFIXES = (
    "OPENROUTER_",
    "JURISNEXO_S3_",
)
_SENSITIVE_ENV_NAMES = {
    "DATABASE_URL",
}


def sanitized_worker_environment(
    environment: dict[str, str],
) -> dict[str, str]:
    return {
        key: value
        for key, value in environment.items()
        if key not in _SENSITIVE_ENV_NAMES
        and not any(
            key.startswith(prefix)
            for prefix in _SENSITIVE_ENV_PREFIXES
        )
    }


@dataclass(slots=True)
class IsolatedDoclingStructuralNormalizer:
    timeout_seconds: float = 180.0
    max_source_bytes: int = 100 * 1024 * 1024
    max_output_bytes: int = 250 * 1024 * 1024
    ocr_language_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if self.max_source_bytes < 1 or self.max_output_bytes < 1:
            raise ValueError("worker byte limits must be positive")

    def normalize(
        self,
        source: bytes,
        inspection: FormatInspection,
        *,
        filename: str | None = None,
    ) -> NormalizedDocument:
        if len(source) > self.max_source_bytes:
            raise ValueError(
                f"source exceeds isolated worker limit: {len(source)} bytes"
            )

        with tempfile.TemporaryDirectory(prefix="jurisnexo-docling-") as temp:
            root = Path(temp)
            source_path = root / "source.bin"
            output_path = root / "normalized.json"
            metadata_path = root / "metadata.json"
            source_path.write_bytes(source)

            command = [
                sys.executable,
                "-m",
                "jurisnexo.normalization.docling_worker",
                "--input",
                str(source_path),
                "--output",
                str(output_path),
                "--metadata",
                str(metadata_path),
                "--filename",
                filename or "document.bin",
                "--media-type",
                inspection.media_type,
                "--detected-format",
                inspection.detected_format,
            ]
            for language in self.ocr_language_tags:
                command.extend(("--ocr-language", language))

            environment = sanitized_worker_environment(dict(os.environ))
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                    env=environment,
                )
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError(
                    f"Docling worker exceeded {self.timeout_seconds:g}s timeout"
                ) from exc

            if completed.returncode != 0:
                stderr = completed.stderr.decode(
                    "utf-8",
                    errors="replace",
                )[-4000:]
                raise RuntimeError(
                    "isolated Docling worker failed: " + stderr
                )
            if not output_path.exists() or not metadata_path.exists():
                raise RuntimeError(
                    "isolated Docling worker did not produce required outputs"
                )

            payload = output_path.read_bytes()
            if len(payload) > self.max_output_bytes:
                raise ValueError(
                    f"normalized output exceeds worker limit: {len(payload)} bytes"
                )

            loaded: object = json.loads(metadata_path.read_bytes())
            if not isinstance(loaded, dict):
                raise RuntimeError("worker metadata is not an object")
            metadata_raw = cast(dict[str, object], loaded)
            result_metadata = metadata_raw.get("metadata")
            metadata: JsonObject = (
                cast(JsonObject, result_metadata)
                if isinstance(result_metadata, dict)
                else {}
            )
            return NormalizedDocument(
                media_type=str(
                    metadata_raw.get(
                        "media_type",
                        "application/vnd.docling+json",
                    )
                ),
                payload=payload,
                engine=str(metadata_raw.get("engine", "docling")),
                engine_version=(
                    str(metadata_raw["engine_version"])
                    if metadata_raw.get("engine_version") is not None
                    else None
                ),
                metadata=metadata,
            )
