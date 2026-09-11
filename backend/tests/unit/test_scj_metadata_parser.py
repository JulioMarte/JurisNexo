from datetime import date

import pytest

from jurisnexo.ingestion.scj_metadata import ObservationValueType, parse_scj_page_metadata

pytestmark = pytest.mark.unit


SAMPLE_PAGE = """\
SCJ-PS-25-0853
Expediente núm. 001-022-2024-RECA-00421
Partes: Compañía Ejemplo, S. R. L. contra Persona Ejemplo
Materia: Civil
Decisión: Rechaza el recurso de casación
Ponente: Magistrada Ejemplo

EN NOMBRE DE LA REPÚBLICA
La Primera Sala, en fecha 30 de abril de 2025, dicta la siguiente sentencia.
"""


def _dockets(text: str) -> list[str]:
    return [
        item.normalized_text
        for item in parse_scj_page_metadata(text, page_number=1)
        if item.field_name == "docket_number" and item.normalized_text is not None
    ]


def test_extracts_observed_scj_metadata_patterns() -> None:
    observations = parse_scj_page_metadata(SAMPLE_PAGE, page_number=7)
    by_field = {observation.field_name: observation for observation in observations}

    assert by_field["decision_number"].normalized_text == "SCJ-PS-25-0853"
    assert by_field["decision_number"].value_type is ObservationValueType.IDENTIFIER
    assert by_field["docket_number"].normalized_text == "001-022-2024-RECA-00421"
    assert by_field["docket_number"].method_name == "scj_labeled_docket_v3"
    assert by_field["matter"].normalized_text == "Civil"
    assert by_field["decision_summary"].normalized_text == "Rechaza el recurso de casación"
    assert by_field["rapporteur"].normalized_text == "Magistrada Ejemplo"
    assert by_field["decision_date_candidate"].normalized_date == date(2025, 4, 30)
    assert by_field["decision_date_candidate"].method_name == "scj_decision_formula_date_v2"

    for observation in observations:
        assert observation.page_number == 7
        assert observation.char_start >= 0
        assert observation.char_end > observation.char_start
        assert len(observation.observation_key) == 64


def test_docket_parser_accepts_observed_exp_abbreviation() -> None:
    assert _dockets("Exp. 057-2022-EPEN-00173") == ["057-2022-EPEN-00173"]


def test_docket_parser_extracts_multiple_identifiers_separately() -> None:
    assert _dockets("Exps. núms. 2014-3935 y 2014-4025") == [
        "2014-3935",
        "2014-4025",
    ]


def test_docket_parser_accepts_full_expediente_label() -> None:
    assert _dockets("Expediente núm. 465-2021-ELAB-00119") == [
        "465-2021-ELAB-00119"
    ]


def test_docket_parser_does_not_match_exponiendo_prose() -> None:
    text = (
        "Exponiendo las justificaciones de hecho o de derecho relacionadas a la "
        "ejecución del fallo. Tercera Sala. 31/01/2023. Decisión íntegra."
    )

    assert _dockets(text) == []


def test_docket_parser_does_not_match_expediente_as_ordinary_noun() -> None:
    text = "Expediente o del procedimiento, entendida como la interrelación de sus actos."

    assert _dockets(text) == []


def test_unparsed_labeled_docket_is_not_promoted_as_identifier() -> None:
    assert _dockets("Expediente núm. pendiente de asignación") == []


def test_observation_key_is_stable_for_same_input() -> None:
    first = parse_scj_page_metadata(SAMPLE_PAGE, page_number=7)
    second = parse_scj_page_metadata(SAMPLE_PAGE, page_number=7)

    assert [item.observation_key for item in first] == [item.observation_key for item in second]


def test_unrelated_procedural_date_is_not_treated_as_decision_date() -> None:
    text = (
        "La sentencia recurrida fue dictada en fecha 12 de enero de 2024. "
        "La parte recurrente notificó posteriormente su recurso."
    )

    observations = parse_scj_page_metadata(text, page_number=3)

    assert all(item.field_name != "decision_date_candidate" for item in observations)


def test_invalid_calendar_date_is_not_emitted_even_with_decision_formula() -> None:
    text = "La sala, en fecha 31 de febrero de 2025, dicta la siguiente sentencia."

    observations = parse_scj_page_metadata(text, page_number=1)

    assert all(item.field_name != "decision_date_candidate" for item in observations)


def test_nonpositive_page_number_is_rejected() -> None:
    with pytest.raises(ValueError, match="page_number must be positive"):
        parse_scj_page_metadata(SAMPLE_PAGE, page_number=0)
