#!/usr/bin/env bash
set -euo pipefail

RESOURCE_GROUP="rg-cocktailagent-dev-wus-01"
ACR_NAME="acrcocktailagentdevwus01"
CONTAINER_APP="ca-cocktailagent-mcp-dev-wus-01"
CONTAINER_JOB="caj-cocktail-scraper-dev-wus-01"
INDEXER_JOB="caj-cocktail-indexer-dev-wus-01"
TARGET="api"
IMAGE_REPO=""
DOCKERFILE=""
BUILD_CONTEXT="."
SUBSCRIPTION=""
DRY_RUN=false
IMAGE_REPO_SET=false
DOCKERFILE_SET=false

default_tag() {
  echo "$(date +%Y%m%d%H%M%S)"
}

TAG="$(default_tag)"

usage() {
  cat <<'EOF'
Build and deploy a new Azure Container Apps image revision.

Usage:
  scripts/deploy_containerapp_revision.sh [options]

Options:
  --resource-group <name>    Azure resource group.
  --acr-name <name>          Azure Container Registry name (no .azurecr.io).
  --target <api|scraper|indexer>
                              Deploy API container app or a container app job.
  --container-app <name>     Azure Container App name.
  --container-job <name>     Azure Container Apps Job name.
  --indexer-job <name>       Azure Container Apps indexer job name.
  --image-repo <name>        Image repository in ACR.
  --tag <tag>                Image tag to build and deploy. Defaults to current date/time.
  --dockerfile <path>        Dockerfile path.
  --context <path>           Docker build context.
  --subscription <id|name>   Azure subscription to target.
  --dry-run                  Print commands without executing.
  -h, --help                 Show this help message.

Examples:
  scripts/deploy_containerapp_revision.sh
  scripts/deploy_containerapp_revision.sh --target scraper
  scripts/deploy_containerapp_revision.sh --target indexer
  scripts/deploy_containerapp_revision.sh --tag v1.4.0
  scripts/deploy_containerapp_revision.sh --target api --container-app my-app --image-repo my-api
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resource-group)
      RESOURCE_GROUP="$2"
      shift 2
      ;;
    --acr-name)
      ACR_NAME="$2"
      shift 2
      ;;
    --target)
      TARGET="$2"
      shift 2
      ;;
    --container-app)
      CONTAINER_APP="$2"
      shift 2
      ;;
    --container-job)
      CONTAINER_JOB="$2"
      shift 2
      ;;
    --indexer-job)
      INDEXER_JOB="$2"
      shift 2
      ;;
    --image-repo)
      IMAGE_REPO="$2"
      IMAGE_REPO_SET=true
      shift 2
      ;;
    --tag)
      TAG="$2"
      shift 2
      ;;
    --dockerfile)
      DOCKERFILE="$2"
      DOCKERFILE_SET=true
      shift 2
      ;;
    --context)
      BUILD_CONTEXT="$2"
      shift 2
      ;;
    --subscription)
      SUBSCRIPTION="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo
      usage
      exit 1
      ;;
  esac
done

case "$TARGET" in
  api)
    if [[ "$IMAGE_REPO_SET" == false ]]; then
      IMAGE_REPO="cocktail-mcp-api"
    fi
    if [[ "$DOCKERFILE_SET" == false ]]; then
      DOCKERFILE="Dockerfile.api"
    fi
    ;;
  scraper)
    if [[ "$IMAGE_REPO_SET" == false ]]; then
      IMAGE_REPO="cocktail-scraper"
    fi
    if [[ "$DOCKERFILE_SET" == false ]]; then
      DOCKERFILE="Dockerfile.scraper"
    fi
    ;;
  indexer)
    if [[ "$IMAGE_REPO_SET" == false ]]; then
      IMAGE_REPO="cocktail-indexer"
    fi
    if [[ "$DOCKERFILE_SET" == false ]]; then
      DOCKERFILE="Dockerfile.indexer"
    fi
    ;;
  *)
    echo "Invalid --target value: ${TARGET}. Use 'api', 'scraper', or 'indexer'."
    exit 1
    ;;
esac

IMAGE="${ACR_NAME}.azurecr.io/${IMAGE_REPO}:${TAG}"

run_cmd() {
  if [[ "$DRY_RUN" == true ]]; then
    echo "+ $*"
  else
    "$@"
  fi
}

echo "Starting build + deploy"
echo "Target         : ${TARGET}"
echo "Resource group : ${RESOURCE_GROUP}"
if [[ "$TARGET" == "api" ]]; then
  echo "Container App  : ${CONTAINER_APP}"
elif [[ "$TARGET" == "scraper" ]]; then
  echo "Container Job  : ${CONTAINER_JOB}"
else
  echo "Indexer Job    : ${INDEXER_JOB}"
fi
echo "ACR            : ${ACR_NAME}"
echo "Image          : ${IMAGE}"
echo "Dockerfile     : ${DOCKERFILE}"
echo "Build context  : ${BUILD_CONTEXT}"

if [[ -n "$SUBSCRIPTION" ]]; then
  echo "Subscription   : ${SUBSCRIPTION}"
  run_cmd az account set --subscription "$SUBSCRIPTION"
fi

run_cmd az account show --query "{name:name,id:id}" -o table

if [[ "$DRY_RUN" == false ]]; then
  if ! command -v az >/dev/null 2>&1; then
    echo "Azure CLI (az) is required"
    exit 1
  fi

  az acr show --name "$ACR_NAME" >/dev/null
  if [[ "$TARGET" == "api" ]]; then
    az containerapp show --resource-group "$RESOURCE_GROUP" --name "$CONTAINER_APP" >/dev/null
  elif [[ "$TARGET" == "scraper" ]]; then
    az containerapp job show --resource-group "$RESOURCE_GROUP" --name "$CONTAINER_JOB" >/dev/null
  else
    az containerapp job show --resource-group "$RESOURCE_GROUP" --name "$INDEXER_JOB" >/dev/null
  fi
fi

echo "Building image in ACR..."
run_cmd az acr build \
  --registry "$ACR_NAME" \
  --image "${IMAGE_REPO}:${TAG}" \
  --file "$DOCKERFILE" \
  "$BUILD_CONTEXT"

if [[ "$TARGET" == "api" ]]; then
  echo "Updating Container App to new image..."
  run_cmd az containerapp update \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CONTAINER_APP" \
    --image "$IMAGE" \
    --query "{name:name,provisioningState:properties.provisioningState,latestRevision:properties.latestRevisionName}" \
    --output json

  echo "Fetching endpoint details..."
  if [[ "$DRY_RUN" == false ]]; then
    FQDN="$(az containerapp show --resource-group "$RESOURCE_GROUP" --name "$CONTAINER_APP" --query properties.configuration.ingress.fqdn -o tsv)"
    if [[ -n "$FQDN" ]]; then
      echo "App URL: https://${FQDN}"
    fi
  fi
else
  echo "Updating Container Apps Job to new image..."
  JOB_NAME="$CONTAINER_JOB"
  if [[ "$TARGET" == "indexer" ]]; then
    JOB_NAME="$INDEXER_JOB"
  fi

  run_cmd az containerapp job update \
    --resource-group "$RESOURCE_GROUP" \
    --name "$JOB_NAME" \
    --image "$IMAGE" \
    --query "{name:name,provisioningState:properties.provisioningState}" \
    --output json
fi

echo "Done. Deployed image: ${IMAGE}"