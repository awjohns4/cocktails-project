"""
transformer.py — Transform recipe data from PostgreSQL into Azure AI Search documents.

Converts recipe sections from the database into structured documents that match
the cocktails-index schema (17 fields including vector embeddings).
"""

from __future__ import annotations

import json
import logging
from typing import Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


def _coerce_string_list(values: Any) -> list[str]:
    """Normalize a value into a list of strings for Search collection fields."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [v.strip() for v in values.split(",")]
    elif not isinstance(values, list):
        values = [values]

    normalized: list[str] = []
    for item in values:
        if item is None:
            continue
        if isinstance(item, dict):
            ingredient = str(item.get("ingredient", "")).strip()
            amount = str(item.get("amount", "")).strip()
            text = f"{amount} {ingredient}".strip() if (amount or ingredient) else ""
            if text:
                normalized.append(text)
            continue
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


@dataclass
class SearchDocument:
    """Represents a single cocktail document for Azure AI Search."""

    id: str
    cocktailName: str
    aliases: list[str]
    baseSpirit: str
    sourceUrl: str
    lastUpdated: str
    strengthScore: float
    sweetDryScore: float
    ingredients: list[str]
    flavorTags: list[str]
    ingredientsText: str
    prepareText: str
    garnishText: str
    reviewText: str
    historyText: str
    searchContent: str
    searchContentVector: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, filtering out None vectors for upsert."""
        doc = asdict(self)
        if doc.get("searchContentVector") is None:
            del doc["searchContentVector"]
        return doc


def transform_recipe_to_document(
    page_id: str | int,
    recipe_json: dict[str, Any],
    embedding: list[float] | None = None,
) -> SearchDocument:
    """
    Transform a recipe from PostgreSQL into a SearchDocument.

    Args:
        page_id: Unique identifier for the recipe (from pages table)
        recipe_json: Recipe data from recipe_sections.section_json
        embedding: Optional vector embedding for searchContent

    Returns:
        SearchDocument ready for Azure AI Search ingestion

    Raises:
        ValueError: If required fields are missing from recipe_json
    """
    # Required fields
    cocktail_name = recipe_json.get("name", "").strip()
    if not cocktail_name:
        raise ValueError(f"Recipe {page_id} missing 'name' field")

    # Structured fields
    base_spirit = recipe_json.get("baseSpirit", "").strip()
    source_url = recipe_json.get("sourceUrl", "").strip()
    last_updated = recipe_json.get("lastUpdated", "")

    # Scores (default to 0.0 if missing)
    strength_score = float(recipe_json.get("strengthScore", 0.0))
    sweet_dry_score = float(recipe_json.get("sweetDryScore", 0.0))

    # Collections (default to empty list if missing)
    aliases = _coerce_string_list(recipe_json.get("aliases", []))

    ingredients = _coerce_string_list(recipe_json.get("ingredients", []))

    flavor_tags = _coerce_string_list(recipe_json.get("flavorTags", []))

    # Text fields (default to empty string if missing)
    ingredients_text = recipe_json.get("ingredientsText", "").strip()
    prepare_text = recipe_json.get("prepareText", "").strip()
    garnish_text = recipe_json.get("garnishText", "").strip()
    review_text = recipe_json.get("reviewText", "").strip()
    history_text = recipe_json.get("historyText", "").strip()

    # Build composite searchContent for hybrid queries
    search_content_parts = [
        cocktail_name,
        " ".join(aliases),
        base_spirit,
        ingredients_text,
        prepare_text,
        garnish_text,
        " ".join(flavor_tags),
        review_text,
        history_text,
    ]
    search_content = " ".join(p for p in search_content_parts if p).strip()

    logger.debug(f"Transformed recipe {page_id} ({cocktail_name}) into search document")

    return SearchDocument(
        id=str(page_id),
        cocktailName=cocktail_name,
        aliases=aliases,
        baseSpirit=base_spirit,
        sourceUrl=source_url,
        lastUpdated=last_updated,
        strengthScore=strength_score,
        sweetDryScore=sweet_dry_score,
        ingredients=ingredients,
        flavorTags=flavor_tags,
        ingredientsText=ingredients_text,
        prepareText=prepare_text,
        garnishText=garnish_text,
        reviewText=review_text,
        historyText=history_text,
        searchContent=search_content,
        searchContentVector=embedding,
    )


def batch_transform_recipes(
    recipes: list[tuple[str, dict[str, Any], list[float] | None]],
) -> list[SearchDocument]:
    """
    Transform multiple recipes into search documents.

    Args:
        recipes: List of (page_id, recipe_json, embedding) tuples

    Returns:
        List of SearchDocument objects
    """
    documents = []
    for page_id, recipe_json, embedding in recipes:
        try:
            doc = transform_recipe_to_document(page_id, recipe_json, embedding)
            documents.append(doc)
        except ValueError as e:
            logger.warning(f"Skipping recipe {page_id}: {e}")
    return documents
