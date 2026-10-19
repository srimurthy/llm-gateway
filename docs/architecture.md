# Architecture

## Goals

| Goal | How |
|---|---|
| Resilient | Two active AWS regions; three AZs each; provider fallback chains; circuit breakers |
| Fault-tolerant | Every shared dependency on the request path has a degraded mode (below) |
| Scalable | Stateless pods behind HPA; Karpenter for nodes; DynamoDB on-demand; Valkey cluster mode |
| High volume | Async I/O end to end; streaming; usage aggregated before writes; async job API for batch |
| Rate-limited | Four layers, from per-pod bursts to per-tenant tokens to provider capacity |
| Restricted exposure | Only the NLB is public, and it admits only corporate egress IPs; WAF; JWT at Istio; private EKS API; `REGISTRY_ONLY` mesh egress |

## Request path

```mermaid
sequenceDiagram
    autonumber
    participant C as Client (corp network)
    participant R as Route 53 public zone
    participant E as Public NLB → internal ALB
    participant I as Istio ingress gateway
    participant L as ratelimit service
    participant G as Gateway pod
    participant V as Valkey
    participant P as Provider (Bedrock / vLLM / Azure)
    C->>R: resolve api.llm.acme.com
    R-->>C: nearest healthy region's NLB (static IPs)
    C->>E: HTTPS + JWT from a corporate egress IP
    E->>E: NLB SG allowlist; ALB terminates TLS, runs WAF
    E->>I: re-encrypted HTTPS
    I->>I: verify JWT, tenant claim → x-tenant-id, L1 local limit
    I->>L: L2: tenant over its requests/minute?
    L->>V: increment counter
    I->>G: mTLS, ingress identity only
    G->>V: L3: reserve prompt + max_tokens (Lua)
    G->>P: first provider with a closed circuit
    P-->>G: stream
    G-->>C: SSE chunks
    G->>V: settle actual usage (background)
```

## Edge

| Hop | Subnets | Does |
|---|---|---|
| Public NLB | public, one Elastic IP per AZ | TCP passthrough. Its security group admits only `client_cidrs` (corporate egress ranges). Static IPs let corporate firewalls allowlist the destination. |
| Internal ALB | private | Registered as the NLB's target. Terminates TLS with the ACM certificate, applies AWS WAF, drops invalid headers, re-encrypts to Istio. |
| Istio ingress gateway | private (pods) | Verifies the JWT, writes the tenant header, enforces L1 and L2. |

WAF runs the AWS IP-reputation, known-bad-inputs and common rule sets. The common set's
body rules (size, XSS, LFI/RFI, SSRF) only count: prompts legitimately contain code and
markup, and are often larger than 8 KB.

## Components

**Gateway service** (`app/`): a FastAPI app that:
- validates OpenAI-format requests;
- authorizes the model alias for the tenant;
- reserves a token budget;
- routes through the alias's provider chain;
- streams the response;
- settles the budget and records usage.

The same image runs the async job worker.

**Providers.** Bedrock uses the Converse API through a PrivateLink endpoint. Azure OpenAI
goes through the Istio egress gateway and the NAT gateways, and Azure allows only those
NAT IPs. vLLM serves the self-hosted model in-mesh on Karpenter GPU nodes.

**State.**
- **Valkey** (per region): rate-limit counters only. Losing it resets counters.
- **DynamoDB global tables:** tenant policies, the usage ledger and async jobs.
- **SQS** (per region): async jobs.

## Fallback rules

- A **throttling or 5xx** failure moves the request to the next provider in the alias's
  chain.
- A **rejected request** (validation, content filter) fails immediately: another
  provider would reject it too.
- A **stream** can fall back only before its first token. The router waits for that
  token before it commits the response, so callers get a clean 429 or 503 instead of a
  200 that breaks halfway.
- The `private` alias has no fallback outside the cluster, by design.

## Degraded modes

| Failure | Detected by | Behavior |
|---|---|---|
| Region | CloudWatch alarm on healthy ALB targets (Istio pods) → Route 53 health check | DNS answers with the other region within about a minute. Each region is sized for full load. |
| AZ | NLB and pod health | Topology spread keeps replicas in the remaining AZs |
| ratelimit service | gRPC errors at Envoy | L2 fails open; L1 and L3 still apply |
| Valkey | Connection errors, 100 ms timeout | L2 fails open; L3 uses an in-pod bucket at 10% of the budget |
| DynamoDB (policies) | API errors | Last known policy per tenant, else the default |
| DynamoDB (usage) | API errors | Ledger rows dropped and counted (`llmgw_usage_flush_failures`) |
| Bedrock | 429/5xx, circuit breaker | Next provider in the chain |
| Azure region | Same | Second Azure region, then Bedrock |
| vLLM saturated | Envoy pool overflow (fast 503) | Bedrock for `fast`; 503 for `private` |
| Client disconnect | Cancelled stream | Budget settled from output so far |

Readiness probes never check shared dependencies. Otherwise one Valkey failover would
pull every pod out of service at the same moment.

## Observability

- **Metrics:** Prometheus metrics (`llmgw_*`) are labelled by alias and provider, never by
  tenant, so cardinality stays bounded. Per-tenant usage lives in the DynamoDB ledger.
- **Logs:** JSON logs carry the Envoy `x-request-id`. Prompts and completions are never
  logged.
- **Traces:** OpenTelemetry tracing is optional, enabled with `otel.enabled`.
- **Alarms to wire up:** `llmgw_circuit_open`, `llmgw_limiter_fallbacks`, provider
  error-rate by outcome, and the DLQ alarm.
