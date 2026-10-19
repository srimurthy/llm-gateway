"""GET /v1/models: the aliases this tenant may use."""

from __future__ import annotations

from fastapi import APIRouter

from llm_gateway.api.dependencies import ContainerDep, TenantDep
from llm_gateway.api.schemas import ModelListOut, ModelOut

router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models", summary="List the models (aliases) available to the caller.")
async def list_models(tenant: TenantDep, container: ContainerDep) -> ModelListOut:
    policy = await container.policies.get(tenant)
    return ModelListOut(
        data=[
            ModelOut(id=alias, description=settings.description)
            for alias, settings in sorted(container.router.aliases.items())
            if policy.allows(alias)
        ]
    )
