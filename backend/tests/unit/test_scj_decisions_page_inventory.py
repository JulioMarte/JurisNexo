from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))

pytestmark = [pytest.mark.unit]


def _module() -> ModuleType:
    path = REPO_ROOT / "backend" / "scripts" / "scj_decisions_page_inventory.py"
    spec = importlib.util.spec_from_file_location("scj_decisions_page_inventory", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pdf(page_count: int) -> bytes:
    images = [Image.new("RGB", (40, 40), "white") for _ in range(page_count)]
    stream = io.BytesIO()
    images[0].save(stream, format="PDF", save_all=True, append_images=images[1:])
    return stream.getvalue()


def test_shard_hex_prefixes_partitions_all_256() -> None:
    module = _module()

    buckets = module.shard_hex_prefixes(20)

    assert len(buckets) == 20
    flattened = [item for bucket in buckets for item in bucket]
    assert sorted(flattened) == sorted(module.HEX_PREFIXES)
    assert len(flattened) == len(set(flattened))
    sizes = {len(bucket) for bucket in buckets}
    assert max(sizes) - min(sizes) <= 1


def test_shard_hex_prefixes_rejects_invalid_counts() -> None:
    module = _module()

    with pytest.raises(ValueError):
        module.shard_hex_prefixes(0)
    with pytest.raises(ValueError):
        module.shard_hex_prefixes(257)


def test_count_pages_reads_real_page_count() -> None:
    module = _module()

    assert module.count_pages(_pdf(1)) == 1
    assert module.count_pages(_pdf(3)) == 3


def _record(key: str, *, fmt: str = "pdf", pages: int | None = 3) -> dict[str, object]:
    return {"key": key, "size": 100, "format": fmt, "pages": pages, "error": None}


def test_summarize_records_totals_and_distribution() -> None:
    module = _module()
    records = [
        _record("a.pdf", pages=2),
        _record("b.pdf", pages=8),
        _record("c.pdf", pages=5),
        _record("d.doc", fmt="doc", pages=None),
    ]

    summary = module.summarize_records(
        records, expected_total=4, expected_pdf=3, expected_non_pdf=1
    )

    assert summary["total_pages"] == 15
    assert summary["pdf_count"] == 3
    assert summary["non_pdf_by_format"] == {"doc": 1}
    assert summary["pages_min"] == 2
    assert summary["pages_max"] == 8
    assert summary["total_bytes"] == 400


def test_summarize_records_fails_closed_on_count_drift() -> None:
    module = _module()

    with pytest.raises(RuntimeError, match="expected 5"):
        module.summarize_records(
            [_record("a.pdf")], expected_total=5, expected_pdf=5, expected_non_pdf=0
        )


def test_summarize_records_fails_closed_on_duplicate_keys() -> None:
    module = _module()

    with pytest.raises(RuntimeError, match="duplicate keys"):
        module.summarize_records(
            [_record("a.pdf"), _record("a.pdf")],
            expected_total=2,
            expected_pdf=2,
            expected_non_pdf=0,
        )


def test_summarize_records_fails_closed_on_format_drift() -> None:
    module = _module()

    with pytest.raises(RuntimeError, match="format counts drifted"):
        module.summarize_records(
            [_record("a.pdf")], expected_total=1, expected_pdf=0, expected_non_pdf=1
        )


def test_load_records_reads_all_shard_files(tmp_path: Path) -> None:
    module = _module()
    (tmp_path / "shard-00").mkdir()
    (tmp_path / "shard-00" / "records.jsonl").write_text(
        json.dumps(_record("a.pdf")) + "\n", encoding="utf-8"
    )
    (tmp_path / "shard-01.jsonl").write_text(
        json.dumps(_record("b.pdf")) + "\n", encoding="utf-8"
    )

    records = module.load_records(tmp_path)

    assert sorted(record["key"] for record in records) == ["a.pdf", "b.pdf"]
