"""Liveness and readiness.

Readiness deliberately does not check Valkey or the providers. Both have fallbacks, and
failing readiness on a shared dependency would pull every pod out of service at once,
turning a degraded dependency into a full outage.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"], include_in_schema=False)


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", response_model=None)
async def readyz(request: Request) -> JSONResponse | dict[str, str]:
    if getattr(request.app.state, "container", None) is None:
        return JSONResponse({"status": "starting"}, status_code=503)
    return {"status": "ready"}
