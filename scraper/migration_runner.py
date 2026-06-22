"""Migration runner for PostgreSQL database schema."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


def get_migrations_dir() -> Path:
    """Return the path to the migrations directory."""
    return Path(__file__).parent / "migrations"


def _ensure_migrations_table(conn: Any) -> None:
    """Create the migrations_applied table if it doesn't exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migrations_applied (
            id            BIGSERIAL PRIMARY KEY,
            migration_name TEXT    NOT NULL UNIQUE,
            applied_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def _get_applied_migrations(conn: Any) -> set[str]:
    """Return the set of already-applied migration names."""
    try:
        rows = conn.execute(
            "SELECT migration_name FROM migrations_applied ORDER BY applied_at"
        ).fetchall()
        return {row["migration_name"] for row in rows}
    except Exception as e:
        logger.debug("Could not fetch applied migrations (table may not exist yet): %s", e)
        return set()


def _run_migration(conn: Any, migration_name: str, sql_content: str) -> None:
    """Execute a migration and record it in migrations_applied."""
    logger.info("Running migration: %s", migration_name)
    try:
        conn.execute(sql_content)
        conn.execute(
            "INSERT INTO migrations_applied (migration_name) VALUES (%s)",
            (migration_name,),
        )
        conn.commit()
        logger.info("Migration applied successfully: %s", migration_name)
    except Exception as e:
        conn.rollback()
        logger.error("Migration failed: %s: %s", migration_name, e)
        raise


def apply_migrations(database_url: str | None = None) -> int:
    """
    Apply all pending migrations to the database.

    Args:
        database_url: PostgreSQL connection string. If None, uses DATABASE_URL env var.

    Returns:
        Number of migrations applied.

    Raises:
        RuntimeError: If DATABASE_URL is not configured or connection fails.
    """
    db_url = database_url or os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL environment variable not set and no database_url provided"
        )

    if not db_url.startswith("postgresql://"):
        raise RuntimeError("apply_migrations() only supports PostgreSQL")

    migrations_dir = get_migrations_dir()
    if not migrations_dir.exists():
        raise RuntimeError(f"Migrations directory not found: {migrations_dir}")

    # Gather all .sql migration files, sorted by name (M001_, M002_, etc.)
    migration_files = sorted(migrations_dir.glob("M*.sql"))
    if not migration_files:
        logger.warning("No migration files found in %s", migrations_dir)
        return 0

    logger.info("Found %d migration file(s)", len(migration_files))

    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        _ensure_migrations_table(conn)
        applied = _get_applied_migrations(conn)

        count = 0
        for migration_file in migration_files:
            migration_name = migration_file.name
            if migration_name in applied:
                logger.debug("Migration already applied, skipping: %s", migration_name)
                continue

            sql_content = migration_file.read_text()
            _run_migration(conn, migration_name, sql_content)
            count += 1

        if count == 0:
            logger.info("No pending migrations to apply")
        else:
            logger.info("Applied %d migration(s)", count)

    return count


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        applied_count = apply_migrations()
        print(f"\nMigrations applied: {applied_count}")
    except Exception as e:
        print(f"Migration error: {e}")
        exit(1)
