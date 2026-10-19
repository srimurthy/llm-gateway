"""Error hierarchy.

``GatewayError`` subclasses are client-visible: each maps to one HTTP status and an
OpenAI-style error body. ``ProviderError`` subclasses are internal: the router decides
whether to fall back, and converts what remains into a ``GatewayError``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar


class GatewayError(Exception):
    status_code: ClassVar[int] = 500
    error_type: ClassVar[str] = "server_error"
    code: ClassVar[str] = "internal_error"

    def __init__(self, message: str, *, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.headers: dict[str, str] = dict(headers or {})


class AuthenticationError(GatewayError):
    status_code = 401
    error_type = "authentication_error"
    code = "missing_tenant"


class InvalidRequestError(GatewayError):
    status_code = 400
    error_type = "invalid_request_error"
    code = "invalid_request"


class UpstreamRejectedError(InvalidRequestError):
    """The provider refused the request itself (validation, content filter)."""

    code = "provider_rejected_request"


class RequestTooLargeError(InvalidRequestError):
    """The request needs more tokens than the tenant's whole per-minute budget."""

    code = "token_budget_too_small"


class AliasNotFoundError(GatewayError):
    status_code = 404
    error_type = "invalid_request_error"
    code = "model_not_found"

    def __init__(self, alias: str) -> None:
        super().__init__(
            f"Model '{alias}' does not exist. GET /v1/models lists the models you can use."
        )


class AliasNotAllowedError(GatewayError):
    status_code = 403
    error_type = "permission_error"
    code = "model_not_allowed"

    def __init__(self, alias: str) -> None:
        super().__init__(f"Your tenant is not allowed to use model '{alias}'.")


class RateLimitExceededError(GatewayError):
    status_code = 429
    error_type = "rate_limit_error"
    code = "tokens_per_minute_exceeded"

    def __init__(self, *, retry_after_s: int, limit: int, remaining: int) -> None:
        super().__init__(
            f"Token budget exhausted ({limit} tokens per minute). Retry after {retry_after_s}s.",
            headers={
                "retry-after": str(retry_after_s),
                "x-ratelimit-limit-tokens": str(limit),
                "x-ratelimit-remaining-tokens": str(max(remaining, 0)),
            },
        )
        self.retry_after_s = retry_after_s


class ProvidersThrottledError(GatewayError):
    status_code = 429
    error_type = "rate_limit_error"
    code = "providers_throttled"

    def __init__(self, alias: str, *, retry_after_s: int) -> None:
        super().__init__(
            f"Every provider for '{alias}' is at capacity. Retry after {retry_after_s}s.",
            headers={"retry-after": str(retry_after_s)},
        )
        self.retry_after_s = retry_after_s


class ProvidersUnavailableError(GatewayError):
    status_code = 503
    error_type = "server_error"
    code = "providers_unavailable"

    def __init__(self, alias: str, *, retry_after_s: int) -> None:
        super().__init__(
            f"No provider for '{alias}' is available right now. Retry after {retry_after_s}s.",
            headers={"retry-after": str(retry_after_s)},
        )
        self.retry_after_s = retry_after_s


class JobNotFoundError(GatewayError):
    status_code = 404
    error_type = "invalid_request_error"
    code = "job_not_found"

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job '{job_id}' does not exist.")


class FeatureDisabledError(GatewayError):
    status_code = 404
    error_type = "invalid_request_error"
    code = "feature_disabled"


class BackendUnavailableError(GatewayError):
    """A gateway dependency (job store, queue) failed."""

    status_code = 503
    error_type = "server_error"
    code = "backend_unavailable"


class ProviderError(Exception):
    """A model backend failed. ``retryable`` says whether another provider may succeed."""

    retryable: ClassVar[bool] = True

    def __init__(self, provider: str, detail: str) -> None:
        super().__init__(f"{provider}: {detail}")
        self.provider = provider
        self.detail = detail


class ProviderThrottledError(ProviderError):
    """The provider is over quota (HTTP 429 or equivalent)."""


class ProviderUnavailableError(ProviderError):
    """5xx, timeout, connection failure, or a provider-side misconfiguration."""


class ProviderRequestError(ProviderError):
    """The provider rejected the request content; another provider would reject it too."""

    retryable = False
