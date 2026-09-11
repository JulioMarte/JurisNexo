from datetime import date

import pytest

from jurisnexo.ingestion.scj_layouts import (
    LayoutDetectionStatus,
    SCJLayoutFamily,
    detect_scj_page_layout,
)
from jurisnexo.ingestion.scj_metadata import MetadataObservation, parse_scj_page_metadata
from jurisnexo.ingestion.scj_segmentation import segment_scj_pages

pytestmark = pytest.mark.unit


OLD_2024_SENTENCE = """\
Principales Decisiones de la Suprema Corte de Justicia 2024
ENERO - ABRIL

SENTENCIA DEL 29 DE FEBRERO DE 2024, NÚM. SCJ-SS-24-0138

Sentencia impugnada: Segunda Sala de la Cámara Penal de la Corte de Apelación
Materia: Penal.
Recurrentes: Mariano Antonio Vásquez González y Marino Antonio Vásquez González.

En nombre de la República, la Segunda Sala de la Suprema Corte de Justicia,
hoy 29 de febrero de 2024, dicta en audiencia pública la siguiente sentencia.
"""

OLD_2023_RESOLUTION = """\
Casación; Efecto suspensivo. Pleno. 07/02/2023. Decisión íntegra.

RESOLUCIÓN NÚM. 62-2023, SOBRE PROCEDIMIENTO PARA LA INTER-
POSICIÓN Y JUZGAMIENTO DE LAS DEMANDAS EN SUSPENSIÓN DE LA
EJECUCIÓN DE SENTENCIA RECURRIDA EN CASACIÓN.

En nombre de la República, EL PLENO DE LA SUPREMA CORTE DE JUSTICIA,
dicta en cámara de consejo la siguiente resolución.
"""

MODERN_PRIMERA = """\
REPÚBLICA DOMINICANA
SUPREMA CORTE DE JUSTICIA
SCJ-PS-25-0905
Exps. núms. 2014-3935 y 2014-4025 (fusionados)
Partes: Normand Masse vs. Virgilio A. Méndez Amaro
Materia: Impugnación de auto que aprueba estado de gastos y honorarios
Decisión: ACOGE
Ponente: Mag. Vanessa Acosta Peralta

La PRIMERA SALA DE LA SUPREMA CORTE DE JUSTICIA, en fecha 30 de abril de 2025,
dicta la siguiente sentencia.
"""

MODERN_SEGUNDA = """\
REPÚBLICA DOMINICANA
SUPREMA CORTE DE JUSTICIA
Exp. 057-2022-EPEN-00173
Rc. Virgilio Francisco Peña
Fecha: 28 de febrero de 2025

Sentencia núm. SCJ-SS-25-0101
"""

MODERN_TERCERA_WITH_INCIDENTAL_PS_CITATION = """\
REPÚBLICA DOMINICANA
SUPREMA CORTE DE JUSTICIA
Exp. núm.: 001-011-2021-RECA-02294
Recurrente principal: Entidad Ejemplo
Recurrido principal: Persona Ejemplo
Materia: Contencioso administrativo
Decisión: Rechaza
SCJ-TS-25-0990

En un precedente anterior SCJ-PS-23-1258 se indicó otra cuestión distinta.
"""

MODERN_PLENO = """\
PODER JUDICIAL
REPÚBLICA DOMINICANA
SUPREMA CORTE DE JUSTICIA
Resolución núm. 9-2025
Expediente núm.: 2023-0125284
Conflicto de competencia entre dos tribunales.
Ponente: Magdo. Francisco A. Jerez Mena

En nombre de la República, el PLENO DE LA SUPREMA CORTE DE JUSTICIA,
en fecha 6 del mes de marzo del año 2025, dicta en cámara de consejo,
la resolución siguiente.
"""


def test_detects_old_formal_sentence_heading_and_date() -> None:
    detection = detect_scj_page_layout(OLD_2024_SENTENCE, page_number=16)

    assert detection.status is LayoutDetectionStatus.RECOGNIZED
    assert detection.family is SCJLayoutFamily.PRINCIPALES_2023_2024_SENTENCE
    assert detection.signature_key == "SCJ-SS-24-0138"
    assert detection.primary_decision_number == "SCJ-SS-24-0138"
    assert detection.header_date == date(2024, 2, 29)


