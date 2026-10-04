from __future__ import annotations

import hashlib

import pytest

from jurisnexo.normalization.independent_ocr import (
    INDEPENDENT_OCR_PROMPT,
    OcrTarget,
    build_record,
    shard_targets,
)

pytestmark = [pytest.mark.unit]


def _targets(count: int) -> list[OcrTarget]:
    return [
        OcrTarget(
            document_id=f"doc{index}",
            page_index=index,
            object_key=f"jurisdictions/do/scj/decisions/x/{index}.pdf",
            source_pdf_sha256=f"{index:064d}",
        )
        for index in range(count)
    ]


def test_shard_targets_partitions_without_overlap() -> None:
    targets = _targets(10)

    shards = [shard_targets(targets, shard_index=i, shard_count=3) for i in range(3)]

    flattened = [target for shard in shards for target in shard]
    assert sorted(target.page_index for target in flattened) == list(range(10))
    assert len(flattened) == len({(t.document_id, t.page_index) for t in flattened})


def test_shard_targets_rejects_invalid_arguments() -> None:
    targets = _targets(3)

    with pytest.raises(ValueError):
        shard_targets(targets, shard_index=0, shard_count=0)
    with pytest.raises(ValueError):
        shard_targets(targets, shard_index=3, shard_count=3)


def test_build_record_hashes_transcription_and_prompt() -> None:
    target = _targets(1)[0]

    record = build_record(
        target=target,
        render_pixel_sha256="a" * 64,
        requested_model="deepseek/deepseek-v4.1-flash",
        provider_tag="morph/fp8",
        returned_model="deepseek/deepseek-v4.1-flash",
        returned_provider="Morph",
        reasoning_effort="none",
        transcription="Texto SCJ-SS-22-0516",
        prompt_tokens=700,
        completion_tokens=120,
        cost_usd=0.0003,
        response_id="gen-1",
    )

    assert record.transcription_sha256 == hashlib.sha256(
        b"Texto SCJ-SS-22-0516"
    ).hexdigest()
    assert record.prompt_sha256 == hashlib.sha256(
        INDEPENDENT_OCR_PROMPT.encode()
    ).hexdigest()
    assert record.source_pdf_sha256 == target.source_pdf_sha256
    assert record.to_dict()["provider_tag"] == "morph/fp8"
