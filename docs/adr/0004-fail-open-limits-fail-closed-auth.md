# 0004. Rate limits fail open; authentication fails closed

**Status:** accepted

## Context

Every limit layer depends on something that can fail: the ratelimit service, Valkey, or
DynamoDB.

## Decision

- **Rate limits degrade instead of blocking:**
  - L2 sets `failure_mode_deny: false`.
  - If Valkey is unreachable for 100 ms, L3 falls back to an in-pod bucket sized at
    `localFallbackFraction` of the budget.
  - Tenant policy lookups serve the last known value.
- **Authentication never degrades.** No valid JWT with a `tenant` claim means no request.
  Gateway pods accept traffic only from the ingress gateway's mTLS identity.

## Consequences

- **Limits during an outage:** a Valkey outage loosens limits to roughly
  `pods × fraction × budget`. L1 still caps each ingress pod. An alarm on
  `llmgw_limiter_fallbacks` tells operators when this happens.
- **Readiness:** probes ignore these dependencies, so a degraded dependency never removes
  every pod at once.
