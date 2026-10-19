"""Resolve provider credentials from Secrets Manager (or the environment, for local runs).

Secrets are read once at startup. Azure keys rotate with the two-key pattern: rotate the
unused key, update the secret, then roll the deployment. The old key stays valid until
the rollout finishes, so no in-process refresh is needed.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types_aiobotocore_secretsmanager import SecretsManagerClient

_ENV_PREFIX = "env:"


class SecretResolutionError(RuntimeError):
    pass


class SecretResolver:
    def __init__(self, client_factory: Callable[[], Awaitable[SecretsManagerClient]]) -> None:
        self._client_factory = client_factory

    async def resolve(self, reference: str) -> str:
        if reference.startswith(_ENV_PREFIX):
            name = reference.removeprefix(_ENV_PREFIX)
            value = os.environ.get(name)
            if not value:
                raise SecretResolutionError(f"environment variable {name} is not set")
            return value

        client = await self._client_factory()
        response = await client.get_secret_value(SecretId=reference)
        value = response.get("SecretString")
        if not value:
            raise SecretResolutionError(f"secret {reference} has no string value")
        return value
