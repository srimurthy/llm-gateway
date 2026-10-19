# LLM Gateway

One OpenAI-compatible API for corporate teams, in front of **Amazon Bedrock**,
**Azure OpenAI** and a **self-hosted small language model** (vLLM). It runs active-active
in two AWS regions, enforces rate limits in four layers, and falls back between providers
so that one throttled or failing backend does not take the service down.

```
corporate clients ──1. resolve──► Route 53 public zone (api.llm.acme.com)
  (JWT from corp IdP)               latency alias per region, health-checked
        │
        └──2. HTTPS──► public NLB ──────────► internal ALB ─────────► Istio ingress gateway
                       public subnets         private subnets          │  JWT check, tenant → header
                       static EIPs            TLS (ACM), AWS WAF,      │  L1 per-pod limit
                       SG: corp egress IPs    re-encrypt to Istio      │  L2 per-tenant RPM
                                                                       ▼
                                                     llm-gateway pods (EKS, Python)
                                                     │  L3 tokens/minute per tenant × model
                                                     │  L4 provider fallback + circuit breakers
                      ┌──────────────────────────────┼──────────────────────────────┐
                      ▼                              ▼                              ▼
          Amazon Bedrock (PrivateLink)     vLLM on GPU nodes (in-mesh)    Azure OpenAI ×2 regions
                                                                          (Istio egress gw → NAT)
```

See [docs/architecture.md](docs/architecture.md) for the full design and
[docs/adr](docs/adr) for the decisions behind it.

## Repository layout

| Path | What it holds | Toolchain |
|---|---|---|
| [`app/`](app) | The gateway service (FastAPI) and async job worker | Python 3.13, uv, ruff, mypy `--strict`, pytest |
| [`infra/`](infra) | All AWS and Azure infrastructure | Terraform ≥ 1.10, tflint, Trivy |
| [`deploy/`](deploy) | Everything inside the clusters: Helm chart, Istio, ratelimit, Karpenter, vLLM, Argo CD | Helm, Kustomize, Argo CD |
| [`docs/`](docs) | Architecture and ADRs | |
| [`scripts/`](scripts) | Operational helpers (key sync, tenant policies) | bash, aws, az, jq |

Infrastructure is Terraform only, with no Crossplane. In-cluster resources are applied
by Argo CD from `deploy/`.

## Rate limiting

| Layer | Where | Keyed on | Limits | When exceeded |
|---|---|---|---|---|
| L1 | Envoy `local_ratelimit` on each ingress pod | pod | burst/flood | 429, no network hop |
| L2 | Envoy `ratelimit` filter → ratelimit service → Valkey | tenant | requests/minute | 429 |
| L3 | Gateway pods, Lua script in Valkey | tenant × model alias | tokens/minute | 429 + `Retry-After` |
| L4 | Router + Istio `DestinationRule` pools | provider | provider capacity | next provider → 429/503 |

L1 and L2 live in Istio. Tokens (L3) are enforced in the app: Envoy counts requests,
and a request's token cost is known only from its body and its response
([ADR 0002](docs/adr/0002-rate-limiting-split.md)).

## Quick start (local)

```sh
docker compose up --build                       # gateway + Valkey + mock providers
curl -s localhost:8080/v1/chat/completions \
  -H 'x-tenant-id: team-local' -H 'content-type: application/json' \
  -d '{"model":"fast","messages":[{"role":"user","content":"hello"}],"stream":true}'
```

Any OpenAI SDK works against it:

```python
from openai import OpenAI

client = OpenAI(base_url="https://api.llm.acme.com/v1", api_key=corp_jwt)
client.chat.completions.create(model="smart", messages=[{"role": "user", "content": "hi"}])
```

## Checks

`make check` runs what CI runs: app lint, types and tests; `terraform fmt` and
`validate` on every root; Helm lint and Kustomize builds. See `make help`.

## Deploying

1. **Infrastructure:** follow the apply order in [infra/README.md](infra/README.md).
2. **Secrets:** run `scripts/sync-azure-keys.sh`, and store the ingress certificate in
   `llmgw-prod/ingress-tls`.
3. **Cluster contents:** `kubectl apply -f deploy/argocd/<region>/` once per cluster. From
   then on, merging to `main` deploys. See [deploy/README.md](deploy/README.md).

## Status and known gaps

The code is complete enough to deploy, but it has not run against real AWS or Azure
accounts yet. Before production:

- **Placeholders:** fill in account IDs, CIDRs, the IdP issuer, the
  hostnames and the ratelimit image SHA. Search for `111122223333`, `acme`, `corp.example`
  and `REPLACE_WITH`.
- **Load test:** measure per-pod stream capacity before setting the HPA targets and the
  L1/L2 numbers.
- **Cross-region quota rebalancing:** each region currently enforces
  `regionQuotaShare` of a tenant's budget on its own
  ([ADR 0003](docs/adr/0003-regional-isolation-and-quotas.md)).
- **Autoscaling on open streams:** the HPA scales on CPU by default. Scaling on
  `llmgw_active_streams` needs prometheus-adapter (`api.autoscaling.activeStreams`).
- **API coverage:** text chat completions only. Tools/function calling, images and
  embeddings are rejected with a 400, not silently ignored.
