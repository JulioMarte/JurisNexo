from __future__ import annotations

import importlib
import io
import json
from dataclasses import dataclass
from typing import Any

from jurisnexo.normalization.contracts import FormatInspection, NormalizedDocument


@dataclass(slots=True)
class DoclingStructuralNormalizer:
    """Docling adapter with PDF-aware OCR routing.

    The adapter stays source-agnostic. Jurisdiction/source configuration may
    supply OCR language tags such as ("iso:es",) without leaking that policy
    into the normalization contract.
    """

    ocr_language_tags: tuple[str, ...] = ()
    pdf_aware_ocr: bool = True
    enable_ocr: bool = True

    def normalize(
        self,
        source: bytes,
        inspection: FormatInspection,
        *,
        filename: str | None = None,
    ) -> NormalizedDocument:
        try:
            converter_module = importlib.import_module("docling.document_converter")
            base_models = importlib.import_module("docling.datamodel.base_models")
            pipeline_module = importlib.import_module(
                "docling.datamodel.pipeline_options"
            )
            docling_package = importlib.import_module("docling")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Docling is required for structural normalization; "
                "install the normalization runtime"
            ) from exc

        converter_cls: Any = converter_module.DocumentConverter
        stream_cls: Any = base_models.DocumentStream
        converter: Any
        ocr_policy = "not_applicable"

        if (
            inspection.media_type == "application/pdf"
            or inspection.media_type.startswith("image/")
        ):
            input_format: Any = base_models.InputFormat
            pdf_format_option: Any = converter_module.PdfFormatOption
            image_format_option: Any = converter_module.ImageFormatOption
            pdf_pipeline_options: Any = pipeline_module.PdfPipelineOptions
            ocr_mode: Any = pipeline_module.OcrMode

            pipeline_options = pdf_pipeline_options()
            pipeline_options.do_ocr = self.enable_ocr
            if inspection.media_type == "application/pdf":
                if not self.enable_ocr:
                    ocr_policy = "disabled"
                elif self.pdf_aware_ocr:
                    pipeline_options.ocr_options.mode = (
                        ocr_mode.PDF_AWARE_LAYOUT_REGIONS
                    )
                    ocr_policy = "pdf_aware_layout_regions"
                else:
                    ocr_policy = str(pipeline_options.ocr_options.mode)
                format_key = input_format.PDF
                format_option = pdf_format_option
            else:
                if self.enable_ocr:
                    pipeline_options.ocr_options.mode = ocr_mode.FULL_PAGE
                    ocr_policy = "full_page"
                else:
                    ocr_policy = "disabled"
                format_key = input_format.IMAGE
                format_option = image_format_option

            if self.enable_ocr and self.ocr_language_tags:
                pipeline_options.ocr_options.lang = list(
                    self.ocr_language_tags
                )

            converter = converter_cls(
                format_options={
                    format_key: format_option(
                        pipeline_options=pipeline_options
                    )
                }
            )
        else:
            converter = converter_cls()

        stream = stream_cls(
            name=filename or "document.bin",
            stream=io.BytesIO(source),
        )
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
            metadata={
                "schema": "DoclingDocument-v2",
                "ocr_policy": ocr_policy,
                "ocr_language_tags": list(self.ocr_language_tags),
            },
        )
