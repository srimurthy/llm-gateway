"""Build provider instances from the routing configuration."""

from __future__ import annotations

from contextlib import AsyncExitStack

from openai import AsyncAzureOpenAI, AsyncOpenAI, DefaultAsyncHttpxClient, Timeout

from llm_gateway.config.routing import (
    AzureOpenAIProviderSettings,
    BedrockProviderSettings,
    MockProviderSettings,
    OpenAICompatibleProviderSettings,
    ProviderSettings,
    RoutingConfig,
)
from llm_gateway.infrastructure.aws import AwsClients
from llm_gateway.infrastructure.secrets import SecretResolver
from llm_gateway.providers.base import ChatProvider
from llm_gateway.providers.bedrock import BedrockProvider
from llm_gateway.providers.mock import MockProvider
from llm_gateway.providers.openai_compatible import OpenAICompatibleProvider

# vLLM ignores the key unless started with --api-key; the SDK requires a non-empty value.
_UNUSED_API_KEY = "unused"


class ProviderFactory:
    def __init__(self, *, stack: AsyncExitStack, aws: AwsClients, secrets: SecretResolver) -> None:
        self._stack = stack
        self._aws = aws
        self._secrets = secrets
        self._http: DefaultAsyncHttpxClient | None = None

    async def build_all(self, config: RoutingConfig) -> dict[str, ChatProvider]:
        return {
            name: await self.build(name, settings) for name, settings in config.providers.items()
        }

    async def build(self, name: str, settings: ProviderSettings) -> ChatProvider:
        match settings:
            case BedrockProviderSettings():
                client = await self._aws.bedrock_runtime(
                    region=settings.region,
                    connect_timeout_s=settings.connect_timeout_s,
                    read_timeout_s=settings.read_timeout_s,
                )
                return BedrockProvider(name, model_id=settings.model_id, client=client)
            case AzureOpenAIProviderSettings():
                azure = AsyncAzureOpenAI(
                    azure_endpoint=str(settings.endpoint),
                    api_version=settings.api_version,
                    api_key=await self._secrets.resolve(settings.api_key_secret),
                    max_retries=0,
                    timeout=_timeout(settings.connect_timeout_s, settings.read_timeout_s),
                    http_client=self._http_client(),
                )
                return OpenAICompatibleProvider(
                    name,
                    client=azure,
                    model=settings.deployment,
                    token_parameter=settings.token_parameter,
                )
            case OpenAICompatibleProviderSettings():
                api_key = (
                    await self._secrets.resolve(settings.api_key_secret)
                    if settings.api_key_secret
                    else _UNUSED_API_KEY
                )
                compatible = AsyncOpenAI(
                    base_url=str(settings.base_url),
                    api_key=api_key,
                    max_retries=0,
                    timeout=_timeout(settings.connect_timeout_s, settings.read_timeout_s),
                    http_client=self._http_client(),
                )
                return OpenAICompatibleProvider(
                    name,
                    client=compatible,
                    model=settings.model,
                    token_parameter=settings.token_parameter,
                )
            case MockProviderSettings():
                return MockProvider(name, chunk_delay_s=settings.chunk_delay_s)

    def _http_client(self) -> DefaultAsyncHttpxClient:
        """One connection pool (the SDK's tuned defaults) shared by every OpenAI-style provider."""
        if self._http is None:
            self._http = DefaultAsyncHttpxClient()
            self._stack.push_async_callback(self._http.aclose)
        return self._http


def _timeout(connect_s: float, read_s: float) -> Timeout:
    return Timeout(read_s, connect=connect_s)
