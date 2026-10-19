"""AWS clients with explicit timeouts and lifetimes.

Every client is entered into the application's ``AsyncExitStack``, so connections close
on shutdown in reverse order of creation. Clients are created lazily and cached.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

from aiobotocore.config import AioConfig

if TYPE_CHECKING:
    from aiobotocore.session import AioSession
    from types_aiobotocore_bedrock_runtime import BedrockRuntimeClient
    from types_aiobotocore_dynamodb import DynamoDBClient
    from types_aiobotocore_secretsmanager import SecretsManagerClient
    from types_aiobotocore_sqs import SQSClient

# The router falls back between providers, so SDK-level retries stay minimal.
_RETRIES = {"mode": "standard", "max_attempts": 2}


class AwsClients:
    def __init__(self, session: AioSession, stack: AsyncExitStack, *, region: str) -> None:
        self._session = session
        self._stack = stack
        self._region = region
        self._bedrock: dict[tuple[str, float, float], BedrockRuntimeClient] = {}
        self._dynamodb: DynamoDBClient | None = None
        self._sqs: SQSClient | None = None
        self._secrets: SecretsManagerClient | None = None

    async def bedrock_runtime(
        self, *, region: str | None, connect_timeout_s: float, read_timeout_s: float
    ) -> BedrockRuntimeClient:
        key = (region or self._region, connect_timeout_s, read_timeout_s)
        if key not in self._bedrock:
            config = AioConfig(
                connect_timeout=connect_timeout_s,
                read_timeout=read_timeout_s,
                retries=_RETRIES,
                max_pool_connections=512,
                tcp_keepalive=True,
            )
            self._bedrock[key] = await self._stack.enter_async_context(
                self._session.create_client("bedrock-runtime", region_name=key[0], config=config)
            )
        return self._bedrock[key]

    async def dynamodb(self) -> DynamoDBClient:
        if self._dynamodb is None:
            config = AioConfig(
                connect_timeout=2,
                read_timeout=5,
                retries=_RETRIES,
                max_pool_connections=128,
            )
            self._dynamodb = await self._stack.enter_async_context(
                self._session.create_client("dynamodb", region_name=self._region, config=config)
            )
        return self._dynamodb

    async def sqs(self) -> SQSClient:
        if self._sqs is None:
            # Read timeout must exceed the 20s long-poll wait.
            config = AioConfig(
                connect_timeout=2,
                read_timeout=30,
                retries=_RETRIES,
                max_pool_connections=64,
            )
            self._sqs = await self._stack.enter_async_context(
                self._session.create_client("sqs", region_name=self._region, config=config)
            )
        return self._sqs

    async def secrets_manager(self) -> SecretsManagerClient:
        if self._secrets is None:
            config = AioConfig(connect_timeout=2, read_timeout=5, retries=_RETRIES)
            self._secrets = await self._stack.enter_async_context(
                self._session.create_client(
                    "secretsmanager", region_name=self._region, config=config
                )
            )
        return self._secrets
