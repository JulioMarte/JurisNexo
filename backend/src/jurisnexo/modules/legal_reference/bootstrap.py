from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from jurisnexo.platform.db.connection import ConnectionFactory

BOOTSTRAP_VERSION = 1


@dataclass(frozen=True, slots=True)
class JurisdictionSeed:
    code: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class CourtSeed:
    code: str
    name: str
    short_name: str
    jurisdiction: str
    judicial_system: str
    court_type: str


@dataclass(frozen=True, slots=True)
class OrganSeed:
    court_code: str
    code: str
    name: str
    organ_type: str


@dataclass(frozen=True, slots=True)
class SourceSeed:
    code: str
    name: str
    institution: str
    authority_class: str
    base_locator: str


@dataclass(frozen=True, slots=True)
class CollectionSeed:
    source_code: str
    code: str
    document_kind: str
    acquisition_policy: str
    agent_visibility: str


JURISDICTIONS = (
    JurisdictionSeed("ordinary", "Jurisdicción ordinaria", "Jurisdicción judicial ordinaria."),
    JurisdictionSeed(
        "constitutional",
        "Jurisdicción constitucional",
        "Control y justicia constitucional ejercidos por el Tribunal Constitucional.",
    ),
    JurisdictionSeed("civil_commercial", "Civil y comercial", "Materia civil y comercial."),
    JurisdictionSeed("criminal", "Penal", "Materia penal."),
    JurisdictionSeed("labor", "Laboral", "Materia laboral."),
    JurisdictionSeed("land", "Tierras", "Jurisdicción inmobiliaria y de tierras."),
    JurisdictionSeed("administrative", "Contencioso-administrativa", "Materia administrativa."),
    JurisdictionSeed(
        "juvenile",
        "Niños, niñas y adolescentes",
        "Jurisdicción especializada de niños, niñas y adolescentes.",
    ),
    JurisdictionSeed("peace", "Juzgados de paz", "Competencias propias de juzgados de paz."),
)

COURTS = (
    CourtSeed(
        code="DO-SCJ",
        name="Suprema Corte de Justicia",
        short_name="SCJ",
        jurisdiction="República Dominicana",
        judicial_system="ordinary_judiciary",
        court_type="supreme",
    ),
    CourtSeed(
        code="DO-TC",
        name="Tribunal Constitucional",
        short_name="TC",
        jurisdiction="República Dominicana",
        judicial_system="constitutional_jurisdiction",
        court_type="constitutional",
    ),
)

COURT_JURISDICTIONS = (
    ("DO-SCJ", "ordinary", True),
    ("DO-TC", "constitutional", True),
)

ORGANS = (
    OrganSeed("DO-SCJ", "PLENO", "Pleno", "pleno"),
    OrganSeed("DO-SCJ", "PRIMERA_SALA", "Primera Sala", "sala"),
    OrganSeed("DO-SCJ", "SEGUNDA_SALA", "Segunda Sala", "sala"),
    OrganSeed("DO-SCJ", "TERCERA_SALA", "Tercera Sala", "sala"),
    OrganSeed("DO-SCJ", "SALAS_REUNIDAS", "Salas Reunidas", "salas_reunidas"),
    OrganSeed("DO-TC", "PLENO", "Pleno", "pleno"),
)

SOURCES = (
    SourceSeed(
        code="scj",
        name="Consulta de Sentencias de la Suprema Corte de Justicia",
        institution="Poder Judicial de la República Dominicana",
        authority_class="official_primary",
        base_locator="https://consultasentenciascj.poderjudicial.gob.do/",
    ),
    SourceSeed(
        code="tc",
        name="Portal oficial del Tribunal Constitucional",
        institution="Tribunal Constitucional de la República Dominicana",
        authority_class="official_primary",
        base_locator="https://tribunalconstitucional.gob.do/",
    ),
)

COLLECTIONS = (
    CollectionSeed("scj", "principales-sentencias", "judicial_decision", "enabled", "hidden"),
    CollectionSeed("scj", "decisiones", "judicial_decision", "enabled", "hidden"),
    CollectionSeed(
        "scj",
        "boletin-judicial",
        "judicial_decision_compilation",
        "catalog_only",
        "hidden",
    ),
    CollectionSeed("scj", "sentencias-historicas", "judicial_decision", "catalog_only", "hidden"),
    CollectionSeed("tc", "sentencias", "judicial_decision", "catalog_only", "hidden"),
)

COURT_ALIASES = (
    ("DO-SCJ", "scj", "Suprema Corte de Justicia", "suprema corte de justicia", "official_name"),
    ("DO-SCJ", "scj", "SCJ", "scj", "abbreviation"),
    ("DO-TC", "tc", "Tribunal Constitucional", "tribunal constitucional", "official_name"),
    ("DO-TC", "tc", "TC", "tc", "abbreviation"),
)

