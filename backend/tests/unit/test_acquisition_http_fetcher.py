from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import URLError

import pytest

from jurisnexo.acquisition.http_fetcher import (
    OFFICIAL_SOURCE_HOSTS,
    SCJ_DECISION_DOCUMENT_HOSTS,
    BoundedHttpFetcher,
    HttpFilePayload,
    HttpPayload,
    HttpStatusError,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


def _empty_delays() -> list[float]:
    return []


@dataclass(slots=True)
class SequenceTransport:
    outcomes: tuple[HttpPayload | Exception, ...]
    calls: int = 0

    def fetch(self, *, url: str, timeout_seconds: float, user_agent: str) -> HttpPayload:
        del url, timeout_seconds, user_agent
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@dataclass(slots=True)
class FileTransport:
    payload: bytes
    final_url: str = "https://official.example/a.pdf"
    status: int = 200
    calls: int = 0

    def fetch(self, *, url: str, timeout_seconds: float, user_agent: str) -> HttpPayload:
        del url, timeout_seconds, user_agent
        raise AssertionError("file transport should not use buffered fetch")

    def fetch_to_file(
        self,
        *,
        url: str,
        destination: Path,
        timeout_seconds: float,
        user_agent: str,
        max_bytes: int,
    ) -> HttpFilePayload:
        del url, timeout_seconds, user_agent
        self.calls += 1
        if len(self.payload) > max_bytes:
            raise ValueError(f"official-source response exceeds max_bytes={max_bytes}")
        with destination.open("wb") as stream:
            for offset in range(0, len(self.payload), 3):
                stream.write(self.payload[offset : offset + 3])
        return HttpFilePayload(
            final_url=self.final_url,
            status=self.status,
            byte_count=len(self.payload),
        )


@dataclass(slots=True)
class RecordingSleep:
    delays: list[float] = field(default_factory=_empty_delays)

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _fetcher(
    transport: SequenceTransport,
    sleep: RecordingSleep | None = None,
) -> BoundedHttpFetcher:
    return BoundedHttpFetcher(
        allowed_hosts=frozenset({"official.example"}),
        transport=transport,
        sleep=sleep or RecordingSleep(),
    )


def test_fetcher_accepts_allowlisted_https_response() -> None:
    transport = SequenceTransport(
        outcomes=(
            HttpPayload(
                content=b"%PDF fixture",
                final_url="https://official.example/a.pdf",
                status=200,
            ),
        )
    )

    content = _fetcher(transport).get_bytes("https://official.example/a.pdf")

    assert content == b"%PDF fixture"


def test_fetcher_rejects_non_allowlisted_input_host() -> None:
    transport = SequenceTransport(outcomes=())

    with pytest.raises(ValueError, match="non-allowlisted"):
        _fetcher(transport).get_bytes("https://evil.example/a.pdf")

    assert transport.calls == 0


def test_fetcher_rejects_redirect_to_non_allowlisted_host() -> None:
    transport = SequenceTransport(
        outcomes=(
            HttpPayload(
                content=b"%PDF",
                final_url="https://evil.example/a.pdf",
                status=200,
            ),
        )
    )

    with pytest.raises(ValueError, match="non-allowlisted"):
        _fetcher(transport).get_bytes("https://official.example/a.pdf")


def test_fetcher_retries_transient_http_error_with_bounded_backoff() -> None:
    transient = HttpStatusError(url="https://official.example/a.pdf", status=503)
    transport = SequenceTransport(
        outcomes=(
            transient,
            HttpPayload(
                content=b"%PDF",
                final_url="https://official.example/a.pdf",
                status=200,
            ),
        )
    )
    sleep = RecordingSleep()
    fetcher = _fetcher(transport, sleep)

    assert fetcher.get_bytes("https://official.example/a.pdf") == b"%PDF"
    assert transport.calls == 2
    assert sleep.delays == [1.0]


def test_fetcher_retries_network_error() -> None:
    transport = SequenceTransport(
        outcomes=(
            URLError("temporary network failure"),
            HttpPayload(
                content=b"ok",
                final_url="https://official.example/page",
                status=200,
            ),
        )
    )

    assert _fetcher(transport).get_bytes("https://official.example/page") == b"ok"
    assert transport.calls == 2


def test_fetcher_fails_closed_on_oversized_response() -> None:
    transport = SequenceTransport(
        outcomes=(
            HttpPayload(
                content=b"12345",
                final_url="https://official.example/a",
                status=200,
            ),
        )
    )
    fetcher = BoundedHttpFetcher(
        allowed_hosts=frozenset({"official.example"}),
        transport=transport,
        max_bytes=4,
    )

    with pytest.raises(ValueError, match="exceeds max_bytes"):
        fetcher.get_bytes("https://official.example/a")


def test_fetcher_streams_to_file_without_buffered_fetch(tmp_path: Path) -> None:
    payload = b"%PDF streamed fixture"
    transport = FileTransport(payload=payload)
    destination = tmp_path / "document.pdf"
    fetcher = BoundedHttpFetcher(
        allowed_hosts=frozenset({"official.example"}),
        transport=transport,
    )

    fetcher.download_to_file("https://official.example/a.pdf", destination)

    assert destination.read_bytes() == payload
    assert transport.calls == 1


def test_streaming_fetcher_rejects_oversized_response(tmp_path: Path) -> None:
    transport = FileTransport(payload=b"12345")
    fetcher = BoundedHttpFetcher(
        allowed_hosts=frozenset({"official.example"}),
        transport=transport,
        max_bytes=4,
    )

    with pytest.raises(ValueError, match="exceeds max_bytes"):
        fetcher.download_to_file(
            "https://official.example/a.pdf",
            tmp_path / "oversized.pdf",
        )


def test_scj_decision_document_hosts_match_live_official_inventory_topology() -> None:
    assert frozenset(
        {
            "transparencia.poderjudicial.gob.do",
            "consultaglobal.blob.core.windows.net",
            "sjdeposito.blob.core.windows.net",
        }
    ) == SCJ_DECISION_DOCUMENT_HOSTS
    assert SCJ_DECISION_DOCUMENT_HOSTS <= OFFICIAL_SOURCE_HOSTS
