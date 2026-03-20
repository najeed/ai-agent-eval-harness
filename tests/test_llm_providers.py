import pytest
import os
from unittest.mock import AsyncMock, patch
from eval_runner.llm_providers import (
    LLMProviderFactory,
    OllamaProvider,
    OpenAIProvider,
    AnthropicProvider,
    GeminiProvider,
    GrokProvider,
)


@pytest.mark.asyncio
async def test_ollama_provider():
    provider = OllamaProvider(host="http://mock", model="m")
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"response": "0.8"}
        mock_post.return_value.__aenter__.return_value = mock_response

        result = await provider.generate("test")
        assert result == "0.8"


@pytest.mark.asyncio
async def test_openai_provider():
    provider = OpenAIProvider(api_key="sk-test", model="gpt-4o")
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": "0.9"}}]}
        mock_post.return_value.__aenter__.return_value = mock_response

        result = await provider.generate("test")
        assert result == "0.9"


@pytest.mark.asyncio
async def test_anthropic_provider():
    provider = AnthropicProvider(api_key="ak-test")
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"content": [{"text": "1.0"}]}
        mock_post.return_value.__aenter__.return_value = mock_response

        result = await provider.generate("test")
        assert result == "1.0"


@pytest.mark.asyncio
async def test_gemini_provider():
    provider = GeminiProvider(api_key="gk-test")
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "0.7"}]}}]
        }
        mock_post.return_value.__aenter__.return_value = mock_response

        result = await provider.generate("test")
        assert result == "0.7"


def test_provider_factory():
    from eval_runner import config

    with patch("eval_runner.config.JUDGE_PROVIDER", "openai"):
        provider = LLMProviderFactory.create()
        assert isinstance(provider, OpenAIProvider)

    with patch("eval_runner.config.JUDGE_PROVIDER", "anthropic"):
        provider = LLMProviderFactory.create()
        assert isinstance(provider, AnthropicProvider)

    with patch("eval_runner.config.JUDGE_PROVIDER", "grok"):
        provider = LLMProviderFactory.create()
        assert isinstance(provider, GrokProvider)
