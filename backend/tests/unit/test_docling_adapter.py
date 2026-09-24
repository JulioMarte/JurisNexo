from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import jurisnexo.normalization.adapters.docling as adapter
from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.contracts import FormatInspection


class _OcrOptions:
    def __init__(self) -> None:
        self.mode: object | None = None
        self.lang: list[str] = []


class _PipelineOptions:
    def __init__(self) -> None:
        self.do_ocr = False
        self.ocr_options = _OcrOptions()


class _OcrMode:
    FULL_PAGE = "full_page"
    PDF_AWARE_LAYOUT_REGIONS = "pdf_aware_layout_regions"


class _InputFormat:
    PDF = "pdf"
    IMAGE = "image"


class _FormatOption:
    def __init__(self, *, pipeline_options: _PipelineOptions) -> None:
        self.pipeline_options = pipeline_options


class _DocumentStream:
    def __init__(self, *, name: str, stream: Any) -> None:
        self.name = name
        self.stream = stream


class _Document:
    def export_to_dict(self) -> dict[str, object]:
        return {
            "schema_name": "DoclingDocument",
            "body": {"children": []},
            "texts": [],
            "tables": [],
        }


class _Converter:
    last_format_options: dict[object, _FormatOption] | None = None

    def __init__(
        self,
        *,
        format_options: dict[object, _FormatOption] | None = None,
    ) -> None:
        type(self).last_format_options = format_options

    def convert(self, stream: _DocumentStream) -> SimpleNamespace:
        assert stream.name == "page.png"
        return SimpleNamespace(document=_Document())


def test_image_input_uses_full_page_spanish_ocr(monkeypatch: Any) -> None:
    converter_module = SimpleNamespace(
        DocumentConverter=_Converter,
        PdfFormatOption=_FormatOption,
        ImageFormatOption=_FormatOption,
    )
    base_models = SimpleNamespace(
        DocumentStream=_DocumentStream,
        InputFormat=_InputFormat,
    )
    pipeline_module = SimpleNamespace(
        PdfPipelineOptions=_PipelineOptions,
        OcrMode=_OcrMode,
    )
    docling_package = SimpleNamespace(__version__="2.129.0")

    modules = {
        "docling.document_converter": converter_module,
        "docling.datamodel.base_models": base_models,
        "docling.datamodel.pipeline_options": pipeline_module,
        "docling": docling_package,
    }
    def fake_import_module(name: str) -> object:
        return modules[name]

    monkeypatch.setattr(
        adapter.importlib,
        "import_module",
        fake_import_module,
    )

    result = DoclingStructuralNormalizer(
        ocr_language_tags=("iso:es",),
    ).normalize(
        b"fake-png",
        FormatInspection(
            media_type="image/png",
            detected_format="image/png",
            metadata={},
        ),
        filename="page.png",
    )

    options = _Converter.last_format_options
    assert options is not None
    image_option = options[_InputFormat.IMAGE]
    assert image_option.pipeline_options.do_ocr is True
    assert image_option.pipeline_options.ocr_options.mode == _OcrMode.FULL_PAGE
    assert image_option.pipeline_options.ocr_options.lang == ["iso:es"]
    assert result.metadata["ocr_policy"] == "full_page"
    assert result.metadata["ocr_language_tags"] == ["iso:es"]



def test_pdf_input_can_disable_ocr_for_native_text_diagnostics(
    monkeypatch: Any,
) -> None:
    converter_module = SimpleNamespace(
        DocumentConverter=_Converter,
        PdfFormatOption=_FormatOption,
        ImageFormatOption=_FormatOption,
    )
    base_models = SimpleNamespace(
        DocumentStream=_DocumentStream,
        InputFormat=_InputFormat,
    )
    pipeline_module = SimpleNamespace(
        PdfPipelineOptions=_PipelineOptions,
        OcrMode=_OcrMode,
    )
    docling_package = SimpleNamespace(__version__="2.129.0")
    modules = {
        "docling.document_converter": converter_module,
        "docling.datamodel.base_models": base_models,
        "docling.datamodel.pipeline_options": pipeline_module,
        "docling": docling_package,
    }

    monkeypatch.setattr(
        adapter.importlib,
        "import_module",
        lambda name: modules[name],
    )

    result = DoclingStructuralNormalizer(
        ocr_language_tags=("iso:es",),
        enable_ocr=False,
    ).normalize(
        b"fake-pdf",
        FormatInspection(
            media_type="application/pdf",
            detected_format="application/pdf",
            metadata={},
        ),
        filename="page.png",
    )

    options = _Converter.last_format_options
    assert options is not None
    pdf_option = options[_InputFormat.PDF]
    assert pdf_option.pipeline_options.do_ocr is False
    assert pdf_option.pipeline_options.ocr_options.lang == []
    assert result.metadata["ocr_policy"] == "disabled"
