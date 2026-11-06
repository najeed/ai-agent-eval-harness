"""
Consolidated LLM Provider Test Suite for AgentV Evaluation Harness.
Verifies OpenAI, Gemini (SDK), Anthropic, Ollama, and Grok providers,
including generation, model listing, and factory dispatch.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.llm_providers import (
    AnthropicProvider,
    GeminiProvider,
    GrokProvider,
    LLMProviderFactory,
    OllamaProvider,
    OpenAIProvider,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_class,base,key_header",
    [
        (AnthropicProvider, "https://api.anthropic.com/v1/models", "x-api-key"),
        (GrokProvider, "https://api.x.ai/v1/models", "Authorization"),
    ],
)
async def test_authenticated_discovery_uses_live_catalog(
    mock_session, monkeypatch, provider_class, base, key_header
):
    from eval_runner import config

    monkeypatch.setattr(config, "ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages")
    monkeypatch.setattr(config, "XAI_BASE_URL", "https://api.x.ai/v1")
    response = mock_session.get.return_value.__aenter__.return_value
    response.status = 200
    response.json = AsyncMock(
        return_value={"data": [{"id": "actual-model", "display_name": "Actual"}]}
    )
    models = await provider_class(api_key="test-discovery-key").list_models()
    assert models == [{"id": "actual-model", "display_name": "Actual", "name": "Actual"}]
    assert mock_session.get.call_args.args[0] == base
    assert key_header in mock_session.get.call_args.kwargs["headers"]
    assert mock_session.get.call_args.kwargs["allow_redirects"] is False


@pytest.mark.asyncio
async def test_anthropic_discovery_paginates_and_rejects_repeated_cursor(mock_session, monkeypatch):
    from eval_runner.llm_resilience import LLMInvalidRequestError

    monkeypatch.setattr("eval_runner.config.LLM_MAX_RETRIES", 0)
    response = mock_session.get.return_value.__aenter__.return_value
    response.status = 200
    first = {"data": [{"id": "one"}], "has_more": True, "last_id": "one"}
    response.json = AsyncMock(side_effect=[first, {"data": [{"id": "two"}], "has_more": False}])
    provider = AnthropicProvider(api_key="test-key")
    assert [model["id"] for model in await provider.list_models()] == ["one", "two"]
    assert mock_session.get.call_args.kwargs["params"] == {"after_id": "one"}
    response.json = AsyncMock(side_effect=[first, first])
    with pytest.raises(LLMInvalidRequestError, match="pagination"):
        await provider.list_models()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_discovery_http_denials_do_not_become_catalog_success(
    mock_session, monkeypatch, status
):
    from eval_runner.llm_resilience import LLMError

    monkeypatch.setattr("eval_runner.config.LLM_MAX_RETRIES", 0)
    response = mock_session.get.return_value.__aenter__.return_value
    response.status = status
    with pytest.raises(LLMError):
        await AnthropicProvider(api_key="test-key").list_models()


@pytest.mark.asyncio
async def test_discovery_transport_outage_has_observable_catalog_fallback(
    mock_session, monkeypatch, caplog
):
    import aiohttp

    monkeypatch.setattr("eval_runner.config.LLM_MAX_RETRIES", 0)
    mock_session.get.side_effect = aiohttp.ClientConnectionError("offline")
    assert await GrokProvider(api_key="test-key").list_models()
    assert any(
        getattr(record, "operation", None) == "list_models" and record.exc_info
        for record in caplog.records
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [None, [], {}, {"data": {}}, {"data": [None]}, {"data": [{"id": ""}]}]
)
async def test_discovery_malformed_catalog_is_not_replaced_by_defaults(
    mock_session, monkeypatch, payload
):
    from eval_runner.llm_resilience import LLMInvalidRequestError

    monkeypatch.setattr("eval_runner.config.LLM_MAX_RETRIES", 0)
    response = mock_session.get.return_value.__aenter__.return_value
    response.status = 200
    response.json = AsyncMock(return_value=payload)
    with pytest.raises(LLMInvalidRequestError, match="Malformed"):
        await GrokProvider(api_key="test-key").list_models()


@pytest.mark.asyncio
async def test_discovery_invalid_json_and_tls_do_not_claim_offline_success(
    mock_session, monkeypatch
):
    import aiohttp

    from eval_runner.llm_resilience import LLMInvalidRequestError

    monkeypatch.setattr("eval_runner.config.LLM_MAX_RETRIES", 0)
    response = mock_session.get.return_value.__aenter__.return_value
    response.status = 200
    response.json = AsyncMock(side_effect=ValueError("invalid JSON"))
    with pytest.raises(LLMInvalidRequestError, match="Invalid JSON"):
        await GrokProvider(api_key="test-key").list_models()
    mock_session.get.side_effect = aiohttp.ClientSSLError(None, OSError("TLS failure"))
    with pytest.raises(LLMInvalidRequestError, match="TLS"):
        await GrokProvider(api_key="test-key").list_models()


@pytest.mark.asyncio
async def test_discovery_rechecks_airgap_before_network(mock_session, monkeypatch):
    from eval_runner.exceptions import AirgappedConfigurationError

    provider = GrokProvider(api_key="test-key")
    monkeypatch.setattr("eval_runner.config.is_airgapped", lambda: True)
    with pytest.raises(AirgappedConfigurationError):
        await provider.list_models()
    mock_session.get.assert_not_called()


@pytest.fixture
def mock_aiohttp():
    with patch("aiohttp.ClientSession.post") as mock_post:
        with patch("aiohttp.ClientSession.get") as mock_get:
            yield mock_post, mock_get


# --- 1. Provider Generation & Error Handling ---


@pytest.mark.asyncio
async def test_openai_provider(mock_aiohttp):
    mock_post, _ = mock_aiohttp
    mock_resp = AsyncMock(
        status=200, json=AsyncMock(return_value={"choices": [{"message": {"content": "ok"}}]})
    )
    mock_post.return_value.__aenter__.return_value = mock_resp

    p = OpenAIProvider(api_key="sk-test")
    assert await p.generate("hi") == "ok"


@pytest.mark.asyncio
async def test_ollama_provider(mock_aiohttp):
    mock_post, _ = mock_aiohttp
    mock_resp = AsyncMock(status=200, json=AsyncMock(return_value={"response": "ok"}))
    mock_post.return_value.__aenter__.return_value = mock_resp

    p = OllamaProvider()
    assert await p.generate("hi") == "ok"


@pytest.mark.asyncio
async def test_gemini_provider():
    with patch("google.genai.Client") as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.aio.models.generate_content = AsyncMock(return_value=MagicMock(text="ok"))
        p = GeminiProvider(api_key="g-test")
        assert await p.generate("hi") == "ok"


# --- 2. Model Listing ---


@pytest.mark.asyncio
async def test_list_models_ollama(mock_aiohttp):
    _, mock_get = mock_aiohttp
    mock_get.return_value.__aenter__.return_value = AsyncMock(
        status=200, json=AsyncMock(return_value={"models": [{"name": "m1"}]})
    )
    p = OllamaProvider()
    models = await p.list_models()
    assert models[0]["name"] == "m1"


@pytest.mark.asyncio
async def test_list_models_gemini():
    with patch("google.genai.Client") as mock_cls:
        mock_client = mock_cls.return_value

        async def mock_gen():
            yield MagicMock(name="m1", display_name="m1")

        mock_client.aio = MagicMock()
        mock_client.aio.models.list = MagicMock(return_value=mock_gen())
        p = GeminiProvider(api_key="g-test")
        models = await p.list_models()
        assert models[0]["name"] == "m1"


# --- 3. Factory Dispatch ---


def test_provider_factory():
    assert isinstance(LLMProviderFactory.create("openai"), OpenAIProvider)
    assert isinstance(LLMProviderFactory.create("google"), GeminiProvider)
    assert isinstance(LLMProviderFactory.create("anthropic"), AnthropicProvider)
    assert isinstance(LLMProviderFactory.create("xai"), GrokProvider)


# === Ported from test_llm_providers.py & test_llm_adapter_suite.py ===


@pytest.fixture
def mock_session():
    with patch("eval_runner.llm_providers.aiohttp.ClientSession") as mock:
        session = mock.return_value
        session.__aenter__.return_value = session
        yield session


@pytest.mark.asyncio
async def test_ollama_list_models_success(mock_session):
    mock_session.get.return_value.__aenter__.return_value.status = 200
    mock_session.get.return_value.__aenter__.return_value.json = AsyncMock(
        return_value={"models": [{"name": "m1"}]}
    )
    p = OllamaProvider()
    models = await p.list_models()
    assert len(models) == 1
    assert models[0]["name"] == "m1"


@pytest.mark.asyncio
async def test_ollama_list_models_error(mock_session):
    mock_session.get.return_value.__aenter__.return_value.status = 500
    p = OllamaProvider()
    assert await p.list_models() == []

    mock_session.get.side_effect = Exception("fail")
    assert await p.list_models() == []


@pytest.mark.asyncio
async def test_ollama_generate_error(mock_session):
    mock_session.post.return_value.__aenter__.return_value.status = 500
    p = OllamaProvider()
    with pytest.raises(Exception, match=r"(?:HTTP 500|Status 500)"):
        await p.generate("hi")


@pytest.mark.asyncio
async def test_openai_missing_key(monkeypatch):
    monkeypatch.setattr("eval_runner.config.OPENAI_API_KEY", "")
    p = OpenAIProvider(api_key="")
    with pytest.raises(Exception, match="OpenAI API key missing"):
        await p.generate("hi")


@pytest.mark.asyncio
async def test_openai_malformed_json(mock_session):
    mock_session.post.return_value.__aenter__.return_value.status = 200
    mock_session.post.return_value.__aenter__.return_value.json = AsyncMock(
        return_value={"bad": "format"}
    )
    p = OpenAIProvider(api_key="sk-test")
    with pytest.raises(Exception, match="Unexpected OpenAI response format"):
        await p.generate("hi")


@pytest.mark.asyncio
async def test_openai_list_models(mock_session):
    mock_session.get.return_value.__aenter__.return_value.status = 200
    mock_session.get.return_value.__aenter__.return_value.json = AsyncMock(
        return_value={"data": [{"id": "gpt-real"}]}
    )
    p = OpenAIProvider(api_key="sk-test")
    models = await p.list_models()
    assert any(m["id"] == "gpt-real" for m in models)


@pytest.mark.asyncio
async def test_openai_list_models_no_key():
    p = OpenAIProvider(api_key="")
    models = await p.list_models()
    assert len(models) > 0
    assert models[0]["id"] == "gpt-5.6"


@pytest.mark.asyncio
async def test_anthropic_missing_key(monkeypatch):
    monkeypatch.setattr("eval_runner.config.ANTHROPIC_API_KEY", "")
    p = AnthropicProvider(api_key="")
    with pytest.raises(Exception, match="Anthropic API key missing"):
        await p.generate("hi")


@pytest.mark.asyncio
async def test_anthropic_malformed_json(mock_session):
    mock_session.post.return_value.__aenter__.return_value.status = 200
    mock_session.post.return_value.__aenter__.return_value.json = AsyncMock(
        return_value={"content": []}
    )
    p = AnthropicProvider(api_key="at-test")
    with pytest.raises(Exception, match="Unexpected Anthropic response format"):
        await p.generate("hi")


@pytest.mark.asyncio
async def test_anthropic_list_models(monkeypatch):
    monkeypatch.setattr("eval_runner.config.ANTHROPIC_API_KEY", "")
    p = AnthropicProvider()
    models = await p.list_models()
    assert len(models) > 0
    assert models[0]["id"] == "claude-opus-5"


@pytest.mark.asyncio
async def test_gemini_missing_key(monkeypatch):
    monkeypatch.setattr("eval_runner.config.GOOGLE_API_KEY", "")
    p = GeminiProvider(api_key="")
    with pytest.raises(Exception, match="Google API key missing"):
        await p.generate("hi")


@pytest.mark.asyncio
async def test_gemini_model_normalization():
    p = GeminiProvider(api_key="g-test", model="models/gemini-pro")
    with patch("google.genai.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_response = AsyncMock()
        mock_response.text = "ok"
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        await p.generate("hi")
        call_args = mock_client.aio.models.generate_content.call_args
        assert call_args.kwargs["model"] == "models/gemini-pro"


@pytest.mark.asyncio
async def test_gemini_empty_response():
    p = GeminiProvider(api_key="g-test")
    with patch("google.genai.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_response = MagicMock()
        mock_response.text = None
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        with pytest.raises(Exception, match="Empty response from Gemini SDK"):
            await p.generate("hi")


@pytest.mark.asyncio
async def test_gemini_list_models_error():
    p = GeminiProvider(api_key="g-test")
    with patch("google.genai.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.aio = MagicMock()
        mock_client.aio.models = MagicMock()
        mock_client.aio.models.list = MagicMock(side_effect=Exception("fail"))
        assert await p.list_models() == []


@pytest.mark.asyncio
async def test_gemini_list_models_no_key(monkeypatch):
    monkeypatch.setattr("eval_runner.config.GOOGLE_API_KEY", "")
    p = GeminiProvider(api_key="")
    assert await p.list_models() == []


@pytest.mark.asyncio
async def test_grok_list_models(monkeypatch):
    monkeypatch.setattr("eval_runner.config.XAI_API_KEY", "")
    p = GrokProvider()
    models = await p.list_models()
    assert models[0]["id"] == "grok-4.20-beta-0309"


def test_provider_factory_variants():
    assert isinstance(LLMProviderFactory.create("openai"), OpenAIProvider)
    assert isinstance(LLMProviderFactory.create("claude"), AnthropicProvider)
    assert isinstance(LLMProviderFactory.create("grok"), GrokProvider)
    assert isinstance(LLMProviderFactory.create("gemini"), GeminiProvider)
    assert isinstance(LLMProviderFactory.create("xai"), GrokProvider)

    with pytest.raises(ValueError):
        LLMProviderFactory.create("unknown_provider")
