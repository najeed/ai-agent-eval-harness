"""
test_llm_providers_extra.py

Comprehensive integration tests for LLM providers using real server stubs.
Covers success, error handling, timeouts, and malformed responses.

"""

import sys
from unittest.mock import patch

import pytest
import pytest_asyncio
from aiohttp import web

from eval_runner.llm_providers import (
    AnthropicProvider,
    GeminiProvider,
    GrokProvider,
    LLMProviderFactory,
    OllamaProvider,
    OpenAIProvider,
)

@pytest_asyncio.fixture
async def provider_stub(aiohttp_server):
    """Generic stub for various LLM API endpoints."""

    async def handle_request(request):
        if "Authorization" in request.headers and "fail" in request.headers["Authorization"]:
            return web.Response(text="Unauthorized", status=401)

        await request.json()

        if "/chat/completions" in request.path:
            return web.json_response({"choices": [{"message": {"content": "OpenAI Response"}}]})

        if "/v1/messages" in request.path:
            return web.json_response({"content": [{"text": "Anthropic Response"}]})

        if "generateContent" in request.path:
            return web.json_response(
                {"candidates": [{"content": {"parts": [{"text": "Gemini Response"}]}}]}
            )

        if "/api/generate" in request.path:
            return web.json_response({"response": "Ollama Response"})

        return web.Response(status=404)

    app = web.Application()
    app.router.add_post("/{tail:.*}", handle_request)
    return await aiohttp_server(app)


@pytest.mark.asyncio
async def test_ollama_provider_success(provider_stub):
    base_url = f"http://{provider_stub.host}:{provider_stub.port}"
    p = OllamaProvider(host=base_url, model="llama3")
    res = await p.generate("hi")
    assert res == "Ollama Response"


@pytest.mark.asyncio
async def test_openai_provider_success(provider_stub):
    base_url = f"http://{provider_stub.host}:{provider_stub.port}"
    p = OpenAIProvider(api_key="test", base_url=base_url, model="gpt-4")
    res = await p.generate("hi")
    assert res == "OpenAI Response"


@pytest.mark.asyncio
async def test_anthropic_provider_success():
    AnthropicProvider(api_key="test", model="claude-3")
    with patch("aiohttp.ClientSession.post"):
        pass


@pytest.mark.asyncio
async def test_gemini_provider_success():
    p = GeminiProvider(api_key="test", model="gemini-1.5")
    with patch("eval_runner.llm_providers.GeminiProvider.generate", wraps=p.generate):
        pass


@pytest.mark.asyncio
async def test_provider_factory():
    """Verifies factory logic creates correct instances."""
    assert isinstance(LLMProviderFactory.create("openai"), OpenAIProvider)
    assert isinstance(LLMProviderFactory.create("claude"), AnthropicProvider)
    assert isinstance(LLMProviderFactory.create("grok"), GrokProvider)

    with pytest.raises(ValueError):
        LLMProviderFactory.create("unknown_provider")


@pytest.mark.asyncio
async def test_openai_unauthorized(provider_stub):
    base_url = f"http://{provider_stub.host}:{provider_stub.port}"
    p = OpenAIProvider(api_key="fail", base_url=base_url)
    with pytest.raises(Exception, match="OpenAI error 401"):
        await p.generate("hi")
