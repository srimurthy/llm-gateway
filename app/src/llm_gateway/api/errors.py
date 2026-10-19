"""Map exceptions to OpenAI-style error responses."""

from __future__ import annotations

from typing import cast

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from llm_gateway.api.openai_format import error_body
from llm_gateway.core.errors import GatewayError

log = structlog.get_logger(__name__)


async def _gateway_error(_: Request, exc: Exception) -> JSONResponse:
    error = cast(GatewayError, exc)
    if error.status_code >= 500:  # noqa: PLR2004
        log.warning("request_failed", code=error.code, error=error.message)
    return JSONResponse(
        error_body(error.message, error_type=error.error_type, code=error.code),
        status_code=error.status_code,
        headers=error.headers,
    )


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    # OpenAI answers malformed requests with 400, not FastAPI's default 422.
    errors = cast(RequestValidationError, exc).errors()
    first = errors[0] if errors else {}
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    detail = str(first.get("msg", "Invalid request."))
    message = f"{location}: {detail}" if location else detail
    return JSONResponse(
        error_body(message, error_type="invalid_request_error", code="invalid_request"),
        status_code=400,
    )


async def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_error", exc_info=exc)
    return JSONResponse(
        error_body("Internal error.", error_type="server_error", code="internal_error"),
        status_code=500,
    )


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(GatewayError, _gateway_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
