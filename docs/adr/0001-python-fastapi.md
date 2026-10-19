# 0001. Python and FastAPI for the gateway service

**Status:** accepted

## Context

The service spends almost all of its time waiting on model providers while holding
long-lived streaming connections. Go was considered for its low per-connection cost.
The team chose Python for familiarity and for its ecosystem: the official `openai` SDK,
`aiobotocore`, and shared skills with the ML side.

## Decision

Python 3.13 with FastAPI and uvicorn, using asyncio throughout. Everything on the request
path is async: aiobotocore for AWS, the async `openai` client, and `redis.asyncio` for
Valkey. Nothing blocks the event loop.

## Consequences

- **Concurrency:** one process per container, no uvicorn workers. Kubernetes scales pods,
  and each pod's memory and stream count stay predictable.
- **Autoscaling:** CPU is a poor scaling signal for I/O-bound pods, so the HPA can scale
  on `llmgw_active_streams`.
- **Per-stream cost:** each stream costs more memory than it would in Go. Plan capacity
  from a load test, not from estimates.
- **Quality gates:** strict typing (`mypy --strict`), ruff with a broad rule set, and an
  85% coverage gate make up for Python's weaker compile-time guarantees.
