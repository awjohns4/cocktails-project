from __future__ import annotations

import hmac
import json
import os
import random
import logging
from typing import Any

import requests
from azure.identity import ManagedIdentityCredential
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from indexer.embeddings import embed_texts_with_fallback
from scraper.database import get_connection


def _is_postgres_conn(conn: Any) -> bool:
    return conn.__class__.__module__.startswith("psycopg")


logger = logging.getLogger(__name__)

app = FastAPI(title="cocktail-mcp-api", version="0.1.0")
EXPECTED_API_KEY = os.getenv("MCP_API_KEY", "").strip()


def _get_search_credentials() -> tuple[str, str, str] | None:
    service_name = os.getenv("SEARCH_SERVICE_NAME", "").strip()
    admin_key = os.getenv("SEARCH_ADMIN_KEY", "").strip()
    index_name = os.getenv("SEARCH_INDEX_NAME", "cocktails-index").strip() or "cocktails-index"

    if not service_name or not admin_key:
        return None

    return service_name, admin_key, index_name


def _escape_filter_value(value: str) -> str:
    return value.replace("'", "''")


def _build_hybrid_filter(
    min_strength: float | None,
    max_strength: float | None,
    min_sweet_dry: float | None,
    max_sweet_dry: float | None,
    include_ingredients: list[str] | None,
    exclude_ingredients: list[str] | None,
) -> str | None:
    clauses: list[str] = []

    if min_strength is not None:
        clauses.append(f"strengthScore ge {min_strength}")
    if max_strength is not None:
        clauses.append(f"strengthScore le {max_strength}")
    if min_sweet_dry is not None:
        clauses.append(f"sweetDryScore ge {min_sweet_dry}")
    if max_sweet_dry is not None:
        clauses.append(f"sweetDryScore le {max_sweet_dry}")

    for ingredient in include_ingredients or []:
        term = ingredient.strip()
        if not term:
            continue
        escaped = _escape_filter_value(term)
        clauses.append(f"search.ismatch('{escaped}', 'ingredients', 'simple', 'any')")

    for ingredient in exclude_ingredients or []:
        term = ingredient.strip()
        if not term:
            continue
        escaped = _escape_filter_value(term)
        clauses.append(f"not search.ismatch('{escaped}', 'ingredients', 'simple', 'any')")

    if not clauses:
        return None
    return " and ".join(clauses)


