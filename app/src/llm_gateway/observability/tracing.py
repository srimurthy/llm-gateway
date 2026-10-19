"""OpenTelemetry tracing, exported over OTLP to the ADOT collector.

The exporter reads its endpoint from the standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` variable.
"""

from __future__ import annotations

from fastapi import FastAPI

from llm_gateway import __version__
from llm_gateway.config.settings import Settings


def configure_tracing(app: FastAPI, settings: Settings) -> None:
    if not settings.otel_enabled:
        return

    from opentelemetry import trace  # noqa: PLC0415 - optional at runtime
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # noqa: PLC0415
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: PLC0415
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.service_name,
                "service.version": __version__,
                "deployment.environment": settings.environment,
                "cloud.region": settings.aws_region,
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")
