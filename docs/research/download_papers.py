from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "papers.json"
CHECKSUMS = ROOT / "checksums.sha256"


def _load_manifest() -> list[dict[str, object]]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    papers = payload.get("papers")
    if not isinstance(papers, list) or not papers:
        raise SystemExit("papers.json has no papers")
    return papers


def _download(url: str, destination: Path) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "JurisNexo research-library downloader/1.0",
            "Accept": "application/pdf",
        },
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError(f"{url} did not return a PDF")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return data


def main() -> None:
    checksums: list[str] = []
    for paper in _load_manifest():
        url = str(paper["pdf_url"])
        relative_path = Path(str(paper["path"]))
        destination = ROOT / relative_path
        if destination.exists():
            data = destination.read_bytes()
            if not data.startswith(b"%PDF"):
                raise SystemExit(f"{relative_path} exists but is not a PDF")
            action = "verified"
        else:
            data = _download(url, destination)
            action = "downloaded"

        digest = hashlib.sha256(data).hexdigest()
        checksums.append(f"{digest}  {relative_path.as_posix()}")
        print(f"{action}: {relative_path} ({len(data)} bytes)")

    CHECKSUMS.write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(f"wrote {CHECKSUMS.relative_to(ROOT.parent.parent)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"research paper sync failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
