"""Prometheus metrics.

Tenant is deliberately not a label: per-tenant usage goes to the DynamoDB usage ledger,
which keeps metric cardinality bounded by providers and aliases.
"""

from __future__ import annotations

from typing import Final

from prometheus_client import Counter, Gauge, Histogram

_LATENCY_BUCKETS: Final = (0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300)

HTTP_REQUEST_DURATION: Final = Histogram(
    "llmgw_http_request_duration_seconds",
    "HTTP request duration, including the whole stream for streamed responses.",
    ["method", "route", "status"],
    buckets=_LATENCY_BUCKETS,
)
CHAT_REQUESTS: Final = Counter(
    "llmgw_chat_requests", "Chat requests by alias, mode and outcome.", ["alias", "mode", "outcome"]
)
PROVIDER_CALLS: Final = Counter(
    "llmgw_provider_calls",
    "Provider attempts by outcome (success, throttled, unavailable, rejected, circuit_open).",
    ["provider", "outcome"],
)
PROVIDER_LATENCY: Final = Histogram(
    "llmgw_provider_latency_seconds",
    "Provider call duration (full response, or full stream).",
    ["provider", "mode"],
    buckets=_LATENCY_BUCKETS,
)
TIME_TO_FIRST_TOKEN: Final = Histogram(
    "llmgw_time_to_first_token_seconds",
    "Time until a provider stream produced its first chunk.",
    ["provider"],
    buckets=_LATENCY_BUCKETS,
)
FALLBACKS: Final = Counter(
    "llmgw_fallbacks",
    "Requests moved to the next provider in the chain.",
    ["alias", "from_provider"],
)
CIRCUIT_OPEN: Final = Gauge(
    "llmgw_circuit_open", "1 while a provider's circuit breaker is open in this pod.", ["provider"]
)
TOKENS: Final = Counter(
    "llmgw_tokens", "Tokens consumed, by kind (prompt, completion).", ["alias", "provider", "kind"]
)
BUDGET_REJECTIONS: Final = Counter(
    "llmgw_budget_rejections", "Requests rejected by the tokens-per-minute budget.", ["alias"]
)
LIMITER_FALLBACKS: Final = Counter(
    "llmgw_limiter_fallbacks",
    "Budget operations served by the in-pod bucket because Valkey was unreachable.",
    ["operation"],
)
ACTIVE_STREAMS: Final = Gauge(
    "llmgw_active_streams", "Streams currently open in this pod. The HPA scales on this."
)
USAGE_FLUSH_FAILURES: Final = Counter(
    "llmgw_usage_flush_failures", "Usage ledger rows that could not be written."
)
BACKGROUND_TASKS_DROPPED: Final = Counter(
    "llmgw_background_tasks_dropped", "Background tasks dropped at the pending limit.", ["task"]
)
JOBS_PROCESSED: Final = Counter(
    "llmgw_jobs_processed", "Async jobs handled by the worker, by outcome.", ["outcome"]
)
