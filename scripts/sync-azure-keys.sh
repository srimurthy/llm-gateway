#!/usr/bin/env bash
# Copy Azure OpenAI keys into Secrets Manager, so they never pass through Terraform state.
#
# Rotation (two-key pattern, no downtime):
#   1. az cognitiveservices account keys regenerate --key-name Key2 ...
#   2. KEY_NAME=key2 ./scripts/sync-azure-keys.sh
#   3. kubectl -n llm-gateway rollout restart deploy   (both regions)
#   4. Regenerate Key1 once every pod runs with Key2. Next rotation, swap the names.
#
# Usage: KEY_NAME=key1 ./scripts/sync-azure-keys.sh
# Needs: az (logged in to the subscription) and aws (credentials for the primary region).
set -euo pipefail

KEY_NAME="${KEY_NAME:-key1}"
RESOURCE_GROUP="${RESOURCE_GROUP:-acme-llmgw-rg}"
SECRET_PREFIX="${SECRET_PREFIX:-llmgw-prod/azure-openai}"
AWS_REGION="${AWS_REGION:-us-east-1}"

accounts_json="$(terraform -chdir="$(dirname "$0")/../infra/live/prod/azure" output -json account_names)"

for location in $(jq -r 'keys[]' <<<"${accounts_json}"); do
  account="$(jq -r --arg l "${location}" '.[$l]' <<<"${accounts_json}")"
  key="$(az cognitiveservices account keys list \
    --name "${account}" --resource-group "${RESOURCE_GROUP}" \
    --query "${KEY_NAME}" --output tsv)"

  # Secrets Manager replicates the new version to the secondary region.
  aws secretsmanager put-secret-value \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_PREFIX}/${location}" \
    --secret-string "${key}" >/dev/null
  echo "updated ${SECRET_PREFIX}/${location} from ${account} (${KEY_NAME})"
done
