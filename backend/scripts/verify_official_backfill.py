from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

import boto3
import psycopg
from botocore.config import Config

from jurisnexo.acquisition.official_corpus import SourceName, object_key_for

Source = Literal["supreme_court", "constitutional_court"]
REQUIRED_ENV = (
    "DATABASE_URL",
    "JURISNEXO_S3_BUCKET",
    "JURISNEXO_S3_ENDPOINT_URL",
    "JURISNEXO_S3_REGION",
    "JURISNEXO_S3_ACCESS_KEY_ID",
    "JURISNEXO_S3_SECRET_ACCESS_KEY",
    "BACKFILL_VERIFY_SOURCE",
    "BACKFILL_VERIFY_INVENTORY",
    "BACKFILL_VERIFY_OUTPUT",
)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"", "0", "false", "no", "off"}


def require_environment() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("missing backfill verification configuration: " + ", ".join(missing))


def scj_identity(record: dict[str, Any]) -> tuple[str, str, str]:
    row = record.get("row")
    if not isinstance(row, dict):
        raise TypeError("SCJ inventory record is missing row")
    surface = str(record.get("surface") or "")
    if surface == "decisions":
        expediente_id = str(row.get("idExpediente") or "").strip()
        guid_blob = str(row.get("guidBlob") or "").strip()
        source_identifier = f"expediente:{expediente_id}"
        if guid_blob:
            source_identifier += f":{guid_blob}"
        return source_identifier, "decisions", str(row.get("urlBlob") or "").strip()
    if surface == "historical":
        year = str(row.get("ano") or "").strip()
        month = str(row.get("mes") or "").strip()
        parties = " ".join(str(row.get("partes") or "").split())
        return (
            f"historical:{year}:{month}:{parties}",
            "historical-decisions",
            str(row.get("rutaDoc") or "").strip(),
        )
    if surface == "bulletins":
        body_id = str(row.get("idCuerpo") or "").strip()
        header_id = str(row.get("idCabecera") or "").strip()
        return (
            f"bulletin:{header_id}:{body_id}",
            "bulletins",
            str(row.get("urlCuerpo") or "").strip(),
        )
    raise ValueError(f"unsupported SCJ inventory surface: {surface!r}")


def expected_inventory(source: Source, path: Path) -> dict[tuple[str, str], str | None]:
    expected: dict[tuple[str, str], str | None] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError("inventory JSONL contains a non-object record")
            if source == "supreme_court":
                identifier, collection, document_url = scj_identity(value)
                key = (identifier, collection)
                previous = expected.get(key)
                if previous is not None and previous != document_url:
                    raise RuntimeError(f"SCJ logical identity maps to multiple current URLs: {key}")
                expected[key] = document_url
            else:
                identifier = str(value.get("source_identifier") or "").strip()
                collection = str(value.get("collection") or "decisions").strip()
                if not identifier:
                    raise ValueError("TC inventory record lacks source_identifier")
                expected[(identifier, collection)] = None
    if not expected:
        raise RuntimeError("verification inventory is empty")
    return expected


def s3_client() -> Any:
    force_path_style = _env_flag("JURISNEXO_S3_FORCE_PATH_STYLE", True)
    return boto3.client(
        "s3",
        endpoint_url=os.environ["JURISNEXO_S3_ENDPOINT_URL"],
        region_name=os.environ["JURISNEXO_S3_REGION"],
        aws_access_key_id=os.environ["JURISNEXO_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["JURISNEXO_S3_SECRET_ACCESS_KEY"],
        config=Config(s3={"addressing_style": "path" if force_path_style else "virtual"}),
    )


def list_s3_keys(client: Any, *, prefix: str) -> set[str]:
    keys: set[str] = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=os.environ["JURISNEXO_S3_BUCKET"], Prefix=prefix):
        for item in page.get("Contents", []):
            key = str(item.get("Key") or "")
            if key:
                keys.add(key)
    return keys


def main() -> None:
    require_environment()
    source_value = os.environ["BACKFILL_VERIFY_SOURCE"]
    if source_value not in {"supreme_court", "constitutional_court"}:
        raise ValueError(f"unsupported verification source: {source_value}")
    source: Source = source_value  # type: ignore[assignment]
    inventory = expected_inventory(source, Path(os.environ["BACKFILL_VERIFY_INVENTORY"]))
    output = Path(os.environ["BACKFILL_VERIFY_OUTPUT"])
    output.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select l.source_identifier,
                       l.source_collection,
                       l.locator,
                       a.sha256,
                       l.last_seen_at
                from corpus.source_artifact_locations l
                join corpus.source_registries r on r.id = l.source_registry_id
                join corpus.source_artifacts a on a.id = l.artifact_id
                where r.code = %s
                  and l.locator_type = 'official_url'
                  and l.source_identifier is not null
                  and l.source_collection is not null
                order by l.last_seen_at desc
                """,
                (source,),
            )
            rows = cursor.fetchall()

    latest: dict[tuple[str, str], tuple[str, str]] = {}
    for source_identifier, collection, locator, sha256, _last_seen_at in rows:
        key = (str(source_identifier), str(collection))
        latest.setdefault(key, (str(locator), str(sha256)))

    missing_database: list[dict[str, str]] = []
    url_mismatches: list[dict[str, str]] = []
    expected_object_keys: dict[tuple[str, str], str] = {}
    for key, expected_url in inventory.items():
        current = latest.get(key)
        if current is None:
            missing_database.append({"source_identifier": key[0], "collection": key[1]})
            continue
        current_url, digest = current
        if expected_url is not None and current_url != expected_url:
            url_mismatches.append(
                {
                    "source_identifier": key[0],
                    "collection": key[1],
                    "expected_url": expected_url,
                    "database_url": current_url,
                }
            )
        expected_object_keys[key] = object_key_for(
            source=source,  # type: ignore[arg-type]
            collection=key[1],
            sha256=digest,
        )

    prefix = "jurisdictions/do/scj/" if source == "supreme_court" else "jurisdictions/do/tc/"
    stored_keys = list_s3_keys(s3_client(), prefix=prefix)
    missing_storage = [
        {"source_identifier": key[0], "collection": key[1], "object_key": object_key}
        for key, object_key in expected_object_keys.items()
        if object_key not in stored_keys
    ]

    status = "COMPLETE" if not missing_database and not url_mismatches and not missing_storage else "INCOMPLETE"
    summary = {
        "status": status,
        "source": source,
        "expected_document_count": len(inventory),
        "database_matched_count": len(inventory) - len(missing_database),
        "s3_matched_count": len(expected_object_keys) - len(missing_storage),
        "missing_database_count": len(missing_database),
        "url_mismatch_count": len(url_mismatches),
        "missing_storage_count": len(missing_storage),
        "observed_s3_object_count_under_source_prefix": len(stored_keys),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output / "missing-database.json").write_text(
        json.dumps(missing_database, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output / "url-mismatches.json").write_text(
        json.dumps(url_mismatches, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output / "missing-storage.json").write_text(
        json.dumps(missing_storage, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    if status != "COMPLETE":
        raise RuntimeError(f"{source} backfill verification is incomplete")


if __name__ == "__main__":
    main()
