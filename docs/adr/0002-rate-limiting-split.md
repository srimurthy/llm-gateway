# 0002. Request limits in Istio, token budgets in the gateway

**Status:** accepted

## Context

The requirement is to enforce rate limits with Istio. LLM cost and provider quotas are
measured in tokens, not requests. A request's token cost depends on its body (the prompt
and `max_tokens`) and on its response (actual usage). Envoy's global rate limit filter
counts requests and cannot see either.

## Decision

Split by what each layer can see:

- **L1** (Envoy `local_ratelimit`, per ingress pod): absorbs bursts and floods with no
  network hop.
- **L2** (Envoy `ratelimit` filter and the ratelimit service on Valkey): requests per
  minute per tenant. The tenant comes from the verified JWT claim. The model alias is in
  the JSON body, which Envoy does not parse, so L2 keys on tenant only.
- **L3** (gateway, in Valkey): tokens per minute per tenant and model alias. Each request
  reserves `prompt estimate + max_tokens` up front, then settles to actual usage
  afterwards.
- **L4** (gateway router and Istio connection pools): provider capacity, with fallback.

## Alternatives

- **Envoy AI Gateway:** reads token usage from responses. It is promising, but it adds a
  second control plane and is younger than the rest of the stack. Revisit when it is GA
  and the team wants token limits in the proxy.
- **Request limits only:** this would let one tenant's long prompts consume the shared
  provider quota.

## Consequences

- Two stores of truth for limits: request rules live in Git
  (`deploy/ratelimit/base/config.yaml`), and token budgets live in DynamoDB
  (`scripts/put-tenant-policy.sh`).
- Reserving the maximum up front keeps the budget correct under concurrency. A tenant
  that sets a huge `max_tokens` "spends" its budget early. The refund comes as soon as
  each request finishes.
