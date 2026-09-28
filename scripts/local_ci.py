#!/usr/bin/env python3
"""Small cross-platform entry point for expensive/manual JurisNexo checks.

This intentionally does not emulate GitHub Actions. It exposes the underlying
repo commands so the same tests can run on a developer workstation without
runner timeouts. Run `python scripts/local_ci.py list` for available profiles.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

PROFILES: dict[str, list[list[str]]] = {
    "normalization-contract": [
        [PYTHON, "-m", "py_compile", "backend/scripts/scj_principales_text_layer_census.py"],
        [PYTHON, "-m", "pytest", "-q", "backend/tests/unit/test_scj_principales_text_layer_census.py", "backend/tests/unit/test_visual_reference_alignment.py", "backend/tests/unit/test_visual_reference_ocr.py"],
    ],
    "backend-quality": [
        [PYTHON, "-m", "ruff", "check", "backend"],
        [PYTHON, "-m", "pytest", "-q", "backend/tests/unit"],
    ],
}


def run(command: list[str]) -> None:
    print("+", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True, env=os.environ.copy())


def census(args: argparse.Namespace) -> int:
    if shutil.which("tesseract") is None:
        raise SystemExit("tesseract is not on PATH. Install Tesseract with Spanish and English language data first.")
    command = [PYTHON, "backend/scripts/scj_principales_text_layer_census.py", "--output", str(args.output), "--cache-dir", str(args.cache_dir), "--progress-every", str(args.progress_every)]
    if args.resume:
        command.append("--resume")
    run(command)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run selected JurisNexo CI workloads locally")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    profile = sub.add_parser("run")
    profile.add_argument("profile", choices=sorted(PROFILES))
    census_parser = sub.add_parser("census")
    census_parser.add_argument("--output", type=Path, default=ROOT / ".local-ci" / "scj-census")
    census_parser.add_argument("--cache-dir", type=Path, default=ROOT / ".local-ci" / "pdf-cache")
    census_parser.add_argument("--resume", action="store_true")
    census_parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()
    if args.command == "list":
        print("Profiles:")
        for name in sorted(PROFILES):
            print(f"  {name}")
        print("Special workloads:\n  census")
        return 0
    if args.command == "run":
        for command in PROFILES[args.profile]:
            run(command)
        return 0
    return census(args)


if __name__ == "__main__":
    raise SystemExit(main())
