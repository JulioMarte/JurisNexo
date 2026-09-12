from jurisnexo.corpus import source_inventory

PORTAL = "https://consultasentenciascj.poderjudicial.gob.do/"


def test_normalizes_proven_live_null_prefix() -> None:
    url, availability, notes = source_inventory.normalize_scj_bulletin_pdf_url(
        "NULLhttps://consultaglobal.blob.core.windows.net/boletines/Boletines/1989/Junio.pdf"
    )
    assert url == "https://consultaglobal.blob.core.windows.net/boletines/Boletines/1989/Junio.pdf"
    assert availability == "available"
    assert notes["document_url_normalization"] == "stripped_literal_NULL_prefix"
    assert notes["raw_document_url"].startswith("NULLhttps://")


def test_preserves_bulletin_without_artifact_as_source_record() -> None:
    observation = source_inventory.scj_source_observation_from_record(
        discovery_url=PORTAL,
        record={
            "surface": "bulletins",
            "row": {
                "idCabecera": 1344,
                "idCuerpo": 5057,
                "ano": 2026,
                "mes": "Enero",
                "urlCuerpo": None,
                "urlCabecera": None,
            },
        },
    )
    assert observation.source_identifier == "bulletin:1344:5057"
    assert observation.source_collection == "bulletins"
    assert observation.document_kind == "official_bulletin"
    assert observation.document_url is None
    assert observation.artifact_availability == "not_published"
    assert observation.normalization_notes == {"document_url_state": "source_null"}


def test_rejects_unknown_bulletin_url_corruption() -> None:
    try:
        source_inventory.normalize_scj_bulletin_pdf_url(
            "BROKENhttp://example.invalid/file.pdf"
        )
    except ValueError as exc:
        assert "unsupported SCJ bulletin document URL shape" in str(exc)
    else:
        raise AssertionError("unknown URL corruption must fail closed")
