"""Async job worker entry point: ``llm-gateway-worker``."""

from __future__ import annotations

import asyncio
import signal
from contextlib import AsyncExitStack

import structlog
from prometheus_client import start_http_server

from llm_gateway import __version__
from llm_gateway.config.settings import Settings
from llm_gateway.container import build_container
from llm_gateway.jobs.worker import JobProcessor, SqsJobConsumer
from llm_gateway.observability.logging import configure_logging

log = structlog.get_logger(__name__)


def _stop_on_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loops; containers run on Linux
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


async def run_worker(settings: Settings) -> None:
    if settings.jobs_queue_url is None or not settings.jobs_enabled:
        raise SystemExit("LLMGW_JOBS_TABLE and LLMGW_JOBS_QUEUE_URL must be set for the worker.")

    stop = asyncio.Event()
    _stop_on_signals(stop)

    async with AsyncExitStack() as stack:
        container = await build_container(settings, stack)
        if container.sqs is None or container.job_repository is None:
            raise SystemExit("The job store and queue failed to initialise.")

        consumer = SqsJobConsumer(
            container.sqs,
            queue_url=settings.jobs_queue_url,
            processor=JobProcessor(chat=container.chat, repository=container.job_repository),
            concurrency=settings.worker_concurrency,
        )
        log.info("worker_started", version=__version__, concurrency=settings.worker_concurrency)
        await consumer.run(stop)
        log.info("worker_stopped")


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format)
    start_http_server(settings.metrics_port)
    asyncio.run(run_worker(settings))


if __name__ == "__main__":
    main()
