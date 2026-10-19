# Common tasks. Each target mirrors a CI step, so a green `make check` predicts green CI.
SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

LIVE_ROOTS := $(shell find infra/live -name backend.tf -exec dirname {} \; | sort)
REGIONS := us-east-1 us-west-2
FAKE_DIGEST := sha256:0000000000000000000000000000000000000000000000000000000000000000

.PHONY: help
help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*## "} {printf "  %-16s %s\n", $$1, $$2}'

.PHONY: check
check: app-check tf-check deploy-check ## Everything CI runs, locally

# ---------------------------------------------------------------- app
.PHONY: app-check
app-check: ## Lint, format check, types and tests for the Python service
	cd app && uv sync --frozen
	cd app && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest --cov

.PHONY: up
up: ## Run the gateway locally with Valkey and mock providers
	docker compose up --build

# ---------------------------------------------------------------- terraform
.PHONY: tf-check
tf-check: ## terraform fmt + validate on every live root
	terraform fmt -check -recursive infra
	for root in $(LIVE_ROOTS); do \
	  terraform -chdir=$$root init -backend=false -input=false >/dev/null && \
	  terraform -chdir=$$root validate; \
	done

.PHONY: tf-lock
tf-lock: ## Write provider lock files with hashes for Linux, macOS and Windows
	for root in $(LIVE_ROOTS); do \
	  terraform -chdir=$$root providers lock \
	    -platform=linux_amd64 -platform=darwin_arm64 -platform=windows_amd64; \
	done

# ---------------------------------------------------------------- deploy
.PHONY: deploy-check
deploy-check: ## Lint the chart and build every kustomization
	for region in $(REGIONS); do \
	  helm lint deploy/charts/llm-gateway -f deploy/charts/llm-gateway/values-$$region.yaml --set image.digest=$(FAKE_DIGEST); \
	  kubectl kustomize deploy/ratelimit/overlays/$$region >/dev/null; \
	  kubectl kustomize deploy/platform/overlays/$$region >/dev/null; \
	done
	kubectl kustomize deploy/istio >/dev/null
	kubectl kustomize deploy/slm >/dev/null
