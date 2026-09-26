from __future__ import annotations

import json
import os
from pathlib import Path

from jurisnexo.acquisition.tc_public import fetch_tc_decision
from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.adapters.tika import TikaServerFormatInspector
from jurisnexo.normalization.quality import extract_text_from_structural_json

DETAIL_URL = (
    "https://www.tribunalconstitucional.gob.do/"
    "consultas/secretar%C3%ADa/sentencias/tc000126/"
)
EXPECTED_FILENAME = "tc-0001-26-tc-04-2025-0258.pdf"
OUTPUT = Path(
    os.environ.get(
        "TC_SECOND_SOURCE_OUTPUT",
        ".artifacts/tc-second-source-normalization.json",
    )
)


def main() -> int:
    artifact = fetch_tc_decision(
        detail_url=DETAIL_URL,
        expected_filename=EXPECTED_FILENAME,
        timeout_seconds=45.0,
    )
    inspector = TikaServerFormatInspector(
        base_url=os.environ.get(
            "JURISNEXO_TIKA_URL",
            "http://127.0.0.1:9998",
        )
    )
    inspection = inspector.inspect(
        artifact.content,
        filename=artifact.filename,
    )
    normalized = DoclingStructuralNormalizer(ocr_language_tags=("iso:es",)).normalize(
        artifact.content,
        inspection,
        filename=artifact.filename,
    )
    text = extract_text_from_structural_json(normalized.payload)
    upper_text = text.upper()
    identity_markers = (
        "TC/0001/26",
        "TC-04-2025-0258",
        "TRIBUNAL CONSTITUCIONAL",
    )
    marker_hits = tuple(
        marker
        for marker in identity_markers
        if marker in upper_text
    )
    payload = {
        "schema_version": 1,
        "source": "tribunal-constitucional",
        "decision": "TC/0001/26",
        "detail_url": artifact.detail_url,
        "document_url": artifact.document_url,
        "filename": artifact.filename,
        "source_sha256": artifact.sha256,
        "source_bytes": len(artifact.content),
        "source_content_type": artifact.content_type,
        "detected_media_type": inspection.media_type,
        "normalized_media_type": normalized.media_type,
        "normalizer_engine": normalized.engine,
        "normalizer_engine_version": normalized.engine_version,
        "normalized_payload_bytes": len(normalized.payload),
        "extracted_text_chars": len(text),
        "identity_marker_hits": marker_hits,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))

    valid_pdf = artifact.content.startswith(b"%PDF-")
    valid_hash = len(artifact.sha256) == 64
    detected_pdf = inspection.media_type == "application/pdf"
    substantial_text = len(text) >= 1000
    source_identity_visible = len(marker_hits) >= 1
    return (
        0
        if all(
            (
                valid_pdf,
                valid_hash,
                detected_pdf,
                substantial_text,
                source_identity_visible,
            )
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
