"""Doubao / Volcengine Ark as a first-class OpenAI-compatible provider."""

import pytest

from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.llm_clients.model_catalog import get_model_options
from tradingagents.llm_clients.openai_client import OPENAI_COMPATIBLE_PROVIDERS
from tradingagents.llm_clients.validators import validate_model

ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"


@pytest.mark.unit
def test_cli_defaults_use_seed_21_pro_and_turbo():
    deep = [value for _, value in get_model_options("doubao", "deep")]
    quick = [value for _, value in get_model_options("doubao", "quick")]
    assert deep[0] == "doubao-seed-2.1-pro"
    assert quick[0] == "doubao-seed-2.1-turbo"


@pytest.mark.unit
def test_factory_uses_ark_endpoint_and_key(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "ark-test-key")
    llm = create_llm_client(
        provider="doubao", model="doubao-seed-2.1-pro"
    ).get_llm()
    assert str(llm.openai_api_base) == ARK_BASE
    key = (
        llm.openai_api_key.get_secret_value()
        if hasattr(llm.openai_api_key, "get_secret_value")
        else llm.openai_api_key
    )
    assert key == "ark-test-key"
    assert getattr(llm, "use_responses_api", False) in (False, None)


@pytest.mark.unit
def test_missing_ark_key_raises(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ARK_API_KEY"):
        create_llm_client(provider="doubao", model="doubao-seed-2.1-pro").get_llm()


@pytest.mark.unit
def test_endpoint_ids_and_aliases_are_accepted():
    assert get_api_key_env("doubao") == "ARK_API_KEY"
    assert validate_model("doubao", "doubao-seed-2.1-pro") is True
    assert validate_model("doubao", "ep-20260914-test") is True
    assert OPENAI_COMPATIBLE_PROVIDERS["doubao"].key_optional is False


@pytest.mark.unit
def test_cli_default_url_is_ark():
    from cli.utils import provider_default_url

    assert provider_default_url("doubao") == ARK_BASE
