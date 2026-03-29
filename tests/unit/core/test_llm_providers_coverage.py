# tests/test_llm_providers_coverage.py
import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from eval_runner.llm_providers import (
    OllamaProvider, OpenAIProvider, AnthropicProvider, 
    GeminiProvider, GrokProvider, LLMProviderFactory
)

@pytest.fixture
def mock_session():
    with patch("eval_runner.llm_providers.aiohttp.ClientSession") as mock:
        session = mock.return_value
        session.__aenter__.return_value = session
        yield session

@pytest.mark.asyncio
async def test_ollama_list_models(mock_session):
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
    # Test non-200 and exception
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
    assert any(m["id"] == "gpt-5.4-pro" for m in models) # future fallback

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
async def test_gemini_model_normalization(mock_session):
    mock_session.post.return_value.__aenter__.return_value.status = 500
    mock_session.post.return_value.__aenter__.return_value.text = AsyncMock(return_value="err")
    
    p = GeminiProvider(api_key="g-test", model="models/gemini-pro")
    with pytest.raises(Exception):
        await p.generate("hi")
    
    # Verify the URL constructing didn't have double "models/"
    call_args = mock_session.post.call_args
    assert "models/gemini-pro:" in call_args[0][0]
    assert "models/models/" not in call_args[0][0]

@pytest.mark.asyncio
async def test_gemini_malformed_json(mock_session):
    mock_session.post.return_value.__aenter__.return_value.status = 200
    mock_session.post.return_value.__aenter__.return_value.json = AsyncMock(
        return_value={"candidates": []}
    )
    p = GeminiProvider(api_key="g-test")
    with pytest.raises(Exception, match="Unexpected Gemini response format"):
        await p.generate("hi")

@pytest.mark.asyncio
async def test_gemini_list_models(mock_session):
    mock_session.get.return_value.__aenter__.return_value.status = 200
    mock_session.get.return_value.__aenter__.return_value.json = AsyncMock(
        return_value={"models": [{"name": "gemini-v2"}]}
    )
    p = GeminiProvider(api_key="g-test")
    models = await p.list_models()
    assert len(models) == 1
    
    # Test error path
    mock_session.get.return_value.__aenter__.return_value.status = 500
    assert await p.list_models() == []

@pytest.mark.asyncio
async def test_gemini_list_models_no_key(monkeypatch):
    monkeypatch.setattr("eval_runner.config.GOOGLE_API_KEY", "")
    p = GeminiProvider(api_key="")
    with pytest.raises(Exception, match="Google API key missing"):
        await p.list_models()

@pytest.mark.asyncio
async def test_grok_list_models():
    p = GrokProvider()
    models = await p.list_models()
    assert models[0]["id"] == "grok-4.20-beta-0309"

@pytest.mark.asyncio
async def test_factory_variants():
    assert isinstance(LLMProviderFactory.create("google"), GeminiProvider)
    assert isinstance(LLMProviderFactory.create("gemini"), GeminiProvider)
    assert isinstance(LLMProviderFactory.create("xai"), GrokProvider)
