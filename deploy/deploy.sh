#!/usr/bin/env bash
# Deploys Inside the Game to Azure Container Apps.
#
#   web app (public)  --MCP over HTTP-->  Match Data MCP server (internal only)
#        |
#        +--> Microsoft Foundry project model (managed identity, no key in the container)
#
# One image runs both apps. GitHub Actions builds it and pushes it to Azure Container
# Registry, so Docker is not needed locally. Reads the Azure OpenAI and Foundry settings from .env.
#
# Usage: deploy/deploy.sh            (first run creates everything; later runs update)

set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

RG=${RG:-match-mind}
LOCATION=${LOCATION:-eastus2}
ENV_NAME=${ENV_NAME:-inside-the-game-env}
ACR=${ACR:-insidethegame$(az account show --query id -o tsv | tr -d '-' | cut -c1-8)}
WEB=${WEB:-inside-the-game}
MCP=${MCP:-match-data-mcp}
FOUNDRY_ACCOUNT=${FOUNDRY_ACCOUNT:-match-mind-resource}
TAG=${TAG:-$(git rev-parse --short HEAD)}
IMAGE="$ACR.azurecr.io/inside-the-game:$TAG"

# The containerapp CLI can hang while waiting on long operations, so each step is
# started with --no-wait and this polls Azure until it is done.
wait_for() {  # wait_for <show command...>
  for _ in $(seq 1 90); do
    state=$("$@" --query properties.provisioningState -o tsv 2>/dev/null || true)
    case "$state" in
      Succeeded) return 0 ;;
      Failed|Canceled) echo "failed: $state"; return 1 ;;
    esac
    sleep 10
  done
  echo "timed out"; return 1
}

echo "== registry and image ($IMAGE)"
az acr show -n "$ACR" -g "$RG" >/dev/null 2>&1 || az acr create -n "$ACR" -g "$RG" -l "$LOCATION" --sku Basic -o none
# GitHub Actions (.github/workflows/image.yml) builds and pushes the image on every push to
# main. Fall back to building in Azure if that image isn't there (needs ACR Tasks).
if ! az acr repository show-tags -n "$ACR" --repository inside-the-game -o tsv 2>/dev/null | grep -qx "$TAG"; then
  az acr build -r "$ACR" -t "inside-the-game:$TAG" . -o none
fi

echo "== container apps environment"
az containerapp env show -n "$ENV_NAME" -g "$RG" >/dev/null 2>&1 || \
  az containerapp env create -n "$ENV_NAME" -g "$RG" -l "$LOCATION" --no-wait -o none
wait_for az containerapp env show -n "$ENV_NAME" -g "$RG"

# Each app is created first (with Azure's placeholder image), then given pull access to the
# registry with its own managed identity, then switched to our image. Doing these steps
# ourselves avoids the containerapp CLI's combined create, which can hang.
ACR_ID=$(az acr show -n "$ACR" -g "$RG" --query id -o tsv)

grant() {  # grant <app> <role> <scope>
  local principal
  principal=$(az containerapp show -n "$1" -g "$RG" --query identity.principalId -o tsv)
  az role assignment create --assignee-object-id "$principal" --assignee-principal-type ServicePrincipal \
    --role "$2" --scope "$3" -o none 2>/dev/null || true
}

use_image() {  # use_image <app>: pull from our registry with the app's identity, run $IMAGE
  grant "$1" AcrPull "$ACR_ID"
  sleep 20   # let the role assignment reach the registry
  az containerapp registry set -n "$1" -g "$RG" --server "$ACR.azurecr.io" --identity system -o none
  az containerapp update -n "$1" -g "$RG" --image "$IMAGE" --no-wait -o none
  wait_for az containerapp show -n "$1" -g "$RG"
}

echo "== Match Data MCP server (internal ingress)"
if ! az containerapp show -n "$MCP" -g "$RG" >/dev/null 2>&1; then
  az containerapp create -n "$MCP" -g "$RG" --environment "$ENV_NAME" --system-assigned \
    --env-vars APP_ROLE=mcp \
    --target-port 8001 --ingress internal --min-replicas 0 --max-replicas 2 --no-wait -o none
  wait_for az containerapp show -n "$MCP" -g "$RG"
fi
use_image "$MCP"
MCP_FQDN=$(az containerapp show -n "$MCP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)

echo "== web app (public ingress)"
ENV_VARS=(FOUNDRY_PROJECT_ENDPOINT="$FOUNDRY_PROJECT_ENDPOINT" FOUNDRY_MODEL="$FOUNDRY_MODEL"
          MATCH_MCP_URL="https://$MCP_FQDN/mcp" MAX_LIVE_MATCHES=2
          AZURE_OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" AZURE_OPENAI_DEPLOYMENT="$AZURE_OPENAI_DEPLOYMENT"
          AZURE_OPENAI_API_KEY=secretref:aoai-key)
if az containerapp show -n "$WEB" -g "$RG" >/dev/null 2>&1; then
  # Secrets are set when the app is created; rotate with ROTATE_SECRETS=1 (this call can be slow).
  if [ "${ROTATE_SECRETS:-0}" = 1 ]; then
    az containerapp secret set -n "$WEB" -g "$RG" --secrets aoai-key="$AZURE_OPENAI_API_KEY" -o none
  fi
  az containerapp update -n "$WEB" -g "$RG" --set-env-vars "${ENV_VARS[@]}" --no-wait -o none
else
  az containerapp create -n "$WEB" -g "$RG" --environment "$ENV_NAME" --system-assigned \
    --secrets aoai-key="$AZURE_OPENAI_API_KEY" --env-vars "${ENV_VARS[@]}" \
    --target-port 8000 --ingress external --min-replicas 0 --max-replicas 3 --no-wait -o none
fi
wait_for az containerapp show -n "$WEB" -g "$RG"

echo "== let the web app use the Foundry model with its managed identity"
FOUNDRY_ID=$(az cognitiveservices account show -n "$FOUNDRY_ACCOUNT" -g "$RG" --query id -o tsv)
for ROLE in "Foundry User" "Cognitive Services OpenAI User"; do
  grant "$WEB" "$ROLE" "$FOUNDRY_ID"
done
use_image "$WEB"

echo "== done: https://$(az containerapp show -n "$WEB" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
