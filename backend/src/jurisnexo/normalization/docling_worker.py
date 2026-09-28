from __future__ import annotations

import argparse
import json
from pathlib import Path

from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.contracts import FormatInspection


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--media-type", required=True)
    parser.add_argument("--detected-format", required=True)
    parser.add_argument("--ocr-language", action="append", default=[])
    args = parser.parse_args()

    source = args.input.read_bytes()
    result = DoclingStructuralNormalizer(
        ocr_language_tags=tuple(args.ocr_language),
    ).normalize(
        source,
        FormatInspection(
            media_type=args.media_type,
            detected_format=args.detected_format,
            metadata={},
        ),
        filename=args.filename,
    )
    args.output.write_bytes(result.payload)
    args.metadata.write_text(
        json.dumps(
            {
                "media_type": result.media_type,
                "engine": result.engine,
                "engine_version": result.engine_version,
                "metadata": result.metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
