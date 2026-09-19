from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from jurisnexo.observability import acquisition_span, span_event

_DEFAULT_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_DEFAULT_USER_AGENT = "JurisNexo-OfficialSourceAcquisition/0.1"


@dataclass(frozen=True, slots=True)
class HttpPayload:
    content: bytes
    final_url: str
    status: int


@dataclass(frozen=True, slots=True)
class HttpFilePayload:
    final_url: str
    status: int
    byte_count: int


class HttpStatusError(RuntimeError):
    def __init__(self, *, url: str, status: int) -> None:
        super().__init__(f"HTTP {status} from {url}")
        self.url = url
        self.status = status


class HttpTransport(Protocol):
    def fetch(self, *, url: str, timeout_seconds: float, user_agent: str) -> HttpPayload: ...


@runtime_checkable
class FileHttpTransport(Protocol):
    def fetch_to_file(
        self,
        *,
        url: str,
        destination: Path,
        timeout_seconds: float,
        user_agent: str,
        max_bytes: int,
    ) -> HttpFilePayload: ...


@dataclass(slots=True)
class UrllibHttpTransport:
    """Small stdlib transport kept behind a testable acquisition boundary."""

    def fetch(self, *, url: str, timeout_seconds: float, user_agent: str) -> HttpPayload:
        request = Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.1",
            },
        )
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            status = int(response.status)
            final_url = response.geturl()
            content = response.read()
        return HttpPayload(content=content, final_url=final_url, status=status)

    def fetch_to_file(
        self,
        *,
        url: str,
        destination: Path,
        timeout_seconds: float,
        user_agent: str,
        max_bytes: int,
    ) -> HttpFilePayload:
        request = Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.1",
            },
        )
        byte_count = 0
        with (
            urlopen(request, timeout=timeout_seconds) as response,  # noqa: S310
            destination.open("wb") as output,
        ):
            status = int(response.status)
            final_url = response.geturl()
            while chunk := response.read(1024 * 1024):
                byte_count += len(chunk)
                if byte_count > max_bytes:
                    raise ValueError(
                        f"official-source response exceeds max_bytes={max_bytes}"
                    )
                output.write(chunk)
        return HttpFilePayload(
            final_url=final_url,
            status=status,
            byte_count=byte_count,
        )


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


