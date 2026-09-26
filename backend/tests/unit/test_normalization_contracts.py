from jurisnexo.normalization import FormatInspection, NormalizedDocument


def test_normalization_value_objects_are_engine_neutral() -> None:
    inspection = FormatInspection("application/pdf", "pdf", {"pages": 1})
    normalized = NormalizedDocument("application/json", b"{}", "fake", "1", {})
    assert inspection.detected_format == "pdf"
    assert normalized.engine == "fake"
