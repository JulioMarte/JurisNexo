from pathlib import Path

import pytest

pytestmark = [pytest.mark.fitness]

ROOT = Path(__file__).resolve().parents[2] / "src" / "jurisnexo"


def test_normalization_core_contains_no_institution_specific_modules() -> None:
    root = ROOT / "normalization"
    forbidden = ("scj", "tribunal_constitucional", "constitution", "legislation")
    paths = [p.as_posix().lower() for p in root.rglob("*.py")]
    assert not [p for p in paths if any(token in p for token in forbidden)]


def test_source_adapters_do_not_own_normalization_engines() -> None:
    acquisition = ROOT / "acquisition"
    forbidden_names = {"docling", "tika", "tesseract", "rapidocr", "paddleocr", "jev"}
    offenders: list[str] = []
    for path in acquisition.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        if any(name in text for name in forbidden_names):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
