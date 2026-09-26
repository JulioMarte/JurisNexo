"""Source-agnostic legal-document normalization control-plane contracts."""

from .contracts import (
    FormatInspection,
    FormatInspector,
    NormalizedDocument,
    NormalizedRepresentationResolver,
    OcrBackend,
    StructuralNormalizer,
    TextQualityJudge,
    VisualTextVerifier,
)

__all__ = [
    "FormatInspection", "FormatInspector", "NormalizedDocument",
    "NormalizedRepresentationResolver", "OcrBackend", "StructuralNormalizer",
    "TextQualityJudge", "VisualTextVerifier",
]
