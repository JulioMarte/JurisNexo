from __future__ import annotations

import argparse
import json
from pathlib import Path

from jurisnexo.acquisition.http_fetcher import OFFICIAL_SOURCE_HOSTS, BoundedHttpFetcher
from jurisnexo.acquisition.official_corpus import SCJ_MEGAQUERY_URL, TC_SENTENCES_URL
from jurisnexo.acquisition.source_drift import (
    BrowserRecoveryRequest,
    inspect_scj_megaconsulta_surface,
    inspect_tc_sentence_surface,
)


def probe_official_sources(
    *, fetcher: BoundedHttpFetcher, output_directory: Path
) -> dict[str, object]:
    output_directory.mkdir(parents=True, exist_ok=True)

    scj_bytes = fetcher.get_bytes(SCJ_MEGAQUERY_URL)
    tc_bytes = fetcher.get_bytes(TC_SENTENCES_URL)
    scj_html = scj_bytes.decode("utf-8", errors="replace")
    tc_html = tc_bytes.decode("utf-8", errors="replace")

    (output_directory / "scj-megaconsulta.html").write_bytes(scj_bytes)
    (output_directory / "tc-sentences.html").write_bytes(tc_bytes)

    observations = (
        inspect_scj_megaconsulta_surface(scj_html),
        inspect_tc_sentence_surface(tc_html),
    )
    drifted = tuple(item for item in observations if item.requires_browser_recovery)
    summary: dict[str, object] = {
        "status": "SOURCE_DRIFT" if drifted else "HEALTHY",
        "surfaces": [json.loads(item.to_json()) for item in observations],
        "browser_recovery_required": bool(drifted),
    }
    (output_directory / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for observation in drifted:
        request = BrowserRecoveryRequest(observation=observation)
        filename = f"browser-recovery-{observation.surface}.json"
        (output_directory / filename).write_text(
            request.to_json() + "\n",
            encoding="utf-8",
        )
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe official SCJ and TC discovery surfaces")
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    fetcher = BoundedHttpFetcher(
        allowed_hosts=OFFICIAL_SOURCE_HOSTS,
        max_bytes=25 * 1024 * 1024,
    )
    summary = probe_official_sources(fetcher=fetcher, output_directory=args.output_directory)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] == "SOURCE_DRIFT":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
