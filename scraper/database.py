from __future__ import annotations

import os
import logging
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

def _database_url() -> str:
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL is required. Local SQLite is no longer supported; "
            "configure a PostgreSQL connection string."
        )
    if not db_url.startswith("postgresql://"):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL connection string")
    return db_url


def get_connection() -> Any:
    """Return a connection to PostgreSQL."""
    return psycopg.connect(_database_url(), row_factory=dict_row)


def _init_postgres_db(conn: Any) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            id          BIGSERIAL PRIMARY KEY,
            url         TEXT    NOT NULL UNIQUE,
            title       TEXT,
            scraped_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status      TEXT    NOT NULL DEFAULT 'ok'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS recipe_sections (
            id            BIGSERIAL PRIMARY KEY,
            page_id       BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
            section_name  TEXT    NOT NULL,
            section_json  TEXT    NOT NULL,
            UNIQUE(page_id, section_name)
        )
    """)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_recipe_sections_page_id ON recipe_sections(page_id)"
    )

    # Clean up deprecated table if it exists from older schema versions.
    conn.execute("DROP TABLE IF EXISTS items")


def init_db() -> None:
    """Validate PostgreSQL connectivity; schema is managed by migrations."""
    with get_connection() as conn:
        conn.execute("SELECT 1")
    logger.info("Database connectivity validated (PostgreSQL)")


def upsert_page(url: str, title: str | None, status: str = "ok") -> int:
    """Insert or replace a page record and return its id."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pages (url, title, status, scraped_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT(url) DO UPDATE SET
                title      = excluded.title,
                status     = excluded.status,
                scraped_at = excluded.scraped_at
            """,
            (url, title, status),
        )
        row = conn.execute("SELECT id FROM pages WHERE url = %s", (url,)).fetchone()
        return row["id"]


def save_recipe_sections(page_id: int, sections: dict[str, Any]) -> None:
    """Store structured section payloads for a page."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM recipe_sections WHERE page_id = %s", (page_id,))
            cur.executemany(
                """
                INSERT INTO recipe_sections (page_id, section_name, section_json)
                VALUES (%s, %s, %s)
                """,
                [
                    (page_id, section_name, json.dumps(section_data))
                    for section_name, section_data in sections.items()
                ],
            )
    logger.info("Saved %d sections for page_id=%d", len(sections), page_id)
