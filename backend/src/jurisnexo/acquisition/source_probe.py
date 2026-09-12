from __future__ import annotations

import argparse
import json
from pathlib import Path

from jurisnexo.acquisition.http_fetcher import OFFICIAL_SOURCE_HOSTS, BoundedHttpFetcher
from jurisnexo.acquisition.official_corpus import (
    SCJ_MEGAQUERY_URL,
    TC_SENTENCES_URL,
    discover_scj_pdf_candidates_from_html,
    discover_tc_detail_pages,
    sha256_hex,
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

    scj_candidates = discover_scj_pdf_candidates_from_html(
        html=scj_html,
        page_url=SCJ_MEGAQUERY_URL,
    )
    tc_detail_pages = discover_tc_detail_pages(
        html=tc_html,
        listing_url=TC_SENTENCES_URL,
    )
    summary: dict[str, object] = {
        "scj": {
            "url": SCJ_MEGAQUERY_URL,
            "sha256": sha256_hex(scj_bytes),
            "byte_count": len(scj_bytes),
            "direct_pdf_candidate_count": len(scj_candidates),
        },
        "constitutional_court": {
            "url": TC_SENTENCES_URL,
            "sha256": sha256_hex(tc_bytes),
            "byte_count": len(tc_bytes),
            "sentence_detail_count": len(tc_detail_pages),
            "first_sentence_ids": [item[0] for item in tc_detail_pages[:10]],
        },
    }
    (output_directory / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
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


if __name__ == "__main__":
    main()
