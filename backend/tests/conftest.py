from __future__ import annotations

from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply evidence classification from stable physical ownership boundaries.

    Architecture tests are deterministic fitness functions by ownership. If a
    historical lane is introduced later, tests placed under tests/historical/
    are historical evidence rather than current-product fitness.
    """

    for item in items:
        item_path = Path(item.path).resolve()
        try:
            relative = item_path.relative_to(TEST_ROOT)
        except ValueError:
            continue
        if not relative.parts:
            continue
        if relative.parts[0] == "architecture":
            item.add_marker(pytest.mark.fitness)
        elif relative.parts[0] == "historical":
            item.add_marker(pytest.mark.historical)
