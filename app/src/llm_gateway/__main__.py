"""API server entry point: ``python -m llm_gateway``."""

from __future__ import annotations

import uvicorn

from llm_gateway.config.settings import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "llm_gateway.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        # One process per container; Kubernetes scales pods, not workers.
        workers=1,
        log_config=None,
        access_log=False,
        server_header=False,
        timeout_graceful_shutdown=settings.shutdown_timeout_s,
        # Envoy holds idle upstream connections for up to an hour; never close first.
        timeout_keep_alive=3700,
    )


if __name__ == "__main__":
    main()
