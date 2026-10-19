"""LLM gateway: one OpenAI-compatible API over Bedrock, Azure OpenAI and self-hosted models."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("llm-gateway")
except PackageNotFoundError:  # pragma: no cover - source tree without an installed distribution
    __version__ = "0.0.0"
