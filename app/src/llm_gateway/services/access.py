"""Alias authorization, shared by synchronous requests and async job submission."""

from __future__ import annotations

from llm_gateway.config.routing import AliasSettings, TenantPolicy
from llm_gateway.core.errors import AliasNotAllowedError
from llm_gateway.routing.router import Router
from llm_gateway.tenants.policies import TenantPolicyStore


async def authorize_alias(
    policies: TenantPolicyStore, router: Router, *, tenant: str, alias: str
) -> tuple[AliasSettings, TenantPolicy]:
    settings = router.alias(alias)
    policy = await policies.get(tenant)
    if not policy.allows(alias):
        raise AliasNotAllowedError(alias)
    return settings, policy
