from __future__ import annotations

import re
import sys
from pathlib import Path

UUID_RE = re.compile(
    r"(?<![0-9a-fA-F])"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
    r"(?![0-9a-fA-F])"
)
TIMESTAMPTZ_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2} "
    r"\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}(?::?\d{2})?|Z)\b"
)


def normalize(text: str) -> str:
    uuid_map: dict[str, str] = {}

    def replace_uuid(match: re.Match[str]) -> str:
        value = match.group(0).lower()
        token = uuid_map.setdefault(value, f"<uuid:{len(uuid_map) + 1}>")
        return token

    text = UUID_RE.sub(replace_uuid, text)
    text = TIMESTAMPTZ_RE.sub("<generated-timestamptz>", text)
    text = re.sub(r"^--.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m jurisnexo.db_dump_normalizer INPUT OUTPUT")
    source = Path(sys.argv[1]).read_text(encoding="utf-8")
    Path(sys.argv[2]).write_text(normalize(source), encoding="utf-8")


if __name__ == "__main__":
    main()
