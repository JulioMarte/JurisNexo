from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aggregate_scj_ocr_hard_rescue import _labels
from prepare_scj_ocr_hard_rescue import _round_robin
from run_open_source_ocr_engine import _observation_identity, _stable_json_sha256


def test_round_robin_is_balanced_and_deterministic() -> None:
    per_document = {
        "a.pdf": [{"object_key": "a.pdf", "page_index": i} for i in range(30)],
        "b.pdf": [{"object_key": "b.pdf", "page_index": i} for i in range(30)],
        "c.pdf": [{"object_key": "c.pdf", "page_index": i} for i in range(30)],
    }
    first = _round_robin(per_document, 50)
    second = _round_robin(per_document, 50)
    assert first == second
    counts = {
        key: sum(row["object_key"] == key for row in first)
        for key in per_document
    }
    assert max(counts.values()) - min(counts.values()) <= 1
    assert len({(row["object_key"], row["page_index"]) for row in first}) == 50


def test_candidate_labels_are_permutations_and_not_constant() -> None:
    mappings = [_labels(f"hard-{i:04d}") for i in range(30)]
    assert all(set(mapping) == {"paddleocr", "rapidocr", "tesseract"} for mapping in mappings)
    assert all(set(mapping.values()) == {"A", "B", "C"} for mapping in mappings)
    assert len({json.dumps(mapping, sort_keys=True) for mapping in mappings}) > 1


def test_shard_partition_covers_each_case_exactly_once() -> None:
    cases = list(range(500))
    shards = [[case for index, case in enumerate(cases) if index % 5 == shard] for shard in range(5)]
    assert all(len(shard) == 100 for shard in shards)
    flattened = [case for shard in shards for case in shard]
    assert sorted(flattened) == cases


def test_observation_id_binds_engine_config_and_source_evidence() -> None:
    case = {
        "source_pdf_sha256": "a" * 64,
        "page_index": 17,
        "image_sha256": "b" * 64,
    }
    config_id = _stable_json_sha256({"lang": "es"})
    first = _observation_identity("rapidocr", "3.9.2", config_id, case)
    second = _observation_identity("rapidocr", "3.9.2", config_id, case)
    changed_page = {**case, "page_index": 18}
    third = _observation_identity("rapidocr", "3.9.2", config_id, changed_page)
    assert first == second
    assert first.startswith("ocr:rapidocr:")
    assert first != third
