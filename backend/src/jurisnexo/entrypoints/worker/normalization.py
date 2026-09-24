from __future__ import annotations

import argparse
import hashlib
import json
from typing import Any, cast

from jurisnexo.acquisition.manifest import parse_acquisition_run_manifest
from jurisnexo.acquisition.s3_object_store import S3ObjectStore, build_s3_object_store
from jurisnexo.bootstrap.settings import get_postgres_settings
from jurisnexo.normalization.adapters.pdf_native_text import PdfNativeTextReferenceExtractor
from jurisnexo.normalization.adapters.tika import TikaServerFormatInspector
from jurisnexo.normalization.executor import NormalizationExecutor
from jurisnexo.normalization.finalizer import NormalizationFinalizer
from jurisnexo.normalization.isolated_docling import IsolatedDoclingStructuralNormalizer
from jurisnexo.normalization.planner import build_normalization_plan
from jurisnexo.normalization.recovery import CircuitBreaker
from jurisnexo.normalization.repository import PostgresNormalizationLedger
from jurisnexo.normalization.s3_source_reader import S3SourceByteReader
from jurisnexo.normalization.source_fidelity import DeterministicSourceFidelityChecker
from jurisnexo.platform.db.connection import (
    PostgresConnectionConfig,
    build_connection_factory,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute and finalize one durable JurisNexo normalization run."
    )
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--manifest-key", required=True)
    parser.add_argument("--pipeline-version", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--resume-run-id")
    parser.add_argument("--tika-url", default="http://127.0.0.1:9998")
    parser.add_argument("--ocr-language", action="append", default=[])
    parser.add_argument("--docling-timeout-seconds", type=float, default=180.0)
    parser.add_argument(
        "--docling-max-source-bytes",
        type=int,
        default=100 * 1024 * 1024,
    )
    parser.add_argument(
        "--docling-max-output-bytes",
        type=int,
        default=250 * 1024 * 1024,
    )
    parser.add_argument("--circuit-breaker-threshold", type=int, default=5)
    return parser


def read_manifest(store: S3ObjectStore, key: str) -> tuple[bytes, dict[str, str]]:
    client = cast(Any, store.client)
    response = cast(
        dict[str, object],
        client.get_object(Bucket=store.config.bucket, Key=key),
    )
    body = cast(Any, response["Body"])
    raw_payload: object = body.read()
    payload = (
        raw_payload
        if isinstance(raw_payload, bytes)
        else bytes(cast(Any, raw_payload))
    )
    metadata_raw = response.get("Metadata", {})
    if isinstance(metadata_raw, dict):
        metadata_map = cast(dict[object, object], metadata_raw)
        metadata = {str(k): str(v) for k, v in metadata_map.items()}
    else:
        metadata = {}
    expected_sha = metadata.get("payload_sha256")
    actual_sha = hashlib.sha256(payload).hexdigest()
    if expected_sha and expected_sha != actual_sha:
        raise RuntimeError(
            "acquisition manifest payload hash disagrees with S3 metadata"
        )
    return payload, metadata


def _connection_factory() -> Any:
    settings = get_postgres_settings()
    return build_connection_factory(
        PostgresConnectionConfig(
            host=settings.host,
            port=settings.port,
            db=settings.db,
            user=settings.user,
            password=settings.password.get_secret_value(),
            sslmode=settings.sslmode,
        )
    )


def run(args: argparse.Namespace) -> dict[str, object]:
    _validate_args(args)

    store = build_s3_object_store()
    manifest_payload, _ = read_manifest(store, args.manifest_key)
    manifest = parse_acquisition_run_manifest(manifest_payload)
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    plan = build_normalization_plan(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        pipeline_version=args.pipeline_version,
        config_sha256=args.config_sha256,
    )

    connection_factory = _connection_factory()
    with connection_factory() as connection:
        ledger = PostgresNormalizationLedger(connection)
        executor = NormalizationExecutor(
            inspector=TikaServerFormatInspector(base_url=args.tika_url),
            normalizer=IsolatedDoclingStructuralNormalizer(
                timeout_seconds=args.docling_timeout_seconds,
                max_source_bytes=args.docling_max_source_bytes,
                max_output_bytes=args.docling_max_output_bytes,
                ocr_language_tags=tuple(args.ocr_language),
            ),
            source_reader=S3SourceByteReader(store),
            derived_store=store,
            ledger=ledger,
            pipeline_version=args.pipeline_version,
            config_sha256=args.config_sha256,
            circuit_breaker=CircuitBreaker(
                threshold=args.circuit_breaker_threshold
            ),
            source_fidelity=DeterministicSourceFidelityChecker(
                PdfNativeTextReferenceExtractor()
            ),
        )
        execution = executor.execute(
            plan=plan,
            scope_id=args.scope_id,
            manifest_locator=store.config.locator_for(args.manifest_key),
            resume_run_id=args.resume_run_id,
        )
        finalization = NormalizationFinalizer(
            ledger=ledger,
            object_store=store,
        ).finalize(
            plan=plan,
            run_id=execution.run_id,
            scope_id=args.scope_id,
            pipeline_version=args.pipeline_version,
            config_sha256=args.config_sha256,
        )

    return {
        "run_id": execution.run_id,
        "manifest_sha256": manifest_sha256,
        "selected": plan.selected_count,
        "normalized": execution.normalized,
        "reused": execution.reused,
        "review_required": execution.review_required,
        "failed": execution.failed,
        "final_status": finalization.status,
        "normalization_manifest_sha256": finalization.manifest_sha256,
        "normalization_manifest_object_key": finalization.manifest_object_key,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["final_status"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
