"""
job.py — Main indexer job entry point.

Orchestrates the complete indexing pipeline:
1. Read recipe data from PostgreSQL
2. Transform recipes into search documents
3. Generate embeddings for each document
4. Upload documents to Azure AI Search
"""

from __future__ import annotations

import os
import sys
import json
import logging
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Import application modules
from scraper.database import get_connection
from indexer.embeddings import batch_embed_texts
from indexer.transformer import batch_transform_recipes
from indexer.ingestion import upload_documents_via_rest_api


def fetch_recipes_from_db() -> list[tuple[str, dict[str, Any]]]:
    """
    Fetch all recipe data from PostgreSQL, aggregating sections per page.

    Returns:
        List of (page_id, recipe_json) tuples where recipe_json is a complete recipe object
    """
    recipes = []
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get all pages with their recipe sections grouped by page_id
                cur.execute(
                    """
                    SELECT 
                        p.id, p.title, p.url, p.scraped_at,
                        r.section_name, r.section_json
                    FROM pages p
                    LEFT JOIN recipe_sections r ON p.id = r.page_id
                    ORDER BY p.id, r.section_name
                    """
                )
                
                current_page_id = None
                recipe_data = {}
                
                for row in cur.fetchall():
                    page_id = row['id']
                    
                    # When we hit a new page, save the previous one
                    if current_page_id is not None and page_id != current_page_id:
                        if recipe_data:
                            recipes.append((current_page_id, recipe_data))
                        recipe_data = {}
                    
                    current_page_id = page_id
                    
                    # Initialize page fields if this is the first row for this page
                    if not recipe_data:
                        recipe_data['name'] = row['title'] or ''
                        recipe_data['sourceUrl'] = row['url'] or ''
                        scraped_at = row['scraped_at']
                        if scraped_at and hasattr(scraped_at, 'isoformat'):
                            recipe_data['lastUpdated'] = scraped_at.isoformat()
                        else:
                            recipe_data['lastUpdated'] = str(scraped_at) if scraped_at else ''
                    
                    # Parse and aggregate section data
                    section_name = row['section_name']
                    section_json = row['section_json']
                    
                    if section_json is None:
                        continue
                    
                    if isinstance(section_json, str):
                        section_json = json.loads(section_json)
                    
                    # Map section names to recipe fields
                    if section_name == 'ingredients':
                        # section_json is a list of ingredient dicts
                        recipe_data['ingredients'] = section_json if isinstance(section_json, list) else []
                        recipe_data['ingredientsText'] = ', '.join([
                            f"{i.get('amount', '')} {i.get('ingredient', '')}".strip()
                            for i in section_json if isinstance(section_json, list)
                        ])
                    elif section_name == 'prepare':
                        # section_json is a list of prepare steps
                        recipe_data['prepareText'] = ' '.join(section_json) if isinstance(section_json, list) else str(section_json)
                    elif section_name == 'how_to_make':
                        # Already captured as part of prepareText, but store as separate field if needed
                        recipe_data['reviewText'] = ' '.join(section_json) if isinstance(section_json, list) else str(section_json)
                    elif section_name == 'garnish':
                        # section_json is a list of garnish items
                        recipe_data['garnishText'] = ' '.join(section_json) if isinstance(section_json, list) else str(section_json)
                    elif section_name == 'strength_taste_guide':
                        # section_json is a dict with strength_score and sweet_dry_score
                        if isinstance(section_json, dict):
                            recipe_data['strengthScore'] = section_json.get('strength_score', 0.0)
                            recipe_data['sweetDryScore'] = section_json.get('sweet_dry_score', 0.0)
                
                # Don't forget the last page
                if current_page_id is not None and recipe_data:
                    recipes.append((current_page_id, recipe_data))
        
        logger.info(f"Fetched {len(recipes)} recipes from database")
        return recipes
    except Exception as e:
        logger.error(f"Failed to fetch recipes: {e}")
        return []


def run_indexer_job() -> int:
    """
    Main indexer job.

    Returns:
        0 on success, 1 on failure
    """
    logger.info("Starting indexer job...")

    # Step 1: Fetch recipes
    logger.info("Step 1: Fetching recipes from PostgreSQL...")
    recipes = fetch_recipes_from_db()
    if not recipes:
        logger.warning("No recipes found in database")
        return 1

    # Step 2: Generate embeddings
    logger.info("Step 2: Generating embeddings...")
    recipe_ids = [page_id for page_id, _ in recipes]
    search_contents = []

    # First, transform recipes to get searchContent
    temp_recipes = []
    for page_id, recipe_json in recipes:
        try:
            from indexer.transformer import transform_recipe_to_document

            doc = transform_recipe_to_document(page_id, recipe_json, embedding=None)
            search_contents.append(doc.searchContent)
            temp_recipes.append((page_id, recipe_json))
        except ValueError as e:
            logger.warning(f"Skipping recipe {page_id}: {e}")

    if not search_contents:
        logger.error("No valid recipes to index")
        return 1

    # Generate embeddings
    embedding_map = batch_embed_texts(search_contents)
    if not embedding_map:
        logger.error("Failed to generate embeddings")
        return 1

    logger.info(f"Generated embeddings for {len(embedding_map)} recipes")

    # Step 3: Transform recipes into search documents
    logger.info("Step 3: Transforming recipes into search documents...")
    recipes_with_embeddings = [
        (page_id, recipe_json, embedding_map.get(idx))
        for idx, (page_id, recipe_json) in enumerate(temp_recipes)
    ]

    documents = batch_transform_recipes(recipes_with_embeddings)
    logger.info(f"Transformed {len(documents)} recipes into search documents")

    if not documents:
        logger.error("No documents to upload")
        return 1

    # Step 4: Upload to Azure AI Search
    logger.info("Step 4: Uploading documents to Azure AI Search...")
    doc_dicts = [doc.to_dict() for doc in documents]
    success = upload_documents_via_rest_api(doc_dicts)

    if success:
        logger.info(f"✓ Indexing job completed successfully ({len(documents)} documents)")
        return 0
    else:
        logger.error("Failed to upload documents to Azure AI Search")
        return 1


if __name__ == "__main__":
    exit_code = run_indexer_job()
    sys.exit(exit_code)