@dataclass(slots=True)
class BoundedHttpFetcher:
    """Fetch official-source bytes with host, size, timeout, retry, and OTel visibility."""

    allowed_hosts: frozenset[str]
    transport: HttpTransport = field(default_factory=UrllibHttpTransport)
    timeout_seconds: float = 60.0
    max_bytes: int = 100 * 1024 * 1024
    max_attempts: int = 4
    retry_base_delay_seconds: float = 1.0
    user_agent: str = _DEFAULT_USER_AGENT
    sleep: Callable[[float], None] = _sleep
    retryable_status: frozenset[int] = _DEFAULT_RETRYABLE_STATUS

    def __post_init__(self) -> None:
        if not self.allowed_hosts:
            raise ValueError("allowed_hosts must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_bytes < 4:
            raise ValueError("max_bytes must be at least 4")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.retry_base_delay_seconds < 0:
            raise ValueError("retry_base_delay_seconds must be non-negative")

    def _require_allowed_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError("official-source acquisition requires HTTPS")
        host = parsed.hostname
        if host is None or host.casefold() not in self.allowed_hosts:
            raise ValueError(f"refusing non-allowlisted host: {host or '(missing)'}")

    def get_bytes(self, url: str) -> bytes:
        self._require_allowed_url(url)
        host = urlparse(url).hostname or ""
        with acquisition_span(
            "acquisition.http.get",
            **{
                "server.address": host,
                "url.full": url,
                "jurisnexo.http.max_attempts": self.max_attempts,
            },
        ) as span:
            for attempt in range(1, self.max_attempts + 1):
                span_event("http.attempt", attempt=attempt)
                try:
                    payload = self.transport.fetch(
                        url=url,
                        timeout_seconds=self.timeout_seconds,
                        user_agent=self.user_agent,
                    )
                    self._require_allowed_url(payload.final_url)
                    span.set_attribute("http.response.status_code", payload.status)
                    span.set_attribute("http.response.body.size", len(payload.content))
                    span.set_attribute("url.final", payload.final_url)
                    if payload.status >= 400:
                        raise HttpStatusError(url=payload.final_url, status=payload.status)
                    if len(payload.content) > self.max_bytes:
                        raise ValueError(
                            f"official-source response exceeds max_bytes={self.max_bytes}"
                        )
                    return payload.content
                except HTTPError as exc:
                    span_event("http.error", attempt=attempt, status=exc.code)
                    if exc.code not in self.retryable_status or attempt >= self.max_attempts:
                        raise
                except HttpStatusError as exc:
                    span_event("http.error", attempt=attempt, status=exc.status)
                    if exc.status not in self.retryable_status or attempt >= self.max_attempts:
                        raise
                except URLError as exc:
                    span_event("http.error", attempt=attempt, error=str(exc.reason))
                    if attempt >= self.max_attempts:
                        raise

                delay = self.retry_base_delay_seconds * (2 ** (attempt - 1))
                span_event("http.retry", attempt=attempt, delay_seconds=delay)
                self.sleep(delay)

        raise RuntimeError("unreachable acquisition retry state")

    def download_to_file(self, url: str, destination: Path) -> None:
        self._require_allowed_url(url)
        if not isinstance(self.transport, FileHttpTransport):
            destination.write_bytes(self.get_bytes(url))
            return

        host = urlparse(url).hostname or ""
        with acquisition_span(
            "acquisition.http.download",
            **{
                "server.address": host,
                "url.full": url,
                "jurisnexo.http.max_attempts": self.max_attempts,
            },
        ) as span:
            for attempt in range(1, self.max_attempts + 1):
                span_event("http.attempt", attempt=attempt)
                destination.unlink(missing_ok=True)
                try:
                    payload = self.transport.fetch_to_file(
                        url=url,
                        destination=destination,
                        timeout_seconds=self.timeout_seconds,
                        user_agent=self.user_agent,
                        max_bytes=self.max_bytes,
                    )
                    self._require_allowed_url(payload.final_url)
                    span.set_attribute("http.response.status_code", payload.status)
                    span.set_attribute("http.response.body.size", payload.byte_count)
                    span.set_attribute("url.final", payload.final_url)
                    if payload.status >= 400:
                        raise HttpStatusError(url=payload.final_url, status=payload.status)
                    return
                except HTTPError as exc:
                    span_event("http.error", attempt=attempt, status=exc.code)
                    if exc.code not in self.retryable_status or attempt >= self.max_attempts:
                        raise
                except HttpStatusError as exc:
                    span_event("http.error", attempt=attempt, status=exc.status)
                    if exc.status not in self.retryable_status or attempt >= self.max_attempts:
                        raise
                except URLError as exc:
                    span_event("http.error", attempt=attempt, error=str(exc.reason))
                    if attempt >= self.max_attempts:
                        raise

                delay = self.retry_base_delay_seconds * (2 ** (attempt - 1))
                span_event("http.retry", attempt=attempt, delay_seconds=delay)
                self.sleep(delay)

        raise RuntimeError("unreachable acquisition retry state")


SCJ_DECISION_DOCUMENT_HOSTS = frozenset(
    {
        "transparencia.poderjudicial.gob.do",
        "consultaglobal.blob.core.windows.net",
        "sjdeposito.blob.core.windows.net",
    }
)


OFFICIAL_SOURCE_HOSTS = frozenset(
    {
        "www.tribunalconstitucional.gob.do",
        "tribunalsitestorage.blob.core.windows.net",
        "transparencia.poderjudicial.gob.do",
        "consultasentenciascj.poderjudicial.gob.do",
        "consultaglobal.blob.core.windows.net",
        "sjdeposito.blob.core.windows.net",
        "poderjudicial.gob.do",
        "www.poderjudicial.gob.do",
    }
)