def _search_cocktails_hybrid(
    query: str,
    limit: int,
    min_strength: float | None,
    max_strength: float | None,
    min_sweet_dry: float | None,
    max_sweet_dry: float | None,
    include_ingredients: list[str] | None,
    exclude_ingredients: list[str] | None,
) -> list[dict[str, Any]]:
    creds = _get_search_credentials()
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SEARCH_SERVICE_NAME/SEARCH_ADMIN_KEY are required for hybrid mode",
        )

    service_name, admin_key, index_name = creds

    embeddings = embed_texts_with_fallback([query])
    if not embeddings:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to generate query embedding",
        )

    vector = embeddings[0]
    payload: dict[str, Any] = {
        "search": query,
        "top": limit,
        "queryType": "semantic",
        "semanticConfiguration": "cocktails-semantic-config",
        "vectorQueries": [
            {
                "kind": "vector",
                "fields": "searchContentVector",
                "vector": vector,
                "k": max(20, limit * 5),
            }
        ],
        "select": "id,cocktailName,sourceUrl,strengthScore,sweetDryScore,ingredients,flavorTags,lastUpdated",
    }

    search_filter = _build_hybrid_filter(
        min_strength=min_strength,
        max_strength=max_strength,
        min_sweet_dry=min_sweet_dry,
        max_sweet_dry=max_sweet_dry,
        include_ingredients=include_ingredients,
        exclude_ingredients=exclude_ingredients,
    )
    if search_filter:
        payload["filter"] = search_filter

    response = requests.post(
        f"https://{service_name}.search.windows.net/indexes/{index_name}/docs/search",
        params={"api-version": "2024-07-01"},
        headers={"api-key": admin_key, "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )

    if not response.ok:
        logger.error("Hybrid search failed: %s %s", response.status_code, response.text)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Hybrid retrieval query failed",
        )

    hits = response.json().get("value", [])
    hydrated_results: list[dict[str, Any]] = []

    for hit in hits:
        doc_id = str(hit.get("id", "")).strip()
        recipe = None
        if doc_id.isdigit():
            recipe = _fetch_recipe_by_id(int(doc_id))

        hydrated_results.append(
            {
                "id": doc_id,
                "title": (recipe or {}).get("title") or hit.get("cocktailName", ""),
                "url": hit.get("sourceUrl"),
                "strength_score": hit.get("strengthScore"),
                "sweet_dry_score": hit.get("sweetDryScore"),
                "ingredients": hit.get("ingredients") or [],
                "flavor_tags": hit.get("flavorTags") or [],
                "last_updated": hit.get("lastUpdated"),
                "search_score": hit.get("@search.score"),
                "reranker_score": hit.get("@search.rerankerScore"),
                "recipe": recipe,
            }
        )

    return hydrated_results


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
def search_cocktails(
    query: str = Query(..., min_length=1),
    limit: int = 10,
    mode: str = Query("keyword", pattern="^(keyword|hybrid)$"),
    min_strength: float | None = Query(None, ge=0, le=10),
    max_strength: float | None = Query(None, ge=0, le=10),
    min_sweet_dry: float | None = Query(None, ge=0, le=10),
    max_sweet_dry: float | None = Query(None, ge=0, le=10),
    include_ingredient: list[str] | None = Query(None),
    exclude_ingredient: list[str] | None = Query(None),
) -> dict[str, Any]:
    limit = max(1, min(limit, 50))

    if mode == "hybrid":
        if min_strength is not None and max_strength is not None and min_strength > max_strength:
            raise HTTPException(status_code=400, detail="min_strength cannot be greater than max_strength")
        if (
            min_sweet_dry is not None
            and max_sweet_dry is not None
            and min_sweet_dry > max_sweet_dry
        ):
            raise HTTPException(status_code=400, detail="min_sweet_dry cannot be greater than max_sweet_dry")

        results = _search_cocktails_hybrid(
            query=query,
            limit=limit,
            min_strength=min_strength,
            max_strength=max_strength,
            min_sweet_dry=min_sweet_dry,
            max_sweet_dry=max_sweet_dry,
            include_ingredients=include_ingredient,
            exclude_ingredients=exclude_ingredient,
        )
        return {
            "count": len(results),
            "mode": "hybrid",
            "input": {
                "query": query,
                "limit": limit,
                "min_strength": min_strength,
                "max_strength": max_strength,
                "min_sweet_dry": min_sweet_dry,
                "max_sweet_dry": max_sweet_dry,
                "include_ingredient": include_ingredient or [],
                "exclude_ingredient": exclude_ingredient or [],
            },
            "results": results,
        }


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
        "mode": "keyword",
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


@app.get("/tools/recommend_cocktails_hybrid")
def recommend_cocktails_hybrid(
    preferences: str = Query(..., min_length=1, description="Natural language description of desired cocktail (e.g. 'citrusy and refreshing, not too strong')"),
    limit: int = Query(5, ge=1, le=20),
    min_strength: float | None = Query(None, ge=0, le=10),
    max_strength: float | None = Query(None, ge=0, le=10),
    min_sweet_dry: float | None = Query(None, ge=0, le=10),
    max_sweet_dry: float | None = Query(None, ge=0, le=10),
    include_ingredient: list[str] | None = Query(None, description="Ingredient that must appear in candidates"),
    exclude_ingredient: list[str] | None = Query(None, description="Ingredient to exclude from candidates"),
) -> dict[str, Any]:
    """Recommend cocktails using hybrid semantic + keyword + metadata-filter retrieval.

    Pass natural language preferences and optional structured constraints.
    Results are ranked by semantic relevance and re-ranked by Azure AI Search semantic re-ranker.
    Each result is hydrated with full recipe details from PostgreSQL.
    """
    if min_strength is not None and max_strength is not None and min_strength > max_strength:
        raise HTTPException(status_code=400, detail="min_strength cannot exceed max_strength")
    if min_sweet_dry is not None and max_sweet_dry is not None and min_sweet_dry > max_sweet_dry:
        raise HTTPException(status_code=400, detail="min_sweet_dry cannot exceed max_sweet_dry")

    results = _search_cocktails_hybrid(
        query=preferences,
        limit=limit,
        min_strength=min_strength,
        max_strength=max_strength,
        min_sweet_dry=min_sweet_dry,
        max_sweet_dry=max_sweet_dry,
        include_ingredients=include_ingredient,
        exclude_ingredients=exclude_ingredient,
    )

    return {
        "count": len(results),
        "input": {
            "preferences": preferences,
            "limit": limit,
            "min_strength": min_strength,
            "max_strength": max_strength,
            "min_sweet_dry": min_sweet_dry,
            "max_sweet_dry": max_sweet_dry,
            "include_ingredient": include_ingredient or [],
            "exclude_ingredient": exclude_ingredient or [],
        },
        "results": results,
    }


@app.post("/tools/trigger_reindex")
def trigger_reindex() -> dict[str, Any]:
    """Trigger a manual reindex run of the cocktail indexer Container App Job.

    Starts the indexer job in Azure Container Apps. Access is restricted to
    authenticated callers via x-api-key middleware.

    Returns the execution name and the accepted status so callers can poll
    for completion if needed.
    """
    sub = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()
    rg = os.getenv("INDEXER_RESOURCE_GROUP", "").strip()
    job = os.getenv("INDEXER_JOB_NAME", "").strip()
    mi_client_id = os.getenv("MANAGED_IDENTITY_CLIENT_ID", "").strip()

    if not sub or not rg or not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AZURE_SUBSCRIPTION_ID, INDEXER_RESOURCE_GROUP, and INDEXER_JOB_NAME must be configured",
        )

    try:
        credential = ManagedIdentityCredential(client_id=mi_client_id or None)
        token = credential.get_token("https://management.azure.com/.default").token
    except Exception as exc:
        logger.error("Failed to obtain managed identity token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to authenticate with Azure management API",
        ) from exc

    url = (
        f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}"
        f"/providers/Microsoft.App/jobs/{job}/start"
        "?api-version=2024-03-01"
    )
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={},
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.error("Request to start indexer job failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to communicate with Azure management API",
        ) from exc

    if response.status_code not in (200, 202):
        logger.error("Start indexer job returned %s: %s", response.status_code, response.text)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Azure returned {response.status_code}: {response.text}",
        )

    body = response.json() if response.text else {}
    execution_name = body.get("name", "")
    logger.info("Triggered reindex job; execution: %s", execution_name)

    return {
        "status": "accepted",
        "job": job,
        "execution_name": execution_name,
        "message": "Indexer job started. Check Azure Container Apps for execution status.",
    }


