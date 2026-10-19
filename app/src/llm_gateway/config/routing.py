"""Routing configuration: providers, model aliases and the default tenant policy.

The file is mounted from a ConfigMap. Clients only ever see alias names (``fast``,
``smart``, ``private``); each alias lists the providers to try, in order.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

TokenParameter = Literal["max_tokens", "max_completion_tokens"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CircuitBreakerSettings(_Frozen):
    failure_threshold: int = Field(default=5, ge=1)
    reset_timeout_s: float = Field(default=30.0, gt=0)


class _ProviderBase(_Frozen):
    connect_timeout_s: float = Field(default=3.0, gt=0)
    read_timeout_s: float = Field(default=120.0, gt=0)
    circuit_breaker: CircuitBreakerSettings = CircuitBreakerSettings()


class BedrockProviderSettings(_ProviderBase):
    type: Literal["bedrock"]
    model_id: str = Field(min_length=1, description="Model ID or inference profile ID.")
    region: str | None = Field(default=None, description="Defaults to the pod's region.")


class AzureOpenAIProviderSettings(_ProviderBase):
    type: Literal["azure_openai"]
    endpoint: HttpUrl
    deployment: str = Field(min_length=1)
    api_version: str = Field(min_length=1)
    api_key_secret: str = Field(
        min_length=1, description="Secrets Manager secret ID, or 'env:VAR' for local runs."
    )
    token_parameter: TokenParameter = "max_tokens"  # noqa: S105 - a parameter name


class OpenAICompatibleProviderSettings(_ProviderBase):
    type: Literal["openai_compatible"]
    base_url: HttpUrl
    model: str = Field(min_length=1)
    api_key_secret: str | None = None
    token_parameter: TokenParameter = "max_tokens"  # noqa: S105 - a parameter name


class MockProviderSettings(_ProviderBase):
    """Echo provider for local development and tests."""

    type: Literal["mock"]
    chunk_delay_s: float = Field(default=0.0, ge=0)


ProviderSettings = Annotated[
    BedrockProviderSettings
    | AzureOpenAIProviderSettings
    | OpenAICompatibleProviderSettings
    | MockProviderSettings,
    Field(discriminator="type"),
]


class AliasSettings(_Frozen):
    description: str = ""
    chain: tuple[str, ...] = Field(min_length=1, description="Providers to try, in order.")
    max_output_tokens: int = Field(default=4096, ge=1)


class TenantPolicy(_Frozen):
    tokens_per_minute: int = Field(ge=1)
    allowed_aliases: frozenset[str] | None = Field(
        default=None, description="None allows every alias."
    )

    def allows(self, alias: str) -> bool:
        return self.allowed_aliases is None or alias in self.allowed_aliases


class RoutingConfig(_Frozen):
    providers: dict[str, ProviderSettings] = Field(min_length=1)
    aliases: dict[str, AliasSettings] = Field(min_length=1)
    default_tenant_policy: TenantPolicy

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        missing = sorted(
            f"{alias} -> {provider}"
            for alias, settings in self.aliases.items()
            for provider in settings.chain
            if provider not in self.providers
        )
        if missing:
            raise ValueError(f"aliases reference unknown providers: {', '.join(missing)}")
        allowed = self.default_tenant_policy.allowed_aliases or frozenset()
        if unknown := sorted(allowed - self.aliases.keys()):
            raise ValueError(f"default_tenant_policy allows unknown aliases: {', '.join(unknown)}")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> RoutingConfig:
        with path.open(encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))
