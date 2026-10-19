"""FastAPI dependencies.

The tenant comes from a header the Istio ingress gateway writes from the verified JWT
claim. The gateway pods accept traffic only from the ingress gateway's identity (mTLS
plus an AuthorizationPolicy), which is what makes the header trustworthy.
"""

from __future__ import annotations

import re
from typing import Annotated, Final, cast

import structlog
from fastapi import Depends, Request

from llm_gateway.container import Container
from llm_gateway.core.errors import AuthenticationError, FeatureDisabledError
from llm_gateway.jobs.service import JobService
from llm_gateway.services.chat import ChatService

TENANT_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def get_container(request: Request) -> Container:
    return cast(Container, request.app.state.container)


ContainerDep = Annotated[Container, Depends(get_container)]


def get_tenant(request: Request, container: ContainerDep) -> str:
    tenant = request.headers.get(container.settings.tenant_header, "")
    if not TENANT_ID_PATTERN.fullmatch(tenant):
        raise AuthenticationError(
            "No valid tenant identity on the request. Call the gateway through its ingress."
        )
    structlog.contextvars.bind_contextvars(tenant=tenant)
    return tenant


def get_chat_service(container: ContainerDep) -> ChatService:
    return container.chat


def get_job_service(container: ContainerDep) -> JobService:
    if container.jobs is None:
        raise FeatureDisabledError("Async jobs are not enabled on this deployment.")
    return container.jobs


TenantDep = Annotated[str, Depends(get_tenant)]
ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
