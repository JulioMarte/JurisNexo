from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.normalization.adapters.pdf_native_text import (
    PdfNativeTextReferenceExtractor,
)
from jurisnexo.normalization.contracts import FormatInspection
from jurisnexo.normalization.gold import assess_reference_text_health
from jurisnexo.normalization.source_fidelity import (
    DeterministicSourceFidelityChecker,
    SourceTextReference,
)


@dataclass
class _Extractor:
    reference: SourceTextReference | None

    def extract(
        self,
        source: bytes,
        inspection: FormatInspection,
    ) -> SourceTextReference | None:
        del source, inspection
        return self.reference


def _inspection() -> FormatInspection:
    return FormatInspection(
        media_type="application/pdf",
        detected_format="application/pdf",
        metadata={},
    )


def test_source_fidelity_absent_reference_does_not_block() -> None:
    checker = DeterministicSourceFidelityChecker(_Extractor(None))
    assert (
        checker.evaluate(
            source=b"%PDF-fixture",
            inspection=_inspection(),
            candidate_text="texto",
        )
        is None
    )


def test_source_fidelity_unreliable_reference_requires_review() -> None:
    checker = DeterministicSourceFidelityChecker(
        _Extractor(
            SourceTextReference(
                text="REP�BLICA DOMINICANA",
                authority="fixture",
                risk_flags=("replacement_characters",),
            )
        )
    )
    result = checker.evaluate(
        source=b"%PDF-fixture",
        inspection=_inspection(),
        candidate_text="REPÚBLICA DOMINICANA",
    )
    assert result is not None
    assert result.requires_review
    assert result.score is None
    assert result.risk_flags == ("source_reference_unreliable",)


def test_source_fidelity_critical_identifier_loss_requires_review() -> None:
    checker = DeterministicSourceFidelityChecker(
        _Extractor(
            SourceTextReference(
                text=(
                    "SENTENCIA SCJ-SS-22-1191. "
                    "Ley 13-07. Artículo 5. Texto judicial estable."
                ),
                authority="fixture",
            )
        )
    )
    result = checker.evaluate(
        source=b"%PDF-fixture",
        inspection=_inspection(),
        candidate_text=(
            "SENTENCIA SCJ-SS-22-191. "
            "Ley 13-07. Artículo 5. Texto judicial estable."
        ),
    )
    assert result is not None
    assert result.requires_review
    assert result.score is not None
    assert result.score.legal_critical_recall < 1.0
    assert "source_legal_critical_loss" in result.risk_flags


def test_source_fidelity_healthy_candidate_can_pass() -> None:
    text = (
        "SENTENCIA SCJ-SS-22-1191. "
        "Ley 13-07. Artículo 5. Texto judicial estable."
    )
    checker = DeterministicSourceFidelityChecker(
        _Extractor(SourceTextReference(text=text, authority="fixture"))
    )
    result = checker.evaluate(
        source=b"%PDF-fixture",
        inspection=_inspection(),
        candidate_text=text,
    )
    assert result is not None
    assert not result.requires_review
    assert result.score is not None
    assert result.score.legal_critical_recall == 1.0



def test_pdf_native_reference_defaults_detect_probable_mojibake() -> None:
    extractor = PdfNativeTextReferenceExtractor()
    text = ("Rep⁄blica DecisiÛn n˙m. " * 20).strip()
    health = assess_reference_text_health(
        text,
        suspicious_characters=extractor.suspicious_characters,
        minimum_suspicious_count=extractor.minimum_suspicious_count,
        maximum_suspicious_rate=extractor.maximum_suspicious_rate,
    )
    assert "probable_mojibake" in health.risk_flags
