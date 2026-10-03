from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from jurisnexo.acquisition.local_object_store import LocalObjectStore
from jurisnexo.acquisition.object_store import ObjectNotFoundError

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def test_local_store_round_trips_bytes_and_metadata(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    key = "benchmarks/scj-principales/ling-literal-ocr/v1/plan/pages/doc/000000/pass-1.json"
    payload = b'{"ok": true}'

    assert store.exists(key) is False
    assert store.head_metadata(key) is None
    with pytest.raises(ObjectNotFoundError):
        store.get_bytes(key)

    store.put(
        key=key,
        content=payload,
        content_type="application/json",
        metadata={"plan-sha256": "a" * 64},
    )

    assert store.exists(key) is True
    assert store.get_bytes(key) == payload
    assert store.head_metadata(key) == {
        "payload-sha256": hashlib.sha256(payload).hexdigest()
    }
    assert tmp_path.joinpath(*key.split("/")).read_bytes() == payload


def test_local_store_missing_object_raises_not_found(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)

    with pytest.raises(ObjectNotFoundError):
        store.get_bytes("jurisdictions/do/scj/missing.pdf")


def test_local_store_rejects_escaping_or_degenerate_keys(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)

    for key in ("", "/absolute", "a//b", "a/../b", "trailing/"):
        with pytest.raises(ValueError):
            store.exists(key)


def test_local_store_lists_objects_under_prefix_in_key_order(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    for key in (
        "benchmarks/scj-principales/corpus-verification/v1/b/_SUCCESS.json",
        "benchmarks/scj-principales/corpus-verification/v1/a/inventory.json",
        "jurisdictions/do/scj/example.pdf",
    ):
        store.put(key=key, content=b"x", content_type="application/json", metadata={})

    listed = store.list_objects("benchmarks/scj-principales/corpus-verification/v1/")

    assert [item.key for item in listed] == [
        "benchmarks/scj-principales/corpus-verification/v1/a/inventory.json",
        "benchmarks/scj-principales/corpus-verification/v1/b/_SUCCESS.json",
    ]
    assert all(item.size == 1 for item in listed)
    assert store.list_objects("does/not/exist/") == []


def test_local_store_requires_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a directory"):
        LocalObjectStore(tmp_path / "missing")
