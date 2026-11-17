"""Postgres connection pool.

Use `with pool.connection() as conn:` for a unit of work: it commits when the block ends
and rolls back if it raises.
"""

from __future__ import annotations

from psycopg_pool import ConnectionPool


# Open the shared pool; the caller closes it on shutdown
def open_pool(database_url: str, max_size: int = 10) -> ConnectionPool:
    return ConnectionPool(database_url, min_size=1, max_size=max_size, open=True)
