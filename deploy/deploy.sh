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

echo "== registry and image ($IMAGE)"
az acr show -n "$ACR" -g "$RG" >/dev/null 2>&1 || az acr create -n "$ACR" -g "$RG" -l "$LOCATION" --sku Basic -o none
# GitHub Actions (.github/workflows/image.yml) builds and pushes the image on every push to
# main. Fall back to building in Azure if that image isn't there (needs ACR Tasks).
if ! az acr repository show-tags -n "$ACR" --repository inside-the-game -o tsv 2>/dev/null | grep -qx "$TAG"; then
  az acr build -r "$ACR" -t "inside-the-game:$TAG" . -o none
fi

echo "== container apps environment"
az containerapp env show -n "$ENV_NAME" -g "$RG" >/dev/null 2>&1 || \
  az containerapp env create -n "$ENV_NAME" -g "$RG" -l "$LOCATION" -o none

echo "== Match Data MCP server (internal ingress)"
if az containerapp show -n "$MCP" -g "$RG" >/dev/null 2>&1; then
  az containerapp update -n "$MCP" -g "$RG" --image "$IMAGE" -o none
else
  az containerapp create -n "$MCP" -g "$RG" --environment "$ENV_NAME" --image "$IMAGE" \
    --registry-server "$ACR.azurecr.io" --registry-identity system \
    --command python --args -m matchmind.mcp_server --port 8001 \
    --target-port 8001 --ingress internal --min-replicas 0 --max-replicas 2 -o none
fi
MCP_FQDN=$(az containerapp show -n "$MCP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)

echo "== web app (public ingress)"
ENV_VARS=(FOUNDRY_PROJECT_ENDPOINT="$FOUNDRY_PROJECT_ENDPOINT" FOUNDRY_MODEL="$FOUNDRY_MODEL"
          MATCH_MCP_URL="https://$MCP_FQDN/mcp" MAX_LIVE_MATCHES=2
          AZURE_OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" AZURE_OPENAI_DEPLOYMENT="$AZURE_OPENAI_DEPLOYMENT"
          AZURE_OPENAI_API_KEY=secretref:aoai-key)
if az containerapp show -n "$WEB" -g "$RG" >/dev/null 2>&1; then
  az containerapp secret set -n "$WEB" -g "$RG" --secrets aoai-key="$AZURE_OPENAI_API_KEY" -o none
  az containerapp update -n "$WEB" -g "$RG" --image "$IMAGE" --set-env-vars "${ENV_VARS[@]}" -o none
else
  az containerapp create -n "$WEB" -g "$RG" --environment "$ENV_NAME" --image "$IMAGE" \
    --registry-server "$ACR.azurecr.io" --registry-identity system --system-assigned \
    --secrets aoai-key="$AZURE_OPENAI_API_KEY" --env-vars "${ENV_VARS[@]}" \
    --target-port 8000 --ingress external --min-replicas 0 --max-replicas 3 -o none
fi

echo "== let the web app use the Foundry model with its managed identity"
PRINCIPAL=$(az containerapp show -n "$WEB" -g "$RG" --query identity.principalId -o tsv)
SCOPE=$(az cognitiveservices account show -n "$FOUNDRY_ACCOUNT" -g "$RG" --query id -o tsv)
for ROLE in "Azure AI User" "Cognitive Services OpenAI User"; do
  az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
    --role "$ROLE" --scope "$SCOPE" -o none 2>/dev/null || true
done

echo "== done: https://$(az containerapp show -n "$WEB" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