def test_detects_old_uppercase_resolution_without_matching_body_citations() -> None:
    detection = detect_scj_page_layout(OLD_2023_RESOLUTION, page_number=98)
    body_citation = detect_scj_page_layout(
        "El tribunal confirmó la resolución núm. 001-2024-SRES-0001.",
        page_number=99,
    )

    assert detection.family is SCJLayoutFamily.PRINCIPALES_2023_2024_RESOLUTION
    assert detection.signature_key == "62-2023"
    assert body_citation.family is SCJLayoutFamily.UNKNOWN


def test_detects_each_observed_2025_layout_family() -> None:
    primera = detect_scj_page_layout(MODERN_PRIMERA, page_number=14)
    segunda = detect_scj_page_layout(MODERN_SEGUNDA, page_number=168)
    tercera = detect_scj_page_layout(
        MODERN_TERCERA_WITH_INCIDENTAL_PS_CITATION, page_number=117
    )
    pleno = detect_scj_page_layout(MODERN_PLENO, page_number=262)

    assert primera.family is SCJLayoutFamily.PRINCIPALES_2025_PRIMERA_SALA
    assert segunda.family is SCJLayoutFamily.PRINCIPALES_2025_SEGUNDA_SALA
    assert tercera.family is SCJLayoutFamily.PRINCIPALES_2025_TERCERA_SALA
    assert pleno.family is SCJLayoutFamily.PRINCIPALES_2025_PLENO_RESOLUTION
    assert tercera.primary_decision_number == "SCJ-TS-25-0990"
    assert segunda.header_date == date(2025, 2, 28)


def test_incidental_scj_reference_does_not_replace_primary_case_identity() -> None:
    observations = parse_scj_page_metadata(
        MODERN_TERCERA_WITH_INCIDENTAL_PS_CITATION, page_number=117
    )
    numbers = [
        item.normalized_text
        for item in observations
        if item.field_name == "decision_number"
    ]

    assert numbers == ["SCJ-TS-25-0990"]


def test_metadata_extractor_emits_header_date_dockets_and_organ() -> None:
    observations = parse_scj_page_metadata(MODERN_SEGUNDA, page_number=168)
    by_field: dict[str, list[MetadataObservation]] = {}
    for observation in observations:
        by_field.setdefault(observation.field_name, []).append(observation)

    assert by_field["decision_number"][0].normalized_text == "SCJ-SS-25-0101"
    assert by_field["docket_number"][0].normalized_text == "057-2022-EPEN-00173"
    assert by_field["decision_date_candidate"][0].normalized_date == date(2025, 2, 28)
    assert by_field["court_organ"][0].normalized_text == "Segunda Sala"


def test_multiple_dockets_are_emitted_as_distinct_observations() -> None:
    observations = parse_scj_page_metadata(MODERN_PRIMERA, page_number=14)
    dockets = [
        item.normalized_text
        for item in observations
        if item.field_name == "docket_number"
    ]

    assert dockets == ["2014-3935", "2014-4025"]


def test_old_publication_segmentation_uses_case_start_headings() -> None:
    pages = [
        "front matter",
        OLD_2024_SENTENCE,
        "continuation page without another formal heading",
        OLD_2024_SENTENCE.replace("SCJ-SS-24-0138", "SCJ-SS-24-0139").replace(
            "29 DE FEBRERO", "27 DE MARZO"
        ),
    ]

    segments, _ = segment_scj_pages(pages)

    assert [(item.start_page, item.end_page) for item in segments] == [(2, 3), (4, 4)]


def test_modern_repeated_header_segmentation_bridges_small_same_identity_gap() -> None:
    pages = [MODERN_SEGUNDA, "", MODERN_SEGUNDA]

    segments, detections = segment_scj_pages(pages, bridge_unknown_pages=1)

    assert len(segments) == 1
    assert (segments[0].start_page, segments[0].end_page) == (1, 3)
    assert detections[1].signature_key == detections[0].signature_key
    assert "bridged_unknown_page" in detections[1].evidence


def test_unknown_gap_between_different_modern_cases_is_not_bridged() -> None:
    other = MODERN_SEGUNDA.replace("057-2022-EPEN-00173", "057-2022-EPEN-00999")
    pages = [MODERN_SEGUNDA, "", other]

    segments, detections = segment_scj_pages(pages, bridge_unknown_pages=1)

    assert len(segments) == 2
    assert detections[1].family is SCJLayoutFamily.UNKNOWN
