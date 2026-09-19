from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class PlaywrightVerifiedFetcher:
    """Strict-HTTPS browser transport for official sources with browser-only TLS behavior."""

    def __init__(self, *, allowed_hosts: frozenset[str]) -> None:
        self.allowed_hosts = allowed_hosts
        self._playwright: Any | None = None
        self._browser: Any | None = None

    def __enter__(self) -> PlaywrightVerifiedFetcher:
        try:
            sync_api = importlib.import_module("playwright.sync_api")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "PlaywrightVerifiedFetcher requires the optional playwright package"
            ) from exc
        sync_playwright: Any = sync_api.sync_playwright
        playwright: Any = sync_playwright().start()
        browser: Any = playwright.chromium.launch(headless=True)
        self._playwright = playwright
        self._browser = browser
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def _require_allowed(self, url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or host not in self.allowed_hosts:
            raise ValueError(f"refusing non-allowlisted official URL: {url}")

    def download_to_file(self, url: str, destination: Path) -> None:
        self._require_allowed(url)
        parsed = urlparse(url)
        if self._browser is None:
            raise RuntimeError("browser fetcher must be used as a context manager")
        if not parsed.path.casefold().endswith(".pdf"):
            destination.write_bytes(self.get_bytes(url))
            return

        context = self._browser.new_context(ignore_https_errors=False)
        page = context.new_page()
        try:
            page.set_content('<a id="jurisnexo-download">download</a>')
            page.locator("#jurisnexo-download").evaluate(
                "(element, target) => { element.href = target; element.download = ''; }",
                url,
            )
            with page.expect_download(timeout=120_000) as download_info:
                page.click("#jurisnexo-download")
            download = download_info.value
            final_url = download.url
            self._require_allowed(final_url)
            download.save_as(destination)
        finally:
            page.close()
            context.close()

    def get_bytes(self, url: str) -> bytes:
        self._require_allowed(url)
        parsed = urlparse(url)
        if self._browser is None:
            raise RuntimeError("browser fetcher must be used as a context manager")

        context = self._browser.new_context(ignore_https_errors=False)
        page = context.new_page()
        try:
            if parsed.path.casefold().endswith(".pdf"):
                page.set_content('<a id="jurisnexo-download">download</a>')
                page.locator("#jurisnexo-download").evaluate(
                    "(element, target) => { element.href = target; element.download = ''; }",
                    url,
                )
                with page.expect_download(timeout=120_000) as download_info:
                    page.click("#jurisnexo-download")
                download = download_info.value
                self._require_allowed(download.url)
                path = download.path()
                if path is None:
                    raise RuntimeError(f"browser download produced no local path: {url}")
                return Path(path).read_bytes()

            response = page.goto(url, wait_until="commit", timeout=120_000)
            if response is None:
                raise RuntimeError(f"browser navigation returned no response: {url}")
            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status} from {url}")
            self._require_allowed(page.url)
            return response.body()
        finally:
            page.close()
            context.close()
