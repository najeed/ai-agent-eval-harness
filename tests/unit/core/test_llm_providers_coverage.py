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
async def test_gemini_model_normalization():
    p = GeminiProvider(api_key="g-test", model="models/gemini-pro")
    with patch("google.genai.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_response = AsyncMock()
        mock_response.text = "ok"
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        
        await p.generate("hi")
        
        # Verify the model name passed to the SDK
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
async def test_gemini_list_models():
    p = GeminiProvider(api_key="g-test")
    with patch("google.genai.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        
        # Mocking an async iterator for client.aio.models.list()
        mock_model = MagicMock()
        mock_model.name = "models/gemini-v2"
        mock_model.display_name = "models/gemini-v2"
        
        # Use a simple list and an async generator function
        async def mock_list_gen():
            yield mock_model
            
        # Ensure the whole chain is MagicMock to prevent AsyncMock from returning coroutines
        mock_client.aio = MagicMock()
        mock_client.aio.models = MagicMock()
        mock_client.aio.models.list = MagicMock(return_value=mock_list_gen())

        models = await p.list_models()
        assert len(models) == 1
        assert models[0]["name"] == "models/gemini-v2"
        
    # Test error path
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

@pytest.mark.asyncio
async def test_factory_variants():
    assert isinstance(LLMProviderFactory.create("google"), GeminiProvider)
    assert isinstance(LLMProviderFactory.create("gemini"), GeminiProvider)
    assert isinstance(LLMProviderFactory.create("xai"), GrokProvider)
