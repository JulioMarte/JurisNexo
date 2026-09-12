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
                            decoded = json.loads(body.decode("utf-8"))
                            json_payloads.append(
                                {
                                    "url": response.url,
                                    "request_post_data": request.post_data,
                                    "body": decoded,
                                }
                            )
                    except Exception as exc:
                        item["json_capture_error"] = repr(exc)

            page.on("response", on_response)
            response = page.goto(TARGET, wait_until="networkidle", timeout=120_000)
            if response is None:
                raise RuntimeError("SCJ portal navigation produced no response")
            root.set_attribute("http.response.status_code", response.status)
            page.wait_for_timeout(2_000)

            script_src = page.locator('script[src*="JsConsulta.js"]').get_attribute("src")
            if script_src:
                script_response = context.request.get(urljoin(TARGET, script_src), timeout=60_000)
                (OUT / "JsConsulta.js").write_text(script_response.text(), encoding="utf-8")

            with tracer.start_as_current_span("scj.browser.filtered_query") as filtered_span:
                page.select_option("#cbTipoDocumento", "1")
                page.wait_for_timeout(3_000)
                filtered_span.set_attribute("scj.filter.document_type", "1")

            with tracer.start_as_current_span("scj.context_request.pagination_probe") as span:
                api_response = context.request.post(
                    ENDPOINT,
                    form=datatables_form(start=10, length=100),
                    headers={
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": TARGET,
                    },
                    timeout=90_000,
                )
                payload = api_response.json()
                if not isinstance(payload, dict):
                    raise TypeError("SCJ context request returned non-object JSON")
                rows = payload.get("data", [])
                if not isinstance(rows, list):
                    raise TypeError("SCJ context request data is not a list")
                context_probe = {
                    "status": api_response.status,
                    "recordsTotal": int(payload.get("recordsTotal", 0)),
                    "recordsFiltered": int(payload.get("recordsFiltered", 0)),
                    "row_count": len(rows),
                    "first_row": rows[0] if rows else None,
                    "last_row": rows[-1] if rows else None,
                }
                (OUT / "context-request-probe.json").write_text(
                    json.dumps(context_probe, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                span.set_attribute("http.response.status_code", api_response.status)
                span.set_attribute("scj.records.filtered", context_probe["recordsFiltered"])
                span.set_attribute("scj.page.row_count", len(rows))
                if context_probe["recordsFiltered"] <= 0 or not rows:
                    raise RuntimeError(
                        "SCJ BrowserContext request did not reproduce the successful inventory query"
                    )

            selects = page.locator("select").evaluate_all(
                """els => els.map((el, index) => ({
                    index,
                    name: el.getAttribute('name'),
                    id: el.id,
                    ariaLabel: el.getAttribute('aria-label'),
                    options: Array.from(el.options).map(o => ({value: o.value, text: o.textContent}))
                }))"""
            )
            anchors = page.locator("a[href]").evaluate_all(
                "els => els.map(a => ({text: a.textContent, href: a.href}))"
            )
            inputs = page.locator("input").evaluate_all(
                """els => els.map((el, index) => ({
                    index,
                    name: el.getAttribute('name'),
                    id: el.id,
                    type: el.type,
                    placeholder: el.getAttribute('placeholder')
                }))"""
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
            (OUT / "inputs.json").write_text(
                json.dumps(inputs, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            (OUT / "anchors.json").write_text(
                json.dumps(anchors, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            candidate_requests = [
                item
                for item in network
                if item["resource_type"] in {"xhr", "fetch"}
                or "json" in item["content_type"].casefold()
                or "api" in item["url"].casefold()
            ]
            summary = {
                "target": TARGET,
                "navigation_status": response.status,
                "title": page.title(),
                "network_request_count": len(network),
                "candidate_data_request_count": len(candidate_requests),
                "candidate_data_requests": candidate_requests,
                "select_count": len(selects),
                "selects": selects,
                "input_count": len(inputs),
                "json_response_count": len(json_payloads),
                "context_request_probe": context_probe,
            }
            (OUT / "summary.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            root.set_attribute("scj.network.request_count", len(network))
            root.set_attribute("scj.network.candidate_data_request_count", len(candidate_requests))
            root.set_attribute("scj.form.select_count", len(selects))
            root.set_attribute("scj.json.response_count", len(json_payloads))
            browser.close()

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
