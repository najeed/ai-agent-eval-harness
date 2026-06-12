from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from eval_runner.llm_providers import (
    AnthropicProvider,
    GrokProvider,
    LLMProviderFactory,
    OpenAIProvider,
)


@pytest.mark.asyncio
async def test_openai_provider_error_status():
    """Verify OpenAIProvider throws correct error on non-200 responses."""
    provider = OpenAIProvider(api_key="fake_key")

    mock_response = AsyncMock()
    mock_response.status = 400
    mock_response.text = AsyncMock(return_value="Invalid request parameters")

    mock_context_manager = MagicMock()
    mock_context_manager.__aenter__ = AsyncMock(return_value=mock_response)
    mock_context_manager.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_context_manager)

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=session_cm):
        with pytest.raises(Exception) as exc:
            await provider.generate("hello")
        assert "OpenAI error 400: Invalid request parameters" in str(exc.value)


@pytest.mark.asyncio
async def test_openai_list_models_failures():
    """Verify OpenAIProvider list_models returns default future models on failures."""
    provider = OpenAIProvider(api_key="fake_key")

    # 1. Non-200 response
    mock_response = AsyncMock()
    mock_response.status = 500

    mock_context_manager = MagicMock()
    mock_context_manager.__aenter__ = AsyncMock(return_value=mock_response)
    mock_context_manager.__aexit__ = AsyncMock(return_value=None)

    mock_session_1 = MagicMock()
    mock_session_1.get = MagicMock(return_value=mock_context_manager)

    session_cm_1 = MagicMock()
    session_cm_1.__aenter__ = AsyncMock(return_value=mock_session_1)
    session_cm_1.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=session_cm_1):
        models = await provider.list_models()
        assert len(models) == 2
        assert models[0]["id"] == "gpt-5.4-pro"

    # 2. Connection Exception (except block)
    mock_session_2 = MagicMock()
    mock_session_2.get = MagicMock(side_effect=aiohttp.ClientError("connection refused"))

    session_cm_2 = MagicMock()
    session_cm_2.__aenter__ = AsyncMock(return_value=mock_session_2)
    session_cm_2.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=session_cm_2):
        models = await provider.list_models()
        assert len(models) == 2


@pytest.mark.asyncio
async def test_anthropic_provider_error_status():
    """Verify AnthropicProvider throws correct error on non-200 responses."""
    provider = AnthropicProvider(api_key="fake_key")

    mock_response = AsyncMock()
    mock_response.status = 429
    mock_response.text = AsyncMock(return_value="Rate limit exceeded")

    mock_context_manager = MagicMock()
    mock_context_manager.__aenter__ = AsyncMock(return_value=mock_response)
    mock_context_manager.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_context_manager)

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    session_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=session_cm):
        with pytest.raises(Exception) as exc:
            await provider.generate("hello")
        assert "Anthropic error 429: Rate limit exceeded" in str(exc.value)


@pytest.mark.asyncio
async def test_grok_provider_generation():
    """Verify GrokProvider delegates correctly to OpenAIProvider backend."""
    provider = GrokProvider(api_key="fake_grok_key", model="grok-4")

    mock_openai_generate = AsyncMock(return_value="Grok response text")
    with patch("eval_runner.llm_providers.OpenAIProvider.generate", mock_openai_generate):
        res = await provider.generate("hello")
        assert res == "Grok response text"
        mock_openai_generate.assert_called_once_with("hello")


def test_provider_factory_unknown():
    """Verify provider factory raises error for unknown providers."""
    with pytest.raises(ValueError) as exc:
        LLMProviderFactory.create("unknown_prov")
    assert "Unknown LLM provider" in str(exc.value)


def test_provider_factory_ollama():
    """Verify provider factory creates OllamaProvider."""
    prov = LLMProviderFactory.create("ollama")
    assert prov.__class__.__name__ == "OllamaProvider"
