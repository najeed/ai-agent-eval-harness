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
    with pytest.raises(Exception, match="Ollama error: 500"):
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
    assert models[0]["id"] == "gpt-5.4-pro"


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
async def test_anthropic_list_models():
    p = AnthropicProvider()
    models = await p.list_models()
    assert len(models) > 0
    assert models[0]["id"] == "claude-4-6-sonnet"


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
async def test_grok_list_models():
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
