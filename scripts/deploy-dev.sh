#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${POSTGRES_ADMIN_USERNAME:-}" ]]; then
  echo "POSTGRES_ADMIN_USERNAME is required"
  exit 1
fi

if [[ -z "${POSTGRES_ADMIN_PASSWORD:-}" ]]; then
  echo "POSTGRES_ADMIN_PASSWORD is required"
  exit 1
fi

if [[ -z "${MCP_API_KEY:-}" ]]; then
  if command -v openssl >/dev/null 2>&1; then
    MCP_API_KEY="$(openssl rand -hex 32)"
  else
    MCP_API_KEY="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  fi
  echo "MCP_API_KEY not provided. Generated a new key for this deployment and stored it in Key Vault."
fi
export MCP_API_KEY

RG_NAME="rg-cocktailagent-dev-wus-01"
LOCATION="westus"
ACR_NAME="acrcocktailagentdevwus01"

az group create --name "$RG_NAME" --location "$LOCATION" --tags Owner=adam.johns@neudesic.com >/dev/null

# Phase 1: Deploy infrastructure (ACR, Key Vault, Postgres, managed identity, Container Apps env).
# Container apps may fail if ACR has no images yet — that is expected and handled in Phase 2.
echo "Phase 1: Deploying infrastructure..."
az deployment group create \
  --resource-group "$RG_NAME" \
  --template-file infra/main.bicep \
  --parameters infra/parameters/dev.bicepparam \
  --parameters postgresAdminUsername="$POSTGRES_ADMIN_USERNAME" \
  --parameters postgresAdminPassword="$POSTGRES_ADMIN_PASSWORD" \
  --parameters mcpApiKey="$MCP_API_KEY" || true

# Phase 2: Build and push container images into ACR using ACR Tasks (no local Docker required).
echo "Phase 2: Building container images in ACR..."
az acr build -r "$ACR_NAME" -t cocktail-mcp-api:latest -f Dockerfile.api . --no-logs
az acr build -r "$ACR_NAME" -t cocktail-scraper:latest -f Dockerfile.scraper . --no-logs
az acr build -r "$ACR_NAME" -t cocktail-indexer:latest -f Dockerfile.indexer . --no-logs

# Phase 3: Re-run Bicep — idempotent, container apps will now succeed with images available.
echo "Phase 3: Re-deploying to provision container apps with images..."
az deployment group create \
  --resource-group "$RG_NAME" \
  --template-file infra/main.bicep \
  --parameters infra/parameters/dev.bicepparam \
  --parameters postgresAdminUsername="$POSTGRES_ADMIN_USERNAME" \
  --parameters postgresAdminPassword="$POSTGRES_ADMIN_PASSWORD" \
  --parameters mcpApiKey="$MCP_API_KEY"

# Phase 4: Run database migrations.
echo "Phase 4: Running database migrations..."
PG_SERVER=$(az postgres flexible-server list \
  --resource-group "$RG_NAME" \
  --query "[0].name" -o tsv)

if [[ -z "$PG_SERVER" ]]; then
  echo "⚠️  PostgreSQL server not found. Skipping migrations."
else
  export DATABASE_URL="postgresql://${POSTGRES_ADMIN_USERNAME}:${POSTGRES_ADMIN_PASSWORD}@${PG_SERVER}.postgres.database.azure.com/postgres"
  python -m scraper.cli migrate || echo "⚠️  Migration failed. Check database connectivity."
fi

echo "Deployment finished."
