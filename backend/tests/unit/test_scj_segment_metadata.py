import pytest

from jurisnexo.ingestion.scj_segment_metadata import parse_scj_segment_metadata
from jurisnexo.ingestion.scj_segmentation import segment_scj_pages

pytestmark = pytest.mark.unit


TERCERA_START = """\
REPÚBLICA DOMINICANA
SUPREMA CORTE DE JUSTICIA
Exp. núm.: 001-011-2021-RECA-02294
Recurrente: Entidad Ejemplo
Recurrido: Persona Ejemplo
Materia: Contencioso administrativo
Decisión: Casa
SCJ-TS-25-0990

La Tercera Sala, en fecha 29 de abril de 2025, dicta la siguiente sentencia.
"""

TERCERA_CONTINUATION_WITH_CITED_CASE = """\
REPÚBLICA DOMINICANA
SUPREMA CORTE DE JUSTICIA
Exp. núm.: 001-011-2021-RECA-02294
Recurrente: Entidad Ejemplo
Recurrido: Persona Ejemplo
Materia: Contencioso administrativo
Decisión: Casa

En el precedente SCJ-TS-22-0049 se decidió una cuestión diferente.
"""

SEGUNDA_START = """\
REPÚBLICA DOMINICANA
SUPREMA CORTE DE JUSTICIA
Exp. 2024-0003141
Rc. Dirección General de Impuestos Internos (DGII)
Fecha: 30 de abril de 2025
Sentencia núm. SCJ-SS-25-0492
"""

SEGUNDA_CONTINUATION_WITH_HISTORICAL_DATE = """\
REPÚBLICA DOMINICANA
SUPREMA CORTE DE JUSTICIA
Exp. 2024-0003141
Rc. Dirección General de Impuestos Internos (DGII)
Fecha: 30 de abril de 2025

En fecha 22 de enero de 2024, dicta la siguiente sentencia citada en el recurso.
"""


def _values(observations, field_name: str) -> list[str]:
    return [
        value
        for item in observations
        if item.field_name == field_name
        and (value := item.normalized_text) is not None
    ]


def _dates(observations) -> list[str]:
    return [
        item.normalized_date.isoformat()
        for item in observations
        if item.field_name == "decision_date_candidate"
        and item.normalized_date is not None
    ]


def test_modern_segment_does_not_promote_cited_number_from_continuation_page() -> None:
    pages = [TERCERA_START, TERCERA_CONTINUATION_WITH_CITED_CASE]
    segments, _ = segment_scj_pages(pages)

    assert len(segments) == 1
    observations = parse_scj_segment_metadata(pages, segments[0])

    assert _values(observations, "decision_number") == ["SCJ-TS-25-0990"]


def test_modern_segment_does_not_promote_historical_date_from_continuation_page() -> None:
    pages = [SEGUNDA_START, SEGUNDA_CONTINUATION_WITH_HISTORICAL_DATE]
    segments, _ = segment_scj_pages(pages)

    assert len(segments) == 1
    observations = parse_scj_segment_metadata(pages, segments[0])

    assert _dates(observations) == ["2025-04-30"]