def _search_cocktails_semantic_only(
    query: str,
    limit: int,
    min_strength: float | None,
    max_strength: float | None,
    min_sweet_dry: float | None,
    max_sweet_dry: float | None,
    include_ingredients: list[str] | None,
    exclude_ingredients: list[str] | None,
) -> list[dict[str, Any]]:
    """Pure vector + semantic re-ranking search — no BM25 keyword component."""
    creds = _get_search_credentials()
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SEARCH_SERVICE_NAME/SEARCH_ADMIN_KEY are required for semantic search",
        )

    service_name, admin_key, index_name = creds

    embeddings = embed_texts_with_fallback([query])
    if not embeddings:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to generate query embedding",
        )

    vector = embeddings[0]
    payload: dict[str, Any] = {
        # Empty search string → pure vector, no BM25 keyword scoring
        "search": "",
        "top": limit,
        "queryType": "semantic",
        "semanticConfiguration": "cocktails-semantic-config",
        "vectorQueries": [
            {
                "kind": "vector",
                "fields": "searchContentVector",
                "vector": vector,
                "k": max(20, limit * 5),
            }
        ],
        "select": "id,cocktailName,sourceUrl,strengthScore,sweetDryScore,ingredients,flavorTags,lastUpdated",
    }

    search_filter = _build_hybrid_filter(
        min_strength=min_strength,
        max_strength=max_strength,
        min_sweet_dry=min_sweet_dry,
        max_sweet_dry=max_sweet_dry,
        include_ingredients=include_ingredients,
        exclude_ingredients=exclude_ingredients,
    )
    if search_filter:
        payload["filter"] = search_filter

    response = requests.post(
        f"https://{service_name}.search.windows.net/indexes/{index_name}/docs/search",
        params={"api-version": "2024-07-01"},
        headers={"api-key": admin_key, "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )

    if not response.ok:
        logger.error("Semantic search failed: %s %s", response.status_code, response.text)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Semantic search query failed",
        )

    hits = response.json().get("value", [])
    results: list[dict[str, Any]] = []

    for hit in hits:
        doc_id = str(hit.get("id", "")).strip()
        recipe = None
        if doc_id.isdigit():
            recipe = _fetch_recipe_by_id(int(doc_id))

        results.append(
            {
                "id": doc_id,
                "title": (recipe or {}).get("title") or hit.get("cocktailName", ""),
                "url": hit.get("sourceUrl"),
                "strength_score": hit.get("strengthScore"),
                "sweet_dry_score": hit.get("sweetDryScore"),
                "ingredients": hit.get("ingredients") or [],
                "flavor_tags": hit.get("flavorTags") or [],
                "last_updated": hit.get("lastUpdated"),
                "search_score": hit.get("@search.score"),
                "reranker_score": hit.get("@search.rerankerScore"),
                "recipe": recipe,
            }
        )

    return results


@app.get("/tools/search_cocktails_semantic")
def search_cocktails_semantic(
    query: str = Query(..., min_length=1, description="Natural language search query (e.g. 'something citrusy and tropical')"),
    limit: int = Query(5, ge=1, le=20),
    min_strength: float | None = Query(None, ge=0, le=10),
    max_strength: float | None = Query(None, ge=0, le=10),
    min_sweet_dry: float | None = Query(None, ge=0, le=10),
    max_sweet_dry: float | None = Query(None, ge=0, le=10),
    include_ingredient: list[str] | None = Query(None, description="Ingredient that must appear in results"),
    exclude_ingredient: list[str] | None = Query(None, description="Ingredient to exclude from results"),
) -> dict[str, Any]:
    """Search cocktails using pure semantic vector search with optional metadata filters.

    Unlike recommend_cocktails_hybrid, this tool uses only vector similarity (no BM25 keyword
    scoring), making it better for open-ended discovery queries where semantic intent matters
    more than exact keyword matches.
    """
    if min_strength is not None and max_strength is not None and min_strength > max_strength:
        raise HTTPException(status_code=400, detail="min_strength cannot exceed max_strength")
    if min_sweet_dry is not None and max_sweet_dry is not None and min_sweet_dry > max_sweet_dry:
        raise HTTPException(status_code=400, detail="min_sweet_dry cannot exceed max_sweet_dry")

    results = _search_cocktails_semantic_only(
        query=query,
        limit=limit,
        min_strength=min_strength,
        max_strength=max_strength,
        min_sweet_dry=min_sweet_dry,
        max_sweet_dry=max_sweet_dry,
        include_ingredients=include_ingredient,
        exclude_ingredients=exclude_ingredient,
    )

    return {
        "count": len(results),
        "mode": "semantic",
        "input": {
            "query": query,
            "limit": limit,
            "min_strength": min_strength,
            "max_strength": max_strength,
            "min_sweet_dry": min_sweet_dry,
            "max_sweet_dry": max_sweet_dry,
            "include_ingredient": include_ingredient or [],
            "exclude_ingredient": exclude_ingredient or [],
        },
        "results": results,
    }
