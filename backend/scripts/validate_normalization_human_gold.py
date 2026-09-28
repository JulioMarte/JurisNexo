from __future__ import annotations

import argparse
import json
from pathlib import Path

from jurisnexo.normalization.human_gold import (
    human_gold_summary,
    load_human_gold_set,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a versioned human-adjudicated normalization gold set.",
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--require-verified",
        action="store_true",
        help="fail unless the set contains at least one verified human page",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    gold = load_human_gold_set(args.path)
    summary = human_gold_summary(gold)
    if args.require_verified and int(summary["verified_page_count"]) < 1:
        raise RuntimeError(
            "human gold set contains no verified adjudicated pages"
        )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