ORGAN_ALIASES = (
    ("DO-SCJ", "PRIMERA_SALA", "scj", "Primera Sala", "primera sala", "official_name"),
    ("DO-SCJ", "SEGUNDA_SALA", "scj", "Segunda Sala", "segunda sala", "official_name"),
    ("DO-SCJ", "TERCERA_SALA", "scj", "Tercera Sala", "tercera sala", "official_name"),
    ("DO-SCJ", "SALAS_REUNIDAS", "scj", "Salas Reunidas", "salas reunidas", "official_name"),
)


def _require_schema(cursor: Any) -> None:
    cursor.execute(
        """
        SELECT to_regclass('corpus.courts'),
               to_regclass('corpus.jurisdictions'),
               to_regclass('corpus.source_collections')
        """
    )
    row = cursor.fetchone()
    if row is None or any(value is None for value in row):
        raise RuntimeError("database schema is not at the JurisNexo bootstrap-compatible head")


def _ids_by_code(cursor: Any, table: str, codes: tuple[str, ...]) -> dict[str, UUID]:
    if table not in {"courts", "source_registries"}:
        raise ValueError("unsupported bootstrap id table")
    cursor.execute(
        f"SELECT code, id FROM corpus.{table} WHERE code = ANY(%s)",  # noqa: S608
        (list(codes),),
    )
    rows = cursor.fetchall()
    result = {str(row["code"]): row["id"] for row in rows}
    missing = sorted(set(codes) - set(result))
    if missing:
        raise RuntimeError(f"bootstrap failed to resolve {table}: {', '.join(missing)}")
    return result


def apply_database_bootstrap(connection_factory: ConnectionFactory) -> None:
    """Apply the idempotent legal-system bootstrap to an already migrated database.

    Stable reference facts are reconciled to the versioned bootstrap definition.
    Mutable operator policy on an existing source collection is deliberately not
    overwritten when the command is re-run.
    """

    with (
        connection_factory() as connection,
        connection.transaction(),
        connection.cursor(row_factory=dict_row) as cursor,
    ):
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext('jurisnexo.database.bootstrap.v1'))")
        _require_schema(cursor)

        for seed in JURISDICTIONS:
            cursor.execute(
                """
                INSERT INTO corpus.jurisdictions (code, name, description)
                VALUES (%s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description
                """,
                (seed.code, seed.name, seed.description),
            )

        for seed in COURTS:
            cursor.execute(
                """
                INSERT INTO corpus.courts (
                    code, name, short_name, jurisdiction, country_code,
                    judicial_system, court_type
                ) VALUES (%s, %s, %s, %s, 'DO', %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    short_name = EXCLUDED.short_name,
                    jurisdiction = EXCLUDED.jurisdiction,
                    country_code = EXCLUDED.country_code,
                    judicial_system = EXCLUDED.judicial_system,
                    court_type = EXCLUDED.court_type
                """,
                (
                    seed.code,
                    seed.name,
                    seed.short_name,
                    seed.jurisdiction,
                    seed.judicial_system,
                    seed.court_type,
                ),
            )

        court_ids = _ids_by_code(cursor, "courts", tuple(seed.code for seed in COURTS))

        for court_code, jurisdiction_code, is_primary in COURT_JURISDICTIONS:
            cursor.execute(
                """
                INSERT INTO corpus.court_jurisdictions (
                    court_id, jurisdiction_code, is_primary
                ) VALUES (%s, %s, %s)
                ON CONFLICT (court_id, jurisdiction_code) DO UPDATE SET
                    is_primary = EXCLUDED.is_primary
                """,
                (court_ids[court_code], jurisdiction_code, is_primary),
            )

        for seed in SOURCES:
            cursor.execute(
                """
                INSERT INTO corpus.source_registries (
                    code, name, institution, authority_class, base_locator
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    institution = EXCLUDED.institution,
                    authority_class = EXCLUDED.authority_class,
                    base_locator = EXCLUDED.base_locator
                """,
                (
                    seed.code,
                    seed.name,
                    seed.institution,
                    seed.authority_class,
                    seed.base_locator,
                ),
            )

        source_ids = _ids_by_code(cursor, "source_registries", tuple(seed.code for seed in SOURCES))

        for seed in ORGANS:
            cursor.execute(
                """
                INSERT INTO corpus.court_organs (court_id, code, name, organ_type)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (court_id, code) DO UPDATE SET
                    name = EXCLUDED.name,
                    organ_type = EXCLUDED.organ_type
                """,
                (court_ids[seed.court_code], seed.code, seed.name, seed.organ_type),
            )

        cursor.execute(
            """
            SELECT c.code AS court_code, co.code AS organ_code, co.id
            FROM corpus.court_organs co
            JOIN corpus.courts c ON c.id = co.court_id
            WHERE c.code = ANY(%s)
            """,
            (list(court_ids),),
        )
        organ_ids = {
            (str(row["court_code"]), str(row["organ_code"])): row["id"]
            for row in cursor.fetchall()
        }

        for court_code, source_code, alias, normalized, alias_kind in COURT_ALIASES:
            cursor.execute(
                """
                INSERT INTO corpus.court_aliases (
                    court_id, alias, normalized_alias, alias_kind, source_registry_id
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (
                    court_id, normalized_alias, alias_kind, source_registry_id
                ) DO UPDATE SET alias = EXCLUDED.alias
                """,
                (
                    court_ids[court_code],
                    alias,
                    normalized,
                    alias_kind,
                    source_ids[source_code],
                ),
            )

        for (
            court_code,
            organ_code,
            source_code,
            alias,
            normalized,
            alias_kind,
        ) in ORGAN_ALIASES:
            cursor.execute(
                """
                INSERT INTO corpus.court_organ_aliases (
                    court_organ_id, alias, normalized_alias, alias_kind, source_registry_id
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (
                    court_organ_id, normalized_alias, alias_kind, source_registry_id
                ) DO UPDATE SET alias = EXCLUDED.alias
                """,
                (
                    organ_ids[(court_code, organ_code)],
                    alias,
                    normalized,
                    alias_kind,
                    source_ids[source_code],
                ),
            )

        for seed in COLLECTIONS:
            cursor.execute(
                """
                INSERT INTO corpus.source_collections (
                    source_registry_id, code, document_kind,
                    acquisition_policy, agent_visibility
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (source_registry_id, code) DO UPDATE SET
                    document_kind = EXCLUDED.document_kind
                """,
                (
                    source_ids[seed.source_code],
                    seed.code,
                    seed.document_kind,
                    seed.acquisition_policy,
                    seed.agent_visibility,
                ),
            )


