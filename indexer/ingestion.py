"""
ingestion.py — Upload transformed documents to Azure AI Search.

Handles batch uploading of cocktail documents to the cocktails-index,
with retry logic and error handling.
"""

from __future__ import annotations

import os
import json
import logging
from typing import Any
import requests

logger = logging.getLogger(__name__)


def upload_documents_via_rest_api(
    documents: list[dict[str, Any]],
    search_service_name: str | None = None,
    search_admin_key: str | None = None,
    index_name: str = "cocktails-index",
    batch_size: int = 1000,
) -> bool:
    """
    Upload documents to Azure AI Search via REST API.

    Uses direct HTTP requests to avoid shell/argument-size limits.
    Falls back to environment variables if parameters not provided.

    Args:
        documents: List of document dicts to upload
        search_service_name: Search service name (default: SEARCH_SERVICE_NAME env var)
        search_admin_key: Search admin API key (default: SEARCH_ADMIN_KEY env var)
        index_name: Index name (default: cocktails-index)
        batch_size: Documents per batch (default: 1000)

    Returns:
        True if all batches uploaded successfully, False otherwise
    """
    search_service_name = search_service_name or os.getenv("SEARCH_SERVICE_NAME", "").strip()
    search_admin_key = search_admin_key or os.getenv("SEARCH_ADMIN_KEY", "").strip()
    index_name = os.getenv("SEARCH_INDEX_NAME", index_name)

    if not search_service_name or not search_admin_key:
        logger.error("Missing SEARCH_SERVICE_NAME or SEARCH_ADMIN_KEY")
        return False

    if not documents:
        logger.warning("No documents to upload")
        return True

    search_url = f"https://{search_service_name}.search.windows.net"
    api_version = "2024-07-01"

    success_count = 0
    total_batches = (len(documents) + batch_size - 1) // batch_size

    for batch_idx in range(0, len(documents), batch_size):
        batch = documents[batch_idx : batch_idx + batch_size]
        batch_num = (batch_idx // batch_size) + 1

        # Prepare batch payload with 'value' wrapper
        payload = {"value": batch}
        payload_json = json.dumps(payload)

        try:
            logger.info(f"Uploading batch {batch_num}/{total_batches} ({len(batch)} documents)")
            response = requests.post(
                f"{search_url}/indexes/{index_name}/docs/index",
                params={"api-version": api_version},
                headers={
                    "api-key": search_admin_key,
                    "Content-Type": "application/json",
                },
                data=payload_json,
                timeout=60,
            )

            if response.ok:
                logger.info(f"Batch {batch_num}/{total_batches} uploaded successfully")
                success_count += 1
            else:
                logger.error(
                    f"Batch {batch_num} failed: HTTP {response.status_code} - {response.text}"
                )
        except requests.Timeout:
            logger.error(f"Batch {batch_num} upload timed out")
        except Exception as e:
            logger.error(f"Batch {batch_num} upload error: {e}")

    if success_count == total_batches:
        logger.info(f"✓ All {success_count} batches uploaded successfully")
        return True
    else:
        logger.error(f"Upload failed: {success_count}/{total_batches} batches succeeded")
        return False


def delete_all_documents(
    search_service_name: str | None = None,
    search_admin_key: str | None = None,
    index_name: str = "cocktails-index",
) -> bool:
    """
    Delete an index from Azure AI Search.

    Args:
        search_service_name: Search service name (default: SEARCH_SERVICE_NAME env var)
        search_admin_key: Search admin API key (default: SEARCH_ADMIN_KEY env var)
        index_name: Index name (default: cocktails-index)

    Returns:
        True if deletion successful, False otherwise
    """
    search_service_name = search_service_name or os.getenv("SEARCH_SERVICE_NAME", "").strip()
    search_admin_key = search_admin_key or os.getenv("SEARCH_ADMIN_KEY", "").strip()
    index_name = os.getenv("SEARCH_INDEX_NAME", index_name)

    if not search_service_name or not search_admin_key:
        logger.error("Missing SEARCH_SERVICE_NAME or SEARCH_ADMIN_KEY")
        return False

    search_url = f"https://{search_service_name}.search.windows.net"
    api_version = "2024-07-01"

    try:
        logger.info(f"Deleting index {index_name}")
        response = requests.delete(
            f"{search_url}/indexes/{index_name}",
            params={"api-version": api_version},
            headers={"api-key": search_admin_key},
            timeout=30,
        )

        if response.ok:
            logger.info(f"✓ Index {index_name} deleted")
            return True
        else:
            logger.error(f"Failed to delete index: HTTP {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Delete index error: {e}")
        return False
