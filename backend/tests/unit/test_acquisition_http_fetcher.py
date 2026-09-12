from __future__ import annotations

from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError

import pytest

from jurisnexo.acquisition.http_fetcher import BoundedHttpFetcher, HttpPayload

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
    transient = HTTPError(
        "https://official.example/a.pdf",
        503,
        "temporary",
        hdrs=None,
        fp=None,
    )
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