def verify_database_bootstrap(connection_factory: ConnectionFactory) -> dict[str, int]:
    """Fail unless every bootstrap-managed business key and stable classification exists."""

    with connection_factory() as connection, connection.cursor(row_factory=dict_row) as cursor:
        _require_schema(cursor)

        expected_courts = {seed.code: seed for seed in COURTS}
        cursor.execute(
            """
            SELECT code, name, short_name, jurisdiction, country_code,
                   judicial_system, court_type
            FROM corpus.courts
            WHERE code = ANY(%s)
            """,
            (list(expected_courts),),
        )
        court_rows = {str(row["code"]): row for row in cursor.fetchall()}
        if set(court_rows) != set(expected_courts):
            raise RuntimeError("database bootstrap court set is incomplete")
        for code, seed in expected_courts.items():
            row = court_rows[code]
            actual = (
                row["name"],
                row["short_name"],
                row["jurisdiction"],
                row["country_code"],
                row["judicial_system"],
                row["court_type"],
            )
            expected = (
                seed.name,
                seed.short_name,
                seed.jurisdiction,
                "DO",
                seed.judicial_system,
                seed.court_type,
            )
            if actual != expected:
                raise RuntimeError(f"database bootstrap court drift detected: {code}")

        cursor.execute(
            "SELECT code FROM corpus.jurisdictions WHERE code = ANY(%s)",
            (list(seed.code for seed in JURISDICTIONS),),
        )
        actual_jurisdictions = {str(row["code"]) for row in cursor.fetchall()}
        expected_jurisdictions = {seed.code for seed in JURISDICTIONS}
        if actual_jurisdictions != expected_jurisdictions:
            raise RuntimeError("database bootstrap jurisdiction set is incomplete")

        expected_sources = {seed.code for seed in SOURCES}
        cursor.execute(
            "SELECT code FROM corpus.source_registries WHERE code = ANY(%s)",
            (list(expected_sources),),
        )
        actual_sources = {str(row["code"]) for row in cursor.fetchall()}
        if actual_sources != expected_sources:
            raise RuntimeError("database bootstrap source registry set is incomplete")

        expected_collections = {(seed.source_code, seed.code) for seed in COLLECTIONS}
        cursor.execute(
            """
            SELECT sr.code AS source_code, sc.code AS collection_code
            FROM corpus.source_collections sc
            JOIN corpus.source_registries sr ON sr.id = sc.source_registry_id
            WHERE sr.code = ANY(%s)
            """,
            (list(expected_sources),),
        )
        actual_collections = {
            (str(row["source_code"]), str(row["collection_code"]))
            for row in cursor.fetchall()
        }
        if not expected_collections <= actual_collections:
            raise RuntimeError("database bootstrap source collection set is incomplete")

        return {
            "bootstrap_version": BOOTSTRAP_VERSION,
            "courts": len(expected_courts),
            "jurisdictions": len(expected_jurisdictions),
            "sources": len(expected_sources),
            "collections": len(expected_collections),
            "organs": len(ORGANS),
        }
