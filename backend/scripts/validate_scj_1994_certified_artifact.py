from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jurisnexo.acquisition.http_fetcher import SCJ_DECISION_DOCUMENT_HOSTS

REQUIRED_FILES = (
    "scj-1994-acquisition.inventory.jsonl",
    "scj-1994-source.inventory.jsonl",
    "duplicate-document-urls.json",
    "summary.json",
    "scj-1994-certify.log",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object in {path}")
    return value


def main() -> None:
    root = Path(os.environ["SCJ_CERTIFIED_ARTIFACT_DIR"])
    if not root.is_dir():
        raise FileNotFoundError(f"certified artifact root does not exist: {root}")

    actual_files = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    )
    print(json.dumps({"artifact_root": str(root), "files": actual_files}, indent=2))

    missing = sorted(name for name in REQUIRED_FILES if not (root / name).is_file())
    if missing:
        raise FileNotFoundError(
            f"certified artifact contract missing required files: {missing}"
        )

    unexpected_nested = sorted(
        name for name in actual_files if "/" in name or "\\" in name
    )
    if unexpected_nested:
        raise RuntimeError(
            "certified artifact contract must be flat; nested files found: "
            f"{unexpected_nested}"
        )

    summary = _load_json(root / "summary.json")
    if summary.get("status") != "COMPLETE":
        raise RuntimeError(f"certified inventory status is not COMPLETE: {summary.get('status')!r}")

    acquisition_path = root / "scj-1994-acquisition.inventory.jsonl"
    source_path = root / "scj-1994-source.inventory.jsonl"
    acquisition_size = acquisition_path.stat().st_size
    source_size = source_path.stat().st_size
    if acquisition_size <= 0 or source_size <= 0:
        raise RuntimeError(
            "certified inventory files must be non-empty: "
            f"acquisition={acquisition_size} source={source_size}"
        )

    acquisition_sha256 = _sha256(acquisition_path)
    source_sha256 = _sha256(source_path)
    expected_acquisition_sha256 = str(summary.get("acquisition_inventory_sha256") or "")
    expected_source_sha256 = str(summary.get("source_inventory_sha256") or "")
    if acquisition_sha256 != expected_acquisition_sha256:
        raise RuntimeError(
            "acquisition inventory SHA mismatch: "
            f"actual={acquisition_sha256} expected={expected_acquisition_sha256}"
        )
    if source_sha256 != expected_source_sha256:
        raise RuntimeError(
            "source inventory SHA mismatch: "
            f"actual={source_sha256} expected={expected_source_sha256}"
        )

    expected_count = int(summary.get("unique_document_url_count") or 0)
    line_count = 0
    host_counts: Counter[str] = Counter()
    unexpected_hosts: Counter[str] = Counter()
    with acquisition_path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            line_count += 1
            record = json.loads(line)
            if not isinstance(record, dict):
                raise TypeError("acquisition inventory contains non-object record")
            document_url = str(record.get("document_url") or "").strip()
            host = (urlparse(document_url).hostname or "").casefold()
            host_counts[host] += 1
            if host not in SCJ_DECISION_DOCUMENT_HOSTS:
                unexpected_hosts[host] += 1
    if unexpected_hosts:
        raise RuntimeError(
            "certified inventory contains non-allowlisted SCJ document hosts: "
            f"{dict(sorted(unexpected_hosts.items()))}"
        )
    if line_count != expected_count:
        raise RuntimeError(
            "acquisition inventory line count mismatch: "
            f"lines={line_count} expected={expected_count}"
        )

    result = {
        "status": "VALID",
        "artifact_root": str(root),
        "required_file_count": len(REQUIRED_FILES),
        "acquisition_inventory": {
            "byte_count": acquisition_size,
            "sha256": acquisition_sha256,
            "record_count": line_count,
        },
        "source_inventory": {
            "byte_count": source_size,
            "sha256": source_sha256,
        },
        "document_hosts": dict(sorted(host_counts.items())),
        "allowed_document_hosts": sorted(SCJ_DECISION_DOCUMENT_HOSTS),
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
