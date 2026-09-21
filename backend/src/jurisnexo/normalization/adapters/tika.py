from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from jurisnexo.normalization.contracts import FormatInspection


@dataclass(slots=True)
class TikaServerFormatInspector:
    base_url: str = "http://127.0.0.1:9998"
    timeout_seconds: float = 30.0

    def inspect(self, source: bytes, *, filename: str | None = None) -> FormatInspection:
        headers = {"Content-Type": "application/octet-stream"}
        if filename:
            headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        media_type = self._put("/detect", source, headers).decode("utf-8").strip()
        metadata_raw = self._put(
            "/meta",
            source,
            {**headers, "Accept": "application/json"},
        )
        try:
            metadata_obj = json.loads(metadata_raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Tika returned invalid metadata JSON") from exc
        metadata = cast(dict[str, Any], metadata_obj) if isinstance(metadata_obj, dict) else {}
        return FormatInspection(
            media_type=media_type or "application/octet-stream",
            detected_format=media_type or "application/octet-stream",
            metadata=metadata,
        )

    def _put(self, path: str, source: bytes, headers: dict[str, str]) -> bytes:
        request = Request(
            url=f"{self.base_url.rstrip('/')}{path}",
            data=source,
            headers=headers,
            method="PUT",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"Tika HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Tika transport error: {exc.reason}") from exc
