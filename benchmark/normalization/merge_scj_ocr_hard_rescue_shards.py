from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ENGINES = ("tesseract", "rapidocr", "paddleocr")


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def merge(engine: str, inputs: list[Path], output: Path, expected: int) -> int:
    rows: list[dict[str, Any]] = []
    for path in inputs:
        rows.extend(_rows(path))
    if len(rows) != expected:
        raise RuntimeError(f"{engine}: expected {expected} observations, found {len(rows)}")
    sample_ids = [str(row["sample_id"]) for row in rows]
    observation_ids = [str(row.get("observation_id") or "") for row in rows]
    if len(set(sample_ids)) != expected:
        raise RuntimeError(f"{engine}: duplicate sample IDs across shards")
    if len(set(observation_ids)) != expected:
        raise RuntimeError(f"{engine}: duplicate observation IDs across shards")
    if any(row.get("engine") != engine for row in rows):
        raise RuntimeError(f"{engine}: engine provenance mismatch in shard output")
    if any(not oid.startswith("ocr-observation:") for oid in observation_ids):
        raise RuntimeError(f"{engine}: malformed observation ID")
    rows.sort(key=lambda row: str(row["sample_id"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(json.dumps({"engine": engine, "observations": len(rows), "output": str(output)}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=ENGINES, required=True)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected", type=int, required=True)
    args = parser.parse_args()
    return merge(args.engine, args.input, args.output, args.expected)


if __name__ == "__main__":
    raise SystemExit(main())
