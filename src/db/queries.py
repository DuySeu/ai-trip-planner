"""Load named SQL queries from sql/queries/*.sql."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

NAME_LINE = re.compile(r"^--\s*name:\s*(\w+)\s*$", re.MULTILINE)
QUERIES_DIR = Path(__file__).resolve().parents[2] / "sql" / "queries"


# Split a file into {name: sql} on "-- name: <query_name>" header lines
def load_queries(path: Path) -> Mapping[str, str]:
    text = path.read_text()
    parts = NAME_LINE.split(text)

    # parts = [before_first_name, name1, body1, name2, body2, ...]
    if parts[0].strip():
        raise ValueError(f"{path}: SQL found before the first '-- name:' line")

    queries: dict[str, str] = {}
    for name, body in zip(parts[1::2], parts[2::2], strict=True):
        if name in queries:
            raise ValueError(f"{path}: duplicate query name {name!r}")
        if not body.strip():
            raise ValueError(f"{path}: query {name!r} is empty")
        queries[name] = body.strip()
    return queries
