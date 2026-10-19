"""Request context: request ID, access log and HTTP metrics.

Written as plain ASGI middleware rather than ``BaseHTTPMiddleware`` so streamed responses
pass through untouched.
"""

from __future__ import annotations

import time
import uuid
from typing import Final

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from llm_gateway.observability import metrics

log = structlog.get_logger(__name__)

REQUEST_ID_HEADER: Final = "x-request-id"
_QUIET_PATHS: Final = frozenset({"/healthz", "/readyz", "/metrics"})


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Envoy sets x-request-id on every request entering the mesh.
        request_id = Headers(scope=scope).get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status = 500
        started = time.perf_counter()

        async def send_with_context(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self._app(scope, receive, send_with_context)
        finally:
            duration = time.perf_counter() - started
            route = getattr(scope.get("route"), "path", "unmatched")
            metrics.HTTP_REQUEST_DURATION.labels(
                method=scope["method"], route=route, status=str(status)
            ).observe(duration)
            if scope["path"] not in _QUIET_PATHS:
                log.info(
                    "request_completed",
                    method=scope["method"],
                    route=route,
                    status=status,
                    duration_ms=round(duration * 1000, 1),
                )
