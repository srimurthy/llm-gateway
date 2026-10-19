"""ASGI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import structlog
from fastapi import FastAPI
from prometheus_client import make_asgi_app

from llm_gateway import __version__
from llm_gateway.api.errors import install_exception_handlers
from llm_gateway.api.routes import chat, health, jobs, models
from llm_gateway.config.settings import Settings
from llm_gateway.container import ContainerFactory, build_container
from llm_gateway.observability.logging import configure_logging
from llm_gateway.observability.middleware import RequestContextMiddleware
from llm_gateway.observability.tracing import configure_tracing

log = structlog.get_logger(__name__)


def create_app(
    settings: Settings | None = None, *, container_factory: ContainerFactory = build_container
) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            app.state.container = await container_factory(settings, stack)
            log.info(
                "gateway_started",
                version=__version__,
                environment=settings.environment,
                region=settings.aws_region,
            )
            yield
            log.info("gateway_stopping")
            app.state.container = None

    is_prod = settings.environment == "prod"
    app = FastAPI(
        title="LLM Gateway",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if is_prod else "/openapi.json",
    )
    app.state.container = None
    install_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    for module in (health, chat, models, jobs):
        app.include_router(module.router)
    # Scraped through the sidecar's merged metrics; the VirtualService never routes here.
    app.mount("/metrics", make_asgi_app())
    configure_tracing(app, settings)
    return app
