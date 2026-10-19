from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from llm_gateway.config.routing import AzureOpenAIProviderSettings, RoutingConfig

CONFIG_DIR = Path(__file__).parents[2] / "config"


@pytest.mark.parametrize("name", ["routing.local.yaml", "routing.example.yaml"])
def test_shipped_routing_files_are_valid(name: str) -> None:
    config = RoutingConfig.from_yaml(CONFIG_DIR / name)

    assert config.aliases


def test_example_file_parses_provider_types() -> None:
    config = RoutingConfig.from_yaml(CONFIG_DIR / "routing.example.yaml")

    assert isinstance(config.providers["azure-gpt4o-eastus2"], AzureOpenAIProviderSettings)


def test_alias_referencing_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown providers: fast -> ghost"):
        RoutingConfig.model_validate(
            {
                "providers": {"m": {"type": "mock"}},
                "aliases": {"fast": {"chain": ["m", "ghost"]}},
                "default_tenant_policy": {"tokens_per_minute": 10},
            }
        )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RoutingConfig.model_validate(
            {
                "providers": {"m": {"type": "mock", "typo_field": 1}},
                "aliases": {"fast": {"chain": ["m"]}},
                "default_tenant_policy": {"tokens_per_minute": 10},
            }
        )


HELM_VALUES = Path(__file__).parents[3] / "deploy" / "charts" / "llm-gateway" / "values.yaml"


@pytest.mark.skipif(not HELM_VALUES.exists(), reason="deploy/ not present")
def test_helm_chart_routing_matches_the_app_schema() -> None:
    """The routing block in the Helm values is what production loads; keep it valid."""
    values = yaml.safe_load(HELM_VALUES.read_text(encoding="utf-8"))

    config = RoutingConfig.model_validate(values["routing"])

    assert config.aliases
