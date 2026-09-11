from __future__ import annotations

from dataclasses import dataclass

import pytest

from jurisnexo.model_providers.contracts import JsonObject
from jurisnexo.model_providers.google_gemini import GoogleGeminiProvider

pytestmark = pytest.mark.unit


@dataclass(slots=True)
class CountTransport:
    last_url: str | None = None
    last_payload: JsonObject | None = None

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: JsonObject,
        timeout_seconds: float,
    ) -> JsonObject:
        del headers, timeout_seconds
        self.last_url = url
        self.last_payload = payload
        return {"totalTokens": 321}


def test_count_input_tokens_uses_model_tokenizer_endpoint() -> None:
    transport = CountTransport()
    provider = GoogleGeminiProvider(
        api_key="test-secret", model="gemini-3.8-flash", transport=transport
    )
    assert provider.count_input_tokens("legal evidence") == 321
    assert transport.last_url is not None
    assert transport.last_url.endswith("/models/gemini-3.8-flash:countTokens")
    assert transport.last_payload == {
        "contents": [{"role": "user", "parts": [{"text": "legal evidence"}]}]
    }
