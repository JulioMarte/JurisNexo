from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from playwright.sync_api import Response, sync_playwright

TARGET = "https://consultasentenciascj.poderjudicial.gob.do/"
ENDPOINT = urljoin(TARGET, "/Home/GetExpedientes")
OUT = Path(os.environ.get("SCJ_PROBE_OUTPUT", "scj-probe-output"))


def configure_telemetry() -> None:
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "jurisnexo-scj-live-probe",
                "service.version": os.environ.get("GITHUB_SHA", "local"),
                "deployment.environment.name": "github-actions",
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def datatables_form(*, start: int, length: int, document_type: str = "1") -> dict[str, str]:
    fields: dict[str, str] = {"draw": "1"}
    for column in range(4):
        prefix = f"columns[{column}]"
        fields.update(
            {
                f"{prefix}[data]": "",
                f"{prefix}[name]": "",
                f"{prefix}[searchable]": "true",
                f"{prefix}[orderable]": "false",
                f"{prefix}[search][value]": "",
                f"{prefix}[search][regex]": "false",
            }
        )
    fields.update(
        {
            "start": str(start),
            "length": str(length),
            "search[value]": "",
            "search[regex]": "false",
            "IdTribunal": "",
            "Materia": "",
            "Ano": "",
            "Mes": "",
            "IdTipoDocumento": document_type,
            "Contenido": "",
        }
    )
    return fields


def post_json(context: Any, path: str, form: dict[str, str]) -> dict[str, Any]:
    response = context.request.post(
        urljoin(TARGET, path),
        form=form,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": TARGET,
        },
        timeout=90_000,
    )
    if response.status != 200:
        raise RuntimeError(f"SCJ {path} returned HTTP {response.status}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError(f"SCJ {path} returned non-object JSON")
    return payload


def request_decisions(context: Any, *, start: int, length: int) -> dict[str, Any]:
    payload = post_json(context, "/Home/GetExpedientes", datatables_form(start=start, length=length))
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        raise TypeError("SCJ decisions data is not a list")
    return {
        "recordsTotal": int(payload.get("recordsTotal", 0)),
        "recordsFiltered": int(payload.get("recordsFiltered", 0)),
        "row_count": len(rows),
        "sample": rows[0] if rows else None,
    }


def surface_probe(context: Any) -> dict[str, Any]:
    decisions = request_decisions(context, start=0, length=10)
    bulletins = post_json(context, "/Home/GetBoletines", {"Ano": "", "Mes": ""})
    historical = post_json(
        context,
        "/Home/GetBoletinesHistorico",
        {
            **datatables_form(start=0, length=10, document_type=""),
            "Ano": "",
            "Mes": "",
            "Contenido": "",
        },
    )
    incomplete = post_json(
        context,
        "/Home/GetExpedienteIncompleto",
        {"Sala": "", "Materia": "", "Ano": "", "Mes": "", "Contenido": ""},
    )
    incomplete_constitutional = post_json(
        context,
        "/Home/GetExpedienteIncompletoConstitucional",
        {"Materia": "", "Contenido": ""},
    )

    def describe(payload: dict[str, Any]) -> dict[str, Any]:
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            raise TypeError("SCJ surface data is not a list")
        return {
            "recordsTotal": int(payload.get("recordsTotal", len(rows)) or 0),
            "recordsFiltered": int(payload.get("recordsFiltered", len(rows)) or 0),
            "row_count": len(rows),
            "sample": rows[0] if rows else None,
            "sample_keys": sorted(rows[0].keys()) if rows and isinstance(rows[0], dict) else [],
        }

    return {
        "decisions": decisions,
        "bulletins": describe(bulletins),
        "historical_sentences": describe(historical),
        "incomplete_cases": describe(incomplete),
        "incomplete_constitutional_cases": describe(incomplete_constitutional),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    configure_telemetry()
    tracer = trace.get_tracer("jurisnexo.scj.probe")
    network: list[dict[str, Any]] = []
    json_payloads: list[dict[str, Any]] = []

    with tracer.start_as_current_span("scj.browser.probe") as root:
        root.set_attribute("url.full", TARGET)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1200})
            page = context.new_page()

            def on_response(response: Response) -> None:
                request = response.request
                content_type = response.headers.get("content-type", "")
                item: dict[str, Any] = {
                    "method": request.method,
                    "resource_type": request.resource_type,
                    "url": response.url,
                    "status": response.status,
                    "content_type": content_type,
                    "post_data": request.post_data,
                }
                network.append(item)
                if "json" in content_type.casefold():
                    try:
                        body = response.body()
                        if len(body) <= 1_000_000:
                            json_payloads.append(
                                {
                                    "url": response.url,
                                    "request_post_data": request.post_data,
                                    "body": json.loads(body.decode("utf-8")),
                                }
                            )
                    except Exception as exc:
                        item["json_capture_error"] = repr(exc)

            page.on("response", on_response)
            response = page.goto(TARGET, wait_until="networkidle", timeout=120_000)
            if response is None or response.status != 200:
                raise RuntimeError("SCJ portal navigation failed")
            page.wait_for_timeout(2_000)

            script_src = page.locator('script[src*="JsConsulta.js"]').get_attribute("src")
            if script_src:
                script_response = context.request.get(urljoin(TARGET, script_src), timeout=60_000)
                (OUT / "JsConsulta.js").write_text(script_response.text(), encoding="utf-8")

            page.select_option("#cbTipoDocumento", "1")
            page.wait_for_timeout(3_000)

            surfaces = surface_probe(context)
            (OUT / "surface-probe.json").write_text(
                json.dumps(surfaces, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            root.set_attribute("scj.decisions.count", surfaces["decisions"]["recordsFiltered"])
            root.set_attribute("scj.bulletins.count", surfaces["bulletins"]["row_count"])
            root.set_attribute(
                "scj.historical.count", surfaces["historical_sentences"]["recordsFiltered"]
            )

            page_size_probes: dict[str, Any] = {}
            for start in (0, 10, 40, 80, 90, 100):
                result = request_decisions(context, start=start, length=10)
                page_size_probes[str(start)] = result
            (OUT / "pagination-probe.json").write_text(
                json.dumps(page_size_probes, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            selects = page.locator("select").evaluate_all(
                """els => els.map((el, index) => ({index,name: el.getAttribute('name'),id: el.id,options: Array.from(el.options).map(o => ({value:o.value,text:o.textContent}))}))"""
            )
            (OUT / "page.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(OUT / "page.png"), full_page=True)
            (OUT / "network.json").write_text(
                json.dumps(network, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            (OUT / "json-responses.json").write_text(
                json.dumps(json_payloads, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            (OUT / "selects.json").write_text(
                json.dumps(selects, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            browser.close()

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
