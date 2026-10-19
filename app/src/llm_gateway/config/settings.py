"""Process settings, read from ``LLMGW_*`` environment variables.

Settings describe the deployment (region, endpoints, table names). What models exist and
how requests route between providers lives in the routing file, see ``routing.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLMGW_", frozen=True, extra="ignore")

    environment: Literal["local", "dev", "staging", "prod"] = "local"
    aws_region: str = "us-east-1"
    service_name: str = "llm-gateway"

    host: str = "0.0.0.0"  # noqa: S104 - the pod's sidecar is the only thing that reaches it
    port: int = Field(default=8080, ge=1, le=65535)
    metrics_port: int = Field(default=9090, ge=1, le=65535, description="Worker metrics port.")
    shutdown_timeout_s: int = Field(
        default=300, ge=1, description="How long open streams may run after SIGTERM."
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    routing_config_path: Path = Path("config/routing.yaml")

    tenant_header: str = Field(
        default="x-tenant-id",
        description="Header the Istio ingress gateway writes from the verified JWT claim.",
    )

    valkey_url: str = "redis://localhost:6379/0"
    valkey_password: SecretStr | None = None
    valkey_cluster_mode: bool = False
    valkey_timeout_s: float = Field(
        default=0.1, gt=0, description="Budget checks fall back to the in-pod bucket after this."
    )

    region_quota_share: float = Field(
        default=1.0,
        gt=0,
        le=1,
        description="Fraction of each tenant's tokens-per-minute this region may spend.",
    )
    local_fallback_fraction: float = Field(
        default=0.1,
        gt=0,
        le=1,
        description="Fraction of a budget each pod may spend on its own while Valkey is down.",
    )

    tenants_table: str | None = None
    usage_table: str | None = None
    usage_flush_interval_s: float = Field(default=10.0, gt=0)
    usage_retention_days: int = Field(default=90, ge=1)

    jobs_table: str | None = None
    jobs_queue_url: str | None = None
    job_retention_days: int = Field(default=7, ge=1)
    worker_concurrency: int = Field(default=16, ge=1, le=256)

    background_task_limit: int = Field(default=5000, ge=1)

    otel_enabled: bool = False

    @property
    def jobs_enabled(self) -> bool:
        return self.jobs_table is not None and self.jobs_queue_url is not None
