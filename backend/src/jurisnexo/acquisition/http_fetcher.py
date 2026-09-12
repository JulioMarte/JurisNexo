from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_DEFAULT_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_DEFAULT_USER_AGENT = "JurisNexo-OfficialSourceAcquisition/0.1"


@dataclass(frozen=True, slots=True)
class HttpPayload:
    content: bytes
    final_url: str
    status: int


class HttpTransport(Protocol):
    def fetch(self, *, url: str, timeout_seconds: float, user_agent: str) -> HttpPayload: ...


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


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


@dataclass(slots=True)
class BoundedHttpFetcher:
    """Fetch official-source bytes with host, size, timeout, and retry limits."""

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
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                payload = self.transport.fetch(
                    url=url,
                    timeout_seconds=self.timeout_seconds,
                    user_agent=self.user_agent,
                )
                self._require_allowed_url(payload.final_url)
                if payload.status >= 400:
                    raise HTTPError(
                        payload.final_url,
                        payload.status,
                        f"HTTP {payload.status}",
                        hdrs=None,
                        fp=None,
                    )
                if len(payload.content) > self.max_bytes:
                    raise ValueError(
                        f"official-source response exceeds max_bytes={self.max_bytes}"
                    )
                return payload.content
            except HTTPError as exc:
                last_error = exc
                retryable = exc.code in self.retryable_status
            except URLError as exc:
                last_error = exc
                retryable = True

            if not retryable or attempt >= self.max_attempts:
                if last_error is None:
                    raise RuntimeError("HTTP acquisition failed without an error")
                raise last_error
            self.sleep(self.retry_base_delay_seconds * (2 ** (attempt - 1)))

        raise RuntimeError("unreachable acquisition retry state")


OFFICIAL_SOURCE_HOSTS = frozenset(
    {
        "www.tribunalconstitucional.gob.do",
        "tribunalsitestorage.blob.core.windows.net",
        "transparencia.poderjudicial.gob.do",
    }
)
