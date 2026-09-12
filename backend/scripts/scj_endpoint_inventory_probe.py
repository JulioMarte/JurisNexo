from __future__ import annotations

import json
import os
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

LANDING = "https://consultasentenciascj.poderjudicial.gob.do/"
ENDPOINT = "https://consultasentenciascj.poderjudicial.gob.do/Home/GetExpedientes"
OUT = Path(os.environ.get("SCJ_ENDPOINT_PROBE_OUTPUT", "scj-endpoint-probe-output"))
DOCUMENT_TYPES = {
    "1": "Decisiones",
    "3": "Boletín",
    "4": "Sentencias Históricas",
    "5": "Expedientes Incompletos",
    "6": "Expedientes de revisión constitucional incompleto",
}


def configure_telemetry() -> None:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "jurisnexo-scj-endpoint-probe",
                "service.version": os.environ.get("GITHUB_SHA", "local"),
                "deployment.environment.name": "github-actions",
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def datatables_form(*, document_type: str, start: int, length: int, year: str) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = [("draw", "1")]
    for column in range(4):
        prefix = f"columns[{column}]"
        fields.extend(
            [
                (f"{prefix}[data]", ""),
                (f"{prefix}[name]", ""),
                (f"{prefix}[searchable]", "true"),
                (f"{prefix}[orderable]", "false"),
                (f"{prefix}[search][value]", ""),
                (f"{prefix}[search][regex]", "false"),
            ]
        )
    fields.extend(
        [
            ("start", str(start)),
            ("length", str(length)),
            ("search[value]", ""),
            ("search[regex]", "false"),
            ("IdTribunal", ""),
            ("Materia", ""),
            ("Ano", year),
            ("Mes", ""),
            ("IdTipoDocumento", document_type),
            ("Contenido", ""),
        ]
    )
    return fields


class ScjSession:
    def __init__(self) -> None:
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def bootstrap(self) -> None:
        request = Request(
            LANDING,
            headers={
                "User-Agent": "JurisNexo-SCJ-Acquisition-Probe/0.1",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with self.opener.open(request, timeout=90) as response:  # noqa: S310
            if response.status != 200:
                raise RuntimeError(f"SCJ landing returned HTTP {response.status}")
            response.read(1024)

    def query(
        self,
        *,
        document_type: str,
        start: int = 0,
        length: int = 1,
        year: str = "",
    ) -> dict[str, object]:
        payload = urlencode(
            datatables_form(document_type=document_type, start=start, length=length, year=year)
        ).encode("utf-8")
        request = Request(
            ENDPOINT,
            data=payload,
            method="POST",
            headers={
                "User-Agent": "JurisNexo-SCJ-Acquisition-Probe/0.1",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://consultasentenciascj.poderjudicial.gob.do",
                "Referer": LANDING,
            },
        )
        with self.opener.open(request, timeout=90) as response:  # noqa: S310
            body = response.read()
            if response.status != 200:
                raise RuntimeError(f"SCJ endpoint returned HTTP {response.status}")
        decoded = json.loads(body)
        if not isinstance(decoded, dict):
            raise TypeError("SCJ endpoint did not return an object")
        return decoded


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    configure_telemetry()
    tracer = trace.get_tracer("jurisnexo.scj.endpoint")
    results: dict[str, object] = {}
    session = ScjSession()

    with tracer.start_as_current_span("scj.endpoint.inventory_probe") as root:
        root.set_attribute("server.address", "consultasentenciascj.poderjudicial.gob.do")
        with tracer.start_as_current_span("scj.endpoint.bootstrap") as span:
            session.bootstrap()
            span.set_attribute("scj.session.cookie_count", len(session.cookies))

        with tracer.start_as_current_span("scj.endpoint.prime") as span:
            prime = session.query(document_type="", length=10, year="-1")
            span.set_attribute("scj.prime.records.filtered", int(prime.get("recordsFiltered", 0)))
            span.set_attribute("scj.session.cookie_count", len(session.cookies))

        total_across_types = 0
        for document_type, label in DOCUMENT_TYPES.items():
            with tracer.start_as_current_span("scj.endpoint.count") as span:
                span.set_attribute("scj.document_type.id", document_type)
                span.set_attribute("scj.document_type.name", label)
                response = session.query(document_type=document_type)
                total = int(response.get("recordsFiltered", 0))
                rows = response.get("data", [])
                if not isinstance(rows, list):
                    raise TypeError("SCJ endpoint data is not a list")
                sample = rows[0] if rows else None
                results[document_type] = {
                    "label": label,
                    "recordsTotal": int(response.get("recordsTotal", 0)),
                    "recordsFiltered": total,
                    "sample": sample,
                }
                total_across_types += total
                span.set_attribute("scj.records.filtered", total)
                span.set_attribute("scj.sample.present", sample is not None)

        checks: dict[str, object] = {}
        for year in ("1910", "1980", "2006", "2025", "2026"):
            response = session.query(document_type="1", year=year)
            rows = response.get("data", [])
            if not isinstance(rows, list):
                raise TypeError("SCJ endpoint data is not a list")
            checks[year] = {
                "recordsFiltered": int(response.get("recordsFiltered", 0)),
                "sample": rows[0] if rows else None,
            }
        results["decision_year_checks"] = checks
        results["total_across_types"] = total_across_types
        results["cookie_count"] = len(session.cookies)
        root.set_attribute("scj.records.total_across_types", total_across_types)

    (OUT / "inventory-probe.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
