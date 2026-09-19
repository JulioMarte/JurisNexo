from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn
