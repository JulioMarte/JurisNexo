from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType

import pytest

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))


def _module() -> ModuleType:
    path = REPO_ROOT / "backend" / "scripts" / "scj_ling_literal_ocr.py"
    spec = importlib.util.spec_from_file_location("scj_ling_literal_ocr", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "source.json"
    path.write_text(
        json.dumps(
            {
                "object_key": "jurisdictions/do/scj/principales-sentencias/aa/test.pdf",
                "source_pdf_sha256": "a" * 64,
                "cases": [
                    {
                        "sample_id": "hard-0001",
                        "object_key": "jurisdictions/do/scj/principales-sentencias/aa/test.pdf",
                        "page_index": 7,
                        "source_pdf_sha256": "a" * 64,
                        "image_sha256": "b" * 64,
                    },
                    {
                        "sample_id": "hard-0002",
                        "object_key": "jurisdictions/do/scj/principales-sentencias/aa/test.pdf",
                        "page_index": 9,
                        "source_pdf_sha256": "a" * 64,
                        "image_sha256": "c" * 64,
                    },
                ],
                "shard_count": 20,
                "model": "inclusionai/ling-3.0-flash-vl",
                "provider_slug": "novita",
                "allow_provider_fallbacks": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def _row(
    sample_id: str,
    page: int,
    image_sha: str,
    text: str,
    pass_number: int,
) -> dict[str, object]:
    module = _module()
    return {
        "sample_id": sample_id,
        "object_key": "jurisdictions/do/scj/principales-sentencias/aa/test.pdf",
        "source_pdf_sha256": "a" * 64,
        "page_index": page,
        "image_sha256": image_sha,
        "pass_number": pass_number,
        "transcription": text,
        "transcription_sha256": module._sha256(text.encode()),
        "routed_provider": "NovitaAI",
        "cost_usd": 0.001,
    }


def test_second_prompt_treats_first_pass_as_untrusted() -> None:
    module = _module()
    prompt = module._prompt(2, "texto previo 123")
    assert "NO confiable" in prompt
    assert "manda la imagen" in prompt
    assert "texto previo 123" in prompt
    with pytest.raises(ValueError):
        module._prompt(1, "must-not-anchor")


def test_provider_is_strictly_pinned_to_novita() -> None:
    module = _module()
    provider = module._provider("secret")
    assert provider.model == "inclusionai/ling-3.0-flash-vl"
    assert provider.provider_order == ("novita",)
    assert provider.allow_provider_fallbacks is False
    assert module._is_novita("NovitaAI")
    assert not module._is_novita("DeepInfra")


def test_second_pass_aggregate_surfaces_disagreement(tmp_path: Path) -> None:
    module = _module()
    source = _source(tmp_path)
    p1 = tmp_path / "p1.jsonl"
    first = [
        _row("hard-0001", 7, "b" * 64, "uno", 1),
        _row("hard-0002", 9, "c" * 64, "dos", 1),
    ]
    p1.write_text(
        "".join(json.dumps(row) + "\n" for row in first),
        encoding="utf-8",
    )

    shard = tmp_path / "shards" / "s0"
    shard.mkdir(parents=True)
    second = [
        _row("hard-0001", 7, "b" * 64, "uno", 2),
        _row("hard-0002", 9, "c" * 64, "dos corregido", 2),
    ]
    for row, before in zip(second, first, strict=True):
        row["previous_transcription_sha256"] = before["transcription_sha256"]
    (shard / "pages-00.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in second),
        encoding="utf-8",
    )

    output = tmp_path / "aggregate"
    assert module.aggregate(
        source_json=source,
        input_root=tmp_path / "shards",
        pass_number=2,
        output=output,
        previous_pages=p1,
    ) == 0
    summary = json.loads((output / "summary.json").read_text())
    assert summary["exact_match_with_previous"] == 1
    assert summary["changed_from_previous"] == 1
    review = [
        json.loads(line)
        for line in (output / "review.jsonl").read_text().splitlines()
    ]
    assert [row["sample_id"] for row in review] == ["hard-0002"]
    assert (
        output / "final-candidate-text" / "page-00009.txt"
    ).read_text() == "dos corregido"


def test_aggregate_fails_closed_on_missing_page(tmp_path: Path) -> None:
    module = _module()
    source = _source(tmp_path)
    shard = tmp_path / "shards" / "s0"
    shard.mkdir(parents=True)
    row = _row("hard-0001", 7, "b" * 64, "uno", 1)
    (shard / "pages-00.jsonl").write_text(
        json.dumps(row) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="reconciliation failed"):
        module.aggregate(
            source_json=source,
            input_root=tmp_path / "shards",
            pass_number=1,
            output=tmp_path / "out",
        )
