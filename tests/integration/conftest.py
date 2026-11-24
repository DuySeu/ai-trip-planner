from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg_pool import ConnectionPool

from core.config import config
from core.settings import DbSettings, load_db_settings
from db.pool import open_pool
from scripts.migrate import apply_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / "sql" / "migrations"


# Every test in this folder needs Postgres
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" in str(item.path):
            item.add_marker(pytest.mark.integration)


# Tests run in "<DB_NAME>_test" on the same server, never in DB_NAME itself
@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    db: DbSettings = load_db_settings(config.ENV)
    test_name = f"{db.name}_test"

    # Create the test database on first use
    with psycopg.connect(db.conninfo(), autocommit=True) as admin:
        exists = admin.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (test_name,)
        ).fetchone()
        if not exists:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_name)))

    # Start every session from an empty schema
    conninfo = db.conninfo(test_name)
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        apply_migrations(conn, MIGRATIONS)
    yield conninfo


# An autocommit connection to the test database with every table emptied
@pytest.fixture
def db_conn(migrated_db: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'schema_migrations'"
            )
        ]
        conn.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
        yield conn


# A pool on the emptied test database, for tests that need two connections at once
@pytest.fixture
def db_pool(migrated_db: str, db_conn: psycopg.Connection) -> Iterator[ConnectionPool]:
    with open_pool(migrated_db, max_size=4) as pool:
        yield pool
