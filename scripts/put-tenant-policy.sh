#!/usr/bin/env bash
# Create or update a tenant's token budget and allowed models.
# Pods pick the change up within their 60-second policy cache.
#
# Usage: ./scripts/put-tenant-policy.sh <tenant> <tokens-per-minute> [alias ...]
#   ./scripts/put-tenant-policy.sh team-search 500000 fast smart
#   ./scripts/put-tenant-policy.sh team-batch 50000          # all aliases
set -euo pipefail

if [[ $# -lt 2 ]]; then
  sed -n '2,8p' "$0"
  exit 64
fi

tenant="$1"
tokens_per_minute="$2"
shift 2

TABLE="${TABLE:-llmgw-prod-tenants}"
AWS_REGION="${AWS_REGION:-us-east-1}"

if [[ ! "${tenant}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
  echo "invalid tenant id: ${tenant}" >&2
  exit 65
fi

item=$(jq -n --arg t "${tenant}" --arg n "${tokens_per_minute}" \
  '{tenant_id: {S: $t}, tokens_per_minute: {N: $n}}')
if [[ $# -gt 0 ]]; then
  item=$(jq --args '. + {allowed_aliases: {SS: $ARGS.positional}}' <<<"${item}" "$@")
fi

aws dynamodb put-item --region "${AWS_REGION}" --table-name "${TABLE}" --item "${item}"
echo "tenant ${tenant}: ${tokens_per_minute} tokens/min, aliases: ${*:-all}"
