from datetime import date

import pytest

from jurisnexo.ingestion.scj_layouts import SCJLayoutFamily, detect_scj_page_layout
from jurisnexo.ingestion.scj_metadata import parse_scj_page_metadata

pytestmark = pytest.mark.unit


DATED_RESOLUTION_2024 = """\
Principales Decisiones de la Suprema Corte de Justicia 2024
SEPTIEMBRE - DICIEMBRE

Ética; Comportamiento. Resolución que modifica el reglamento del Comité de
Comportamiento Ético del Poder Judicial. Pleno. 17/10/2024

RESOLUCION DEL 17 DE OCTUBRE DE 2024, NÚM. SCJ-RS-24-170

Resolución núm. 170-2024, que modifica la Resolución núm. 03-2011, del
6 de mayo de 2011, sobre el Reglamento del Comité de Comportamiento
Ético del Poder Judicial
"""


def test_detects_dated_2024_scj_resolution_as_case_boundary() -> None:
    detection = detect_scj_page_layout(DATED_RESOLUTION_2024, page_number=1)

    assert detection.family is SCJLayoutFamily.PRINCIPALES_2023_2024_RESOLUTION
    assert detection.signature_key == "SCJ-RS-24-170"
    assert detection.primary_decision_number == "SCJ-RS-24-170"
    assert detection.header_date == date(2024, 10, 17)


def test_dated_resolution_emits_primary_number_date_and_pleno() -> None:
    observations = parse_scj_page_metadata(DATED_RESOLUTION_2024, page_number=1)
    by_field = {item.field_name: item for item in observations}

    assert by_field["decision_number"].normalized_text == "SCJ-RS-24-170"
    assert by_field["decision_date_candidate"].normalized_date == date(2024, 10, 17)
    assert (
        by_field["decision_date_candidate"].method_name
        == "scj_formal_resolution_heading_date_v1"
    )
    assert by_field["court_organ"].normalized_text == "Pleno"
