"""Apply sql/migrations/*.sql in order, each once, recording them in schema_migrations.

Run from the repo root: PYTHONPATH=src uv run python scripts/migrate.py (reads DB_* through core.config: the environment or .env).
"""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg

from core.config import config
from core.settings import load_db_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "sql" / "migrations"
# Any fixed number; serializes concurrent runs (api and worker starting together)
LOCK_ID = 7_420_001

logger = logging.getLogger(__name__)


# Apply every migration not yet recorded; return the versions applied
def apply_migrations(conn: psycopg.Connection, migrations_dir: Path) -> list[str]:
    applied: list[str] = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}

        # Each file runs inside a savepoint so a failure leaves nothing half-applied
        for path in sorted(migrations_dir.glob("*.sql")):
            if path.stem in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
            applied.append(path.stem)
            logger.info("applied migration %s", path.stem)
    return applied


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db = load_db_settings(config.ENV)
    with psycopg.connect(db.conninfo(), autocommit=True) as connection:
        versions = apply_migrations(connection, MIGRATIONS_DIR)
    logger.info("%d migration(s) applied", len(versions))
