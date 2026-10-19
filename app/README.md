# llm-gateway (application)

Python service behind the Istio ingress gateway. It exposes an OpenAI-compatible API,
enforces per-tenant token budgets, and routes each model alias through a fallback chain
of providers (Amazon Bedrock, Azure OpenAI, self-hosted vLLM).

See the [repository README](../README.md) for the architecture and the
[ADRs](../docs/adr) for the reasoning behind the main decisions.

## Layout

```
src/llm_gateway/
  api/             HTTP layer: schemas, routes, error mapping, SSE formatting
  config/          Settings (env) and routing config (YAML)
  core/            Provider-neutral models, errors, token estimates
  providers/       Bedrock, OpenAI-compatible (Azure, vLLM) and mock adapters
  routing/         Alias -> provider chain, fallback rules, circuit breakers
  ratelimit/       Tokens-per-minute budgets in Valkey, with an in-pod fallback
  services/        Use cases: run a chat request
  jobs/            Async jobs: submit, store, worker
  tenants/         Tenant policies (DynamoDB, cached)
  usage/           Usage ledger, aggregated before writing to DynamoDB
  infrastructure/  AWS, Valkey, secrets, supervised background tasks
  observability/   Logging, metrics, tracing, request middleware
  container.py     Composition root
  main.py          ASGI app factory
  worker.py        Job worker entry point
```

Dependencies point inward: `api` -> `services` -> `routing`/`ratelimit` -> `core`.
Providers depend only on `core`. Only `container.py` knows every concrete class.

## Develop

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                       # create .venv with runtime + dev dependencies
uv run pytest                 # tests with coverage gate (see pyproject.toml)
uv run ruff check . && uv run ruff format --check .
uv run mypy                   # strict
```

Run locally against Valkey and mock providers:

```sh
docker compose up --build     # from the repository root
curl -s localhost:8080/v1/chat/completions \
  -H 'x-tenant-id: team-local' -H 'content-type: application/json' \
  -d '{"model":"fast","messages":[{"role":"user","content":"hello"}]}'
```

The `x-tenant-id` header is normally written by the Istio ingress gateway from the
caller's JWT; locally you set it yourself.

## Configuration

Environment variables use the `LLMGW_` prefix; see `config/settings.py` for the full
list. Routing (providers, aliases, default tenant policy) is a YAML file; see
`config/routing.example.yaml`.
