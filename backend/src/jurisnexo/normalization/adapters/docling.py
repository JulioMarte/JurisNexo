from __future__ import annotations

import importlib
import io
import json
from dataclasses import dataclass
from typing import Any

from jurisnexo.normalization.contracts import FormatInspection, NormalizedDocument


@dataclass(slots=True)
class DoclingStructuralNormalizer:
    """Docling v2 adapter using an in-memory DocumentStream.

    Imports are dynamic so ordinary JurisNexo runtime/CI does not need the
    heavyweight normalization dependency unless this adapter is selected.
    """

    def normalize(
        self,
        source: bytes,
        inspection: FormatInspection,
        *,
        filename: str | None = None,
    ) -> NormalizedDocument:
        del inspection
        try:
            converter_module = importlib.import_module("docling.document_converter")
            base_models = importlib.import_module("docling.datamodel.base_models")
            docling_package = importlib.import_module("docling")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Docling is required for structural normalization; install the normalization group"
            ) from exc

        converter_cls: Any = converter_module.DocumentConverter
        stream_cls: Any = base_models.DocumentStream
        converter = converter_cls()
        stream = stream_cls(name=filename or "document.bin", stream=io.BytesIO(source))
        result: Any = converter.convert(stream)
        exported: dict[str, Any] = result.document.export_to_dict()
        payload = json.dumps(
            exported,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        version = getattr(docling_package, "__version__", None)
        return NormalizedDocument(
            media_type="application/vnd.docling+json",
            payload=payload,
            engine="docling",
            engine_version=str(version) if version is not None else None,
            metadata={"schema": "DoclingDocument-v2"},
        )
