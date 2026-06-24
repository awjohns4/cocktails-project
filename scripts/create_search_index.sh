#!/usr/bin/env bash
set -euo pipefail

SEARCH_SERVICE_NAME="${1:-${SEARCH_SERVICE_NAME:-}}"
SEARCH_ADMIN_KEY="${2:-${SEARCH_ADMIN_KEY:-}}"

if [[ -z "$SEARCH_SERVICE_NAME" ]]; then
  echo "Usage: $0 <SEARCH_SERVICE_NAME> <SEARCH_ADMIN_KEY>"
  echo ""
  echo "Examples:"
  echo "  $0 my-search-service <admin-key>"
  echo "  SEARCH_SERVICE_NAME=my-search-service SEARCH_ADMIN_KEY=<key> $0"
  exit 1
fi

if [[ -z "$SEARCH_ADMIN_KEY" ]]; then
  echo "SEARCH_ADMIN_KEY is required (pass as 2nd argument or SEARCH_ADMIN_KEY env var)"
  exit 1
fi

SEARCH_INDEX_NAME="${SEARCH_INDEX_NAME:-cocktails-index}"
SEARCH_API_VERSION="${SEARCH_API_VERSION:-2024-07-01}"
INDEX_SCHEMA_PATH="${INDEX_SCHEMA_PATH:-infra/search/cocktails-index.json}"

if [[ ! -f "$INDEX_SCHEMA_PATH" ]]; then
  echo "Index schema file not found: $INDEX_SCHEMA_PATH"
  exit 1
fi

echo "Creating/updating index '$SEARCH_INDEX_NAME' on service '$SEARCH_SERVICE_NAME'..."
az rest \
  --method put \
  --resource "https://${SEARCH_SERVICE_NAME}.search.windows.net" \
  --url "https://${SEARCH_SERVICE_NAME}.search.windows.net/indexes/${SEARCH_INDEX_NAME}?api-version=${SEARCH_API_VERSION}" \
  --headers "Content-Type=application/json" "api-key=${SEARCH_ADMIN_KEY}" \
  --body "@${INDEX_SCHEMA_PATH}" \
  --output json >/dev/null

echo "Index '$SEARCH_INDEX_NAME' is ready."
