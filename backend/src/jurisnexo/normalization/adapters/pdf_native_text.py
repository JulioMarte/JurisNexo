from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any

from jurisnexo.normalization.contracts import FormatInspection
from jurisnexo.normalization.gold import assess_reference_text_health
from jurisnexo.normalization.source_fidelity import SourceTextReference

DEFAULT_PDF_NATIVE_MOJIBAKE_MARKERS = frozenset(
    {"⁄", "˙", "Û", "Ì", "È", "Ò", "Ø", "œ", "Æ", "æ"}
)


def _default_suspicious_characters() -> frozenset[str]:
    return DEFAULT_PDF_NATIVE_MOJIBAKE_MARKERS


@dataclass(slots=True)
class PdfNativeTextReferenceExtractor:
    """Extract the PDF text layer as a secondary fidelity authority.

    This adapter is intentionally optional and imports pypdfium2 lazily so the
    core backend does not require the normalization runtime dependency. The
    default risk markers are conservative legacy-encoding signals; they only
    make the reference non-authoritative when the configured count/rate gates
    are exceeded.
    """

    suspicious_characters: frozenset[str] = field(
        default_factory=_default_suspicious_characters
    )
    minimum_suspicious_count: int = 3
    maximum_suspicious_rate: float = 0.002
    minimum_characters: int = 200

    def extract(
        self,
        source: bytes,
        inspection: FormatInspection,
    ) -> SourceTextReference | None:
        if inspection.media_type != "application/pdf":
            return None
        pdfium: Any = importlib.import_module("pypdfium2")
        document = pdfium.PdfDocument(source)
        try:
            parts: list[str] = []
            for page_index in range(len(document)):
                page = document[page_index]
                try:
                    text_page = page.get_textpage()
                    try:
                        text = (
                            str(text_page.get_text_range())
                            .replace("\ufffe", "")
                            .strip()
                        )
                    finally:
                        text_page.close()
                finally:
                    page.close()
                if text:
                    parts.append(text)
            reference = "\n\f\n".join(parts).strip()
        finally:
            document.close()

        if len(reference) < self.minimum_characters:
            return None
        health = assess_reference_text_health(
            reference,
            suspicious_characters=self.suspicious_characters,
            minimum_suspicious_count=self.minimum_suspicious_count,
            maximum_suspicious_rate=self.maximum_suspicious_rate,
        )
        return SourceTextReference(
            text=reference,
            authority="pdf_native_text_layer",
            risk_flags=health.risk_flags,
        )
