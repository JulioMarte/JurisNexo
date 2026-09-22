from __future__ import annotations

import json

from jurisnexo.normalization.quality import extract_text_from_structural_json


def _payload(document: dict[str, object]) -> bytes:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")


def test_extract_text_follows_docling_body_reading_order() -> None:
    document: dict[str, object] = {
        "schema_name": "DoclingDocument",
        "body": {
            "children": [
                {"$ref": "#/texts/1"},
                {"$ref": "#/groups/0"},
            ]
        },
        "groups": [
            {
                "children": [
                    {"$ref": "#/texts/0"},
                    {"$ref": "#/texts/2"},
                ]
            }
        ],
        "texts": [
            {"text": "Segundo"},
            {"text": "Primero"},
            {"text": "Tercero"},
        ],
        "tables": [],
    }

    assert extract_text_from_structural_json(_payload(document)) == (
        "Primero\nSegundo\nTercero"
    )


def test_extract_text_emits_table_cells_once_in_row_column_order() -> None:
    document: dict[str, object] = {
        "schema_name": "DoclingDocument",
        "body": {
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/tables/0"},
                {"$ref": "#/texts/1"},
            ]
        },
        "texts": [
            {"text": "Antes"},
            {"text": "Después"},
        ],
        "groups": [],
        "tables": [
            {
                "data": {
                    "table_cells": [
                        {
                            "text": "B2",
                            "start_row_offset_idx": 1,
                            "start_col_offset_idx": 1,
                        },
                        {
                            "text": "A1",
                            "start_row_offset_idx": 0,
                            "start_col_offset_idx": 0,
                        },
                        {
                            "text": "B1",
                            "start_row_offset_idx": 1,
                            "start_col_offset_idx": 0,
                        },
                    ]
                }
            }
        ],
    }

    assert extract_text_from_structural_json(_payload(document)) == (
        "Antes\nA1\nB1\nB2\nDespués"
    )


def test_extract_text_deduplicates_repeated_body_reference() -> None:
    document: dict[str, object] = {
        "schema_name": "DoclingDocument",
        "body": {
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/texts/0"},
            ]
        },
        "texts": [{"text": "Único"}],
        "groups": [],
        "tables": [],
    }

    assert extract_text_from_structural_json(_payload(document)) == "Único"
