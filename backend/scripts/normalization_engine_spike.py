from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from jurisnexo.normalization.adapters.docling import DoclingStructuralNormalizer
from jurisnexo.normalization.adapters.tika import TikaServerFormatInspector


@dataclass(frozen=True, slots=True)
class FixtureCase:
    name: str
    filename: str
    expected_tokens: tuple[str, ...]
    expected_docling_success: bool


@dataclass(frozen=True, slots=True)
class SpikeResult:
    name: str
    detected_media_type: str | None
    tika_seconds: float
    docling_success: bool
    docling_seconds: float
    output_bytes: int
    token_coverage: float
    error: str | None


CASES = (
    FixtureCase("born-digital-pdf", "born-digital.pdf", ("Articulo", "12", "Ley", "1"), True),
    FixtureCase("scanned-pdf", "scanned.pdf", ("ART", "12", "LEY", "1"), True),
    FixtureCase("mixed-pdf", "mixed.pdf", ("Articulo", "12", "LEY", "1"), True),
    FixtureCase("docx", "sample.docx", ("Artículo", "12", "Ley", "1"), True),
    FixtureCase("rtf", "sample.rtf", ("Artículo", "12", "Ley", "1"), True),
    FixtureCase("html", "sample.html", ("Artículo", "12", "Ley", "1"), True),
    FixtureCase("corrupt-pdf", "corrupt.pdf", (), False),
)


def _pdf(objects: list[bytes]) -> bytes:
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def _text_pdf(text: str) -> bytes:
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"\nendstream",
    ]
    return _pdf(objects)


_FONT: dict[str, tuple[str, ...]] = {
    "A": ("01110","10001","10001","11111","10001","10001","10001"),
    "R": ("11110","10001","10001","11110","10100","10010","10001"),
    "T": ("11111","00100","00100","00100","00100","00100","00100"),
    "L": ("10000","10000","10000","10000","10000","10000","11111"),
    "E": ("11111","10000","10000","11110","10000","10000","11111"),
    "Y": ("10001","10001","01010","00100","00100","00100","00100"),
    "1": ("00100","01100","00100","00100","00100","00100","01110"),
    "2": ("01110","10001","00001","00010","00100","01000","11111"),
    " ": ("00000","00000","00000","00000","00000","00000","00000"),
}


def _text_bitmap(text: str, scale: int = 5) -> tuple[int, int, bytes]:
    glyph_width = 5
    glyph_height = 7
    width = (len(text) * (glyph_width + 1) - 1) * scale
    height = glyph_height * scale
    pixels = bytearray([255] * (width * height))
    for char_index, char in enumerate(text):
        glyph = _FONT.get(char, _FONT[" "])
        x0 = char_index * (glyph_width + 1) * scale
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit != "1":
                    continue
                for sy in range(scale):
                    for sx in range(scale):
                        x = x0 + gx * scale + sx
                        y = gy * scale + sy
                        pixels[y * width + x] = 0
    return width, height, bytes(pixels)


def _image_pdf(text: str) -> bytes:
    width, height, pixels = _text_bitmap(text)
    compressed = zlib.compress(pixels)
    draw = f"q {width} 0 0 {height} 72 650 cm /Im0 Do Q".encode()
    image = (
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        "/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
        f"/Length {len(compressed)} >>\nstream\n"
    ).encode() + compressed + b"\nendstream"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>"
        ),
        image,
        b"<< /Length " + str(len(draw)).encode() + b" >>\nstream\n"
        + draw + b"\nendstream",
    ]
    return _pdf(objects)


def _mixed_pdf() -> bytes:
    text_stream = b"BT /F1 18 Tf 72 720 Td (Articulo 12) Tj ET"
    width, height, pixels = _text_bitmap("LEY 1")
    compressed = zlib.compress(pixels)
    image_stream = f"q {width} 0 0 {height} 72 650 cm /Im0 Do Q".encode()
    image = (
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        "/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
        f"/Length {len(compressed)} >>\nstream\n"
    ).encode() + compressed + b"\nendstream"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>"
        ),
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << /Im0 7 0 R >> >> /Contents 8 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(text_stream)).encode() + b" >>\nstream\n"
        + text_stream + b"\nendstream",
        image,
        b"<< /Length " + str(len(image_stream)).encode() + b" >>\nstream\n"
        + image_stream + b"\nendstream",
    ]
    return _pdf(objects)


