# syntax=docker/dockerfile:1.7
#
# Two stages: dependencies resolve with uv against the lockfile in a builder, then only
# the virtualenv is copied into a slim runtime that runs as a non-root user.
# For production, pin both base images by digest (python:3.13-slim-bookworm@sha256:...)
# and let Renovate or Dependabot bump them.

ARG PYTHON_IMAGE=python:3.13-slim-bookworm

FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src

# Dependencies first, so source edits do not invalidate this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


FROM ${PYTHON_IMAGE} AS runtime
LABEL org.opencontainers.image.title="llm-gateway" \
      org.opencontainers.image.description="Multi-provider LLM gateway"

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv
COPY config /app/config

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LLMGW_ROUTING_CONFIG_PATH=/app/config/routing.yaml

WORKDIR /app
USER 10001:10001
EXPOSE 8080

# The same image runs the worker: override the command with ["llm-gateway-worker"].
ENTRYPOINT []
CMD ["llm-gateway"]
