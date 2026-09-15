from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("JURISNEXO_REPO_ROOT", DEFAULT_REPO_ROOT))
AUDIT_SCRIPT = REPO_ROOT / "backend" / "scripts" / "ci" / "audit_test_architecture.py"


def test_test_architecture_inventory_is_clean() -> None:
    assert AUDIT_SCRIPT.is_file(), "Blocking test-architecture inventory audit is missing"

    result = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--repo-root", str(REPO_ROOT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "Test architecture inventory reported governance drift.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "test architecture inventory: PASS" in result.stdout