def _write_docx(path: Path) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    document = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>Artículo 12 Ley 1</w:t></w:r></w:p></w:body></w:document>"""
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)


def generate_fixtures(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "born-digital.pdf").write_bytes(_text_pdf("Articulo 12 Ley 1"))
    (root / "scanned.pdf").write_bytes(_image_pdf("ART 12 LEY 1"))
    (root / "mixed.pdf").write_bytes(_mixed_pdf())
    _write_docx(root / "sample.docx")
    (root / "sample.rtf").write_text(
        r"{\rtf1\ansi Art\'edculo 12 Ley 1}", encoding="latin-1"
    )
    (root / "sample.html").write_text(
        "<html><body><p>Artículo 12 Ley 1</p></body></html>", encoding="utf-8"
    )
    (root / "corrupt.pdf").write_bytes(b"%PDF-1.7\nthis is intentionally corrupt")


def _collect_text(value: object) -> str:
    parts: list[str] = []

    def visit(node: object) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "text" and isinstance(child, str):
                    parts.append(child)
                else:
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return "\n".join(parts)


def run_spike(*, tika_url: str, output: Path) -> list[SpikeResult]:
    inspector = TikaServerFormatInspector(base_url=tika_url)
    normalizer = DoclingStructuralNormalizer()
    results: list[SpikeResult] = []
    with tempfile.TemporaryDirectory(prefix="jurisnexo-normalization-") as temp:
        fixtures = Path(temp)
        generate_fixtures(fixtures)
        for case in CASES:
            source = (fixtures / case.filename).read_bytes()
            media_type: str | None = None
            inspect_started = time.perf_counter()
            try:
                inspection = inspector.inspect(source, filename=case.filename)
                media_type = inspection.media_type
                tika_seconds = time.perf_counter() - inspect_started
            except Exception as exc:
                results.append(
                    SpikeResult(
                        case.name,
                        None,
                        time.perf_counter() - inspect_started,
                        False,
                        0.0,
                        0,
                        0.0,
                        f"Tika: {type(exc).__name__}: {exc}",
                    )
                )
                continue

            docling_started = time.perf_counter()
            try:
                normalized = normalizer.normalize(
                    source,
                    inspection,
                    filename=case.filename,
                )
                elapsed = time.perf_counter() - docling_started
                document = json.loads(normalized.payload)
                text = _collect_text(document)
                hits = sum(token.casefold() in text.casefold() for token in case.expected_tokens)
                coverage = hits / len(case.expected_tokens) if case.expected_tokens else 1.0
                results.append(
                    SpikeResult(
                        case.name,
                        media_type,
                        tika_seconds,
                        True,
                        elapsed,
                        len(normalized.payload),
                        coverage,
                        None,
                    )
                )
            except Exception as exc:
                results.append(
                    SpikeResult(
                        case.name,
                        media_type,
                        tika_seconds,
                        False,
                        time.perf_counter() - docling_started,
                        0,
                        0.0,
                        f"Docling: {type(exc).__name__}: {exc}",
                    )
                )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([asdict(item) for item in results], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tika-url",
        default=os.environ.get("JURISNEXO_TIKA_URL", "http://127.0.0.1:9998"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".artifacts/normalization-engine-spike.json"),
    )
    args = parser.parse_args()
    results = run_spike(tika_url=args.tika_url, output=args.output)
    for item in results:
        print(
            f"{item.name}: tika={item.detected_media_type} "
            f"docling={'ok' if item.docling_success else 'failed'} "
            f"coverage={item.token_coverage:.2f} error={item.error or '-'}"
        )

    required = [item for item in results if item.name != "corrupt-pdf"]
    corrupt = next(item for item in results if item.name == "corrupt-pdf")
    structural_ok = all(
        item.detected_media_type and item.docling_success for item in required
    )
    fidelity_ok = all(item.token_coverage == 1.0 for item in required)
    corrupt_rejected = not corrupt.docling_success
    return 0 if structural_ok and fidelity_ok and corrupt_rejected else 1


if __name__ == "__main__":
    raise SystemExit(main())
