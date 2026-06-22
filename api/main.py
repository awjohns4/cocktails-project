from __future__ import annotations

import hmac
import json
import os
import random
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from scraper.database import get_connection


def _is_postgres_conn(conn: Any) -> bool:
    return conn.__class__.__module__.startswith("psycopg")

app = FastAPI(title="cocktail-mcp-api", version="0.1.0")
EXPECTED_API_KEY = os.getenv("MCP_API_KEY", "").strip()


@app.middleware("http")
async def require_api_key_for_tools(request: Request, call_next):
    # Keep health probe public; protect MCP tool routes with x-api-key.
    if request.url.path.startswith("/tools/"):
        provided_api_key = request.headers.get("x-api-key", "").strip()

        if not EXPECTED_API_KEY:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "MCP API key is not configured"},
            )

        if not provided_api_key or not hmac.compare_digest(provided_api_key, EXPECTED_API_KEY):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or missing API key"},
            )

    return await call_next(request)


def _fetch_recipe_by_name(name: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        if _is_postgres_conn(conn):
            page = conn.execute(
                """
                SELECT id, url, title, status, scraped_at
                FROM pages
                WHERE lower(title) LIKE lower(%s)
                ORDER BY scraped_at DESC
                LIMIT 1
                """,
                (f"%{name}%",),
            ).fetchone()
        else:
            page = conn.execute(
                """
                SELECT id, url, title, status, scraped_at
                FROM pages
                WHERE lower(title) LIKE lower(?)
                ORDER BY scraped_at DESC
                LIMIT 1
                """,
                (f"%{name}%",),
            ).fetchone()

        if not page:
            return None

        if _is_postgres_conn(conn):
            sections = conn.execute(
                """
                SELECT section_name, section_json
                FROM recipe_sections
                WHERE page_id = %s
                """,
                (page["id"],),
            ).fetchall()
        else:
            sections = conn.execute(
                """
                SELECT section_name, section_json
                FROM recipe_sections
                WHERE page_id = ?
                """,
                (page["id"],),
            ).fetchall()

    return {
        "id": page["id"],
        "url": page["url"],
        "title": page["title"],
        "status": page["status"],
        "scraped_at": page["scraped_at"],
        "sections": {
            row["section_name"]: json.loads(row["section_json"]) for row in sections
        },
    }


def _fetch_recipe_by_id(recipe_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        if _is_postgres_conn(conn):
            page = conn.execute(
                """
                SELECT id, title
                FROM pages
                WHERE id = %s
                """,
                (recipe_id,),
            ).fetchone()
        else:
            page = conn.execute(
                """
                SELECT id, title
                FROM pages
                WHERE id = ?
                """,
                (recipe_id,),
            ).fetchone()

        if not page:
            return None

        if _is_postgres_conn(conn):
            sections = conn.execute(
                """
                SELECT section_name, section_json
                FROM recipe_sections
                WHERE page_id = %s
                """,
                (page["id"],),
            ).fetchall()
        else:
            sections = conn.execute(
                """
                SELECT section_name, section_json
                FROM recipe_sections
                WHERE page_id = ?
                """,
                (page["id"],),
            ).fetchall()

    return {
        "id": page["id"],
        "title": page["title"],
        "sections": {
            row["section_name"]: json.loads(row["section_json"]) for row in sections
        },
    }


def _recommend_cocktails_by_scores(
    strength_score: int,
    sweet_dry_score: int,
    score_limit: int,
    max_results: int,
) -> list[dict[str, Any]]:
    with get_connection() as conn:
        if _is_postgres_conn(conn):
            rows = conn.execute(
                """
                SELECT p.id, p.url, p.title, p.status, p.scraped_at, rs.section_json
                FROM pages p
                JOIN recipe_sections rs ON rs.page_id = p.id
                WHERE rs.section_name = %s
                """,
                ("strength_taste_guide",),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT p.id, p.url, p.title, p.status, p.scraped_at, rs.section_json
                FROM pages p
                JOIN recipe_sections rs ON rs.page_id = p.id
                WHERE rs.section_name = ?
                """,
                ("strength_taste_guide",),
            ).fetchall()

    eligible: list[dict[str, Any]] = []

    for row in rows:
        try:
            guide = json.loads(row["section_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue

        row_strength = guide.get("strength_score")
        row_sweet_dry = guide.get("sweet_dry_score")
        if row_strength is None or row_sweet_dry is None:
            continue

        distance = abs(int(row_strength) - strength_score) + abs(int(row_sweet_dry) - sweet_dry_score)
        if distance <= score_limit:
            eligible.append(
                {
                    "id": row["id"],
                    "url": row["url"],
                    "title": row["title"],
                    "status": row["status"],
                    "scraped_at": row["scraped_at"],
                    "strength_score": int(row_strength),
                    "sweet_dry_score": int(row_sweet_dry),
                    "distance": distance,
                }
            )

    buckets: dict[int, list[dict[str, Any]]] = {}
    for item in eligible:
        buckets.setdefault(item["distance"], []).append(item)

    ordered: list[dict[str, Any]] = []
    for distance in sorted(buckets):
        random.shuffle(buckets[distance])
        ordered.extend(buckets[distance])

    return ordered[:max_results]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/tools/get_recipe")
def get_recipe(name: str = Query(..., min_length=1)) -> dict[str, Any]:
    recipe = _fetch_recipe_by_name(name)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


@app.get("/tools/get_recipe_by_id/{recipe_id}")
def get_recipe_by_id(recipe_id: int) -> dict[str, Any]:
    recipe = _fetch_recipe_by_id(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


@app.get("/tools/search_cocktails")
def search_cocktails(query: str = Query(..., min_length=1), limit: int = 10) -> dict[str, Any]:
    limit = max(1, min(limit, 50))
    with get_connection() as conn:
        if _is_postgres_conn(conn):
            rows = conn.execute(
                """
                SELECT id, url, title, status, scraped_at
                FROM pages
                WHERE lower(title) LIKE lower(%s)
                ORDER BY scraped_at DESC
                LIMIT %s
                """,
                (f"%{query}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, url, title, status, scraped_at
                FROM pages
                WHERE lower(title) LIKE lower(?)
                ORDER BY scraped_at DESC
                LIMIT ?
                """,
                (f"%{query}%", limit),
            ).fetchall()

    return {
        "count": len(rows),
        "results": [
            {
                "id": row["id"],
                "url": row["url"],
                "title": row["title"],
                "status": row["status"],
                "scraped_at": row["scraped_at"],
            }
            for row in rows
        ],
    }


@app.get("/tools/recommend_cocktails")
def recommend_cocktails(
    strength_score: int = Query(..., ge=0, le=10),
    sweet_dry_score: int = Query(..., ge=0, le=10),
    score_limit: int = Query(2, ge=0, le=10),
    max_results: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    recommendations = _recommend_cocktails_by_scores(
        strength_score=strength_score,
        sweet_dry_score=sweet_dry_score,
        score_limit=score_limit,
        max_results=max_results,
    )
    return {
        "count": len(recommendations),
        "input": {
            "strength_score": strength_score,
            "sweet_dry_score": sweet_dry_score,
            "score_limit": score_limit,
            "max_results": max_results,
        },
        "results": recommendations,
    }
