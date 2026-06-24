"""
embeddings.py — Azure OpenAI embedding generation with fallback and retry logic.

Generates vector embeddings using text-embedding-3-small model across two regions
(primary West US, secondary East US) with automatic failover and batch processing.
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any
from urllib.parse import urlsplit
from openai import AzureOpenAI, APIError
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

logger = logging.getLogger(__name__)

# Configuration
EMBEDDING_MODEL: str = "text-embedding-3-small"
EMBEDDING_DIMENSIONS: int = 1536
BATCH_SIZE: int = 100  # Max texts per batch
MAX_RETRIES: int = 3
RETRY_DELAY_SEC: float = 2.0  # Base delay; increases exponentially
REQUEST_TIMEOUT_SEC: int = 60

# Key Vault setup
_KV_CLIENT: SecretClient | None = None


def _normalize_key_vault_uri(raw_uri: str) -> str:
    """Normalize Key Vault URI to a valid https URL and tolerate duplicate dots."""
    uri = raw_uri.strip().strip('"').strip("'")
    if not uri:
        return ""

    if not uri.startswith(("http://", "https://")):
        uri = f"https://{uri}"

    parts = urlsplit(uri)
    host = (parts.netloc or parts.path or "").strip().strip("/")
    while ".." in host:
        host = host.replace("..", ".")

    # Key Vault requires https; ignore path/query/fragment from env value.
    return f"https://{host}" if host else ""


def _get_keyvault_client() -> SecretClient | None:
    """
    Initialize and cache the Key Vault SecretClient.
    Uses DefaultAzureCredential for authentication.
    """
    global _KV_CLIENT
    if _KV_CLIENT is not None:
        return _KV_CLIENT

    kv_url = _normalize_key_vault_uri(os.getenv("KEY_VAULT_URI", ""))
    if not kv_url:
        logger.debug("KEY_VAULT_URI not set; skipping Key Vault client initialization")
        return None

    try:
        credential = DefaultAzureCredential()
        _KV_CLIENT = SecretClient(vault_url=kv_url, credential=credential)
        logger.debug(f"Initialized Key Vault client for {kv_url}")
        return _KV_CLIENT
    except Exception as e:
        logger.error(f"Failed to initialize Key Vault client: {e}")
        return None


def _get_credential_from_env_or_keyvault(
    endpoint_var: str,
    key_var: str,
    kv_endpoint_secret: str,
    kv_key_secret: str,
    endpoint_var_aliases: list[str] | None = None,
    key_var_aliases: list[str] | None = None,
) -> tuple[str, str] | None:
    """
    Fetch endpoint and key from Key Vault by default.
    Falls back to environment variables if Key Vault is unavailable.

    Args:
        endpoint_var: Environment variable name for endpoint
        key_var: Environment variable name for key
        kv_endpoint_secret: Key Vault secret name for endpoint
        kv_key_secret: Key Vault secret name for key

    Returns:
        Tuple of (endpoint, key) or None if not found
    """
    # Try Key Vault first
    kv_client = _get_keyvault_client()
    if kv_client:
        try:
            endpoint = kv_client.get_secret(kv_endpoint_secret).value
            key = kv_client.get_secret(kv_key_secret).value
            if endpoint and key:
                logger.debug(f"Retrieved credentials from Key Vault ({kv_endpoint_secret}, {kv_key_secret})")
                return (endpoint, key)
        except Exception as e:
            logger.warning(f"Failed to retrieve credentials from Key Vault: {e}")

    # Fall back to environment variables (supports aliases for backward compatibility)
    endpoint_candidates = [endpoint_var] + (endpoint_var_aliases or [])
    key_candidates = [key_var] + (key_var_aliases or [])

    endpoint = ""
    key = ""
    for var_name in endpoint_candidates:
        endpoint = os.getenv(var_name, "").strip()
        if endpoint:
            break

    for var_name in key_candidates:
        key = os.getenv(var_name, "").strip()
        if key:
            break

    if endpoint and key:
        logger.debug("Using OpenAI credentials from environment variables")
        return (endpoint, key)

    return None


def _get_openai_client(region: str = "primary") -> AzureOpenAI | None:
    """
    Create an Azure OpenAI client for the specified region.
    Returns None if credentials are not available.
    """
    if region == "primary":
        endpoint_var = "OPENAI_PRIMARY_ENDPOINT"
        key_var = "OPENAI_PRIMARY_KEY"
        endpoint_var_aliases = ["OPENAI_API_ENDPOINT"]
        key_var_aliases = ["OPENAI_API_KEY"]
        kv_endpoint_secret = "openai-primary-endpoint"
        kv_key_secret = "openai-primary-key"
    elif region == "secondary":
        endpoint_var = "OPENAI_SECONDARY_ENDPOINT"
        key_var = "OPENAI_SECONDARY_KEY"
        endpoint_var_aliases = ["OPENAI_API_ENDPOINT_SECONDARY"]
        key_var_aliases = ["OPENAI_API_KEY_SECONDARY"]
        kv_endpoint_secret = "openai-secondary-endpoint"
        kv_key_secret = "openai-secondary-key"
    else:
        raise ValueError(f"Unknown region: {region}")

    creds = _get_credential_from_env_or_keyvault(
        endpoint_var,
        key_var,
        kv_endpoint_secret,
        kv_key_secret,
        endpoint_var_aliases=endpoint_var_aliases,
        key_var_aliases=key_var_aliases,
    )
    if not creds:
        logger.warning(f"Credentials not found for {region} region")
        return None

    endpoint, key = creds
    try:
        client = AzureOpenAI(api_key=key, api_version="2024-08-01-preview", azure_endpoint=endpoint)
        logger.debug(f"Created Azure OpenAI client for {region} region")
        return client
    except Exception as e:
        logger.error(f"Failed to create Azure OpenAI client for {region}: {e}")
        return None


def embed_texts(
    texts: list[str], region: str = "primary", retry_on_failure: bool = True
) -> list[list[float]] | None:
    """
    Embed a list of texts using Azure OpenAI text-embedding-3-small.

    Args:
        texts: List of text strings to embed.
        region: "primary" (West US) or "secondary" (East US).
        retry_on_failure: If True, retry with exponential backoff on failure.

    Returns:
        List of embedding vectors (each 1536 dimensions), or None if all retries failed.
    """
    if not texts:
        logger.warning("No texts provided for embedding")
        return None

    for attempt in range(MAX_RETRIES):
        client = _get_openai_client(region)
        if not client:
            logger.error(f"Cannot create client for {region} region, attempt {attempt + 1}/{MAX_RETRIES}")
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY_SEC * (2 ** attempt)
                logger.info(f"Retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)
            continue

        try:
            logger.debug(f"Requesting embeddings for {len(texts)} texts from {region} region")
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=texts,
                dimensions=EMBEDDING_DIMENSIONS,
                timeout=REQUEST_TIMEOUT_SEC,
            )
            embeddings = [item.embedding for item in response.data]
            logger.info(f"Successfully embedded {len(embeddings)} texts from {region} region")
            return embeddings
        except APIError as e:
            logger.error(f"API error on attempt {attempt + 1}/{MAX_RETRIES}: {e}")
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY_SEC * (2 ** attempt)
                logger.info(f"Retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)
        except Exception as e:
            logger.error(f"Unexpected error on attempt {attempt + 1}/{MAX_RETRIES}: {e}")
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY_SEC * (2 ** attempt)
                logger.info(f"Retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)

    logger.error(f"Failed to embed texts after {MAX_RETRIES} attempts")
    return None


def embed_texts_with_fallback(texts: list[str]) -> list[list[float]] | None:
    """
    Embed texts with automatic fallover: try primary (West US) first,
    then fall back to secondary (East US) if primary fails.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of embedding vectors (each 1536 dimensions), or None if both regions fail.
    """
    logger.info(f"Starting embedding request for {len(texts)} texts (primary first)")

    # Try primary region first
    embeddings = embed_texts(texts, region="primary", retry_on_failure=True)
    if embeddings:
        return embeddings

    logger.warning("Primary region (West US) failed; trying secondary region (East US)")
    # Try secondary region
    embeddings = embed_texts(texts, region="secondary", retry_on_failure=True)
    if embeddings:
        return embeddings

    logger.error("Both regions exhausted; embedding failed")
    return None


def batch_embed_texts(
    texts: list[str], batch_size: int = BATCH_SIZE
) -> dict[int, list[float]] | None:
    """
    Embed texts in batches to stay within API rate limits.

    Args:
        texts: List of text strings to embed.
        batch_size: Number of texts per batch.

    Returns:
        Dict mapping original text index to embedding vector, or None if any batch fails.
    """
    if not texts:
        logger.warning("No texts provided for batch embedding")
        return None

    embeddings_map: dict[int, list[float]] = {}
    total_batches = (len(texts) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        start_idx = batch_idx * batch_size
        end_idx = min((batch_idx + 1) * batch_size, len(texts))
        batch_texts = texts[start_idx:end_idx]

        logger.info(f"Processing batch {batch_idx + 1}/{total_batches} ({len(batch_texts)} texts)")

        batch_embeddings = embed_texts_with_fallback(batch_texts)
        if not batch_embeddings:
            logger.error(f"Batch {batch_idx + 1} failed; aborting")
            return None

        # Map original indices to embeddings
        for i, embedding in enumerate(batch_embeddings):
            original_idx = start_idx + i
            embeddings_map[original_idx] = embedding

    logger.info(f"Successfully embedded {len(embeddings_map)} texts in {total_batches} batches")
    return embeddings_map
