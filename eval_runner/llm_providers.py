from abc import ABC, abstractmethod

import aiohttp

from . import config
from .llm_resilience import (
    LLMAuthenticationError,
    LLMError,
    LLMInvalidRequestError,
    LLMModelNotFoundError,
    LLMQuotaExceededError,
    LLMRateLimitError,
    LLMTransientError,
    classify_llm_error,
    execute_with_resilience,
)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> str:
        """Generates a response for the given prompt."""
        pass


class OllamaProvider(LLMProvider):
    """Local Ollama provider."""

    def __init__(self, host: str | None = None, model: str | None = None):
        self.host = host or config.OLLAMA_HOST
        self.model = model or config.OLLAMA_MODEL

    async def generate(self, prompt: str, **kwargs) -> str:
        async def _call():
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(
                        f"{self.host}/api/generate",
                        json={
                            "model": self.model,
                            "prompt": prompt,
                            "stream": False,
                            "options": {
                                "temperature": kwargs.get("temperature", 0.0),
                                "seed": kwargs.get("seed"),
                            },
                        },
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            return data.get("response", "").strip()
                        else:
                            raise Exception(f"Ollama error: {response.status}")
                except Exception as e:
                    if "Ollama error:" in str(e):
                        raise
                    raise Exception(f"Ollama connection failed: {e}") from e

        return await execute_with_resilience(_call, provider="ollama")

    async def list_models(self) -> list:
        """Lists available models in Ollama."""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{self.host}/api/tags") as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("models", [])
                    else:
                        return []
            except:  # noqa: E722
                return []


class OpenAIProvider(LLMProvider):
    """OpenAI and compatible API provider."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or config.OPENAI_API_KEY
        self.base_url = base_url or config.OPENAI_BASE_URL
        self.model = model or config.OPENAI_MODEL

    async def generate(self, prompt: str, **kwargs) -> str:
        if not self.api_key:
            raise LLMAuthenticationError(
                "OpenAI API key missing.", provider="openai", status_code=401
            )

        async def _call():
            async with aiohttp.ClientSession() as session:
                try:
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    }
                    async with session.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json={
                            "model": self.model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": kwargs.get("temperature", 0.0),
                            "seed": kwargs.get("seed"),
                        },
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            try:
                                return data["choices"][0]["message"]["content"].strip()
                            except (KeyError, IndexError) as err:
                                raise Exception(
                                    f"Unexpected OpenAI response format: {data}"
                                ) from err
                        else:
                            error_body = await response.text()
                            raise Exception(f"OpenAI error {response.status}: {error_body}")
                except Exception as e:
                    if "OpenAI error " in str(e) or "Unexpected OpenAI response format" in str(e):
                        raise
                    raise Exception(f"OpenAI request failed: {e}") from e

        return await execute_with_resilience(_call, provider="openai")

    async def list_models(self) -> list:
        """Lists available models in OpenAI."""
        future_models = [
            {"id": "gpt-5.6", "name": "GPT-5.6 (Production)"},
        ]
        if not self.api_key:
            return future_models

        async with aiohttp.ClientSession() as session:
            try:
                headers = {"Authorization": f"Bearer {self.api_key}"}
                async with session.get(f"{self.base_url}/models", headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return future_models + data.get("data", [])
                    else:
                        return future_models
            except:  # noqa: E722
                return future_models


class AnthropicProvider(LLMProvider):
    """Anthropic (Claude) provider."""

    def __init__(
        self, api_key: str | None = None, base_url: str | None = None, model: str | None = None
    ):
        self.api_key = api_key or config.ANTHROPIC_API_KEY
        self.base_url = base_url or config.ANTHROPIC_BASE_URL
        self.model = model or config.ANTHROPIC_MODEL

    async def generate(self, prompt: str, **kwargs) -> str:
        if not self.api_key:
            raise LLMAuthenticationError(
                "Anthropic API key missing.", provider="anthropic", status_code=401
            )

        async def _call():
            async with aiohttp.ClientSession() as session:
                try:
                    headers = {
                        "x-api-key": self.api_key,
                        "anthropic-version": config.ANTHROPIC_VERSION,
                        "content-type": "application/json",
                    }
                    async with session.post(
                        self.base_url,
                        headers=headers,
                        json={
                            "model": self.model,
                            "max_tokens": 1024,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": kwargs.get("temperature", 0.0),
                        },
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            try:
                                return data["content"][0]["text"].strip()
                            except (KeyError, IndexError) as err:
                                raise Exception(
                                    f"Unexpected Anthropic response format: {data}"
                                ) from err
                        else:
                            error_body = await response.text()
                            raise Exception(f"Anthropic error {response.status}: {error_body}")
                except Exception as e:
                    if "Anthropic error " in str(
                        e
                    ) or "Unexpected Anthropic response format" in str(e):
                        raise
                    raise Exception(f"Anthropic request failed: {e}") from e

        return await execute_with_resilience(_call, provider="anthropic")

    async def list_models(self) -> list:
        """Lists available models for Anthropic."""
        return [
            {"id": "claude-opus-5", "name": "Claude Opus 5"},
        ]


class GeminiProvider(LLMProvider):
    """
    Google Gemini provider using the modern google-genai SDK (v1.70.0+).
    Architectural Shift: Migrated from raw REST (aiohttp) to the official SDK
    for 2026 industrial-grade reliability.
    """

    def __init__(
        self, api_key: str | None = None, base_url: str | None = None, model: str | None = None
    ):
        self.api_key = api_key or config.GOOGLE_API_KEY
        self.model = model or config.GEMINI_MODEL
        # The SDK handles the base URL automatically, but we can override if needed
        self.vertex_ai = "vertexai" in (base_url or "").lower()

    async def _get_client(self):
        """Lazy initialization of the GenAI client."""
        from google import genai

        return genai.Client(
            api_key=self.api_key,
            vertexai=self.vertex_ai,
            http_options={"timeout": 30000},  # 30s in ms for the SDK
        )

    async def generate(self, prompt: str, **kwargs) -> str:
        if not self.api_key:
            raise LLMAuthenticationError(
                "Google API key missing.", provider="gemini", status_code=401
            )

        async def _call():
            try:
                client = await self._get_client()
                from google.genai import types

                response = await client.aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=kwargs.get("temperature", 0.1),
                        max_output_tokens=kwargs.get("max_output_tokens", 1024),
                        seed=kwargs.get("seed"),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )

                if response and response.text:
                    return response.text.strip()
                else:
                    raise Exception(f"Empty response from Gemini SDK: {response}")
            except Exception as e:
                if "Empty response from Gemini SDK" in str(e):
                    raise
                raise Exception(f"Gemini SDK request failed: {e}") from e

        return await execute_with_resilience(_call, provider="gemini")

    async def list_models(self) -> list:
        """Lists available models using the GenAI SDK."""
        if not self.api_key:
            return []

        try:
            client = await self._get_client()
            models = []
            async for m in client.aio.models.list():
                models.append({"id": m.name, "name": m.display_name or m.name})
            return models
        except Exception as e:
            print(f"      [Gemini] Failed to list models: {e}")
            return []


class GrokProvider(LLMProvider):
    """xAI Grok provider (OpenAI-compatible)."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or config.XAI_API_KEY
        self.model = model or config.XAI_MODEL

    async def generate(self, prompt: str, **kwargs) -> str:
        # Grok uses OpenAI-compatible API
        provider = OpenAIProvider(
            api_key=self.api_key, base_url=config.XAI_BASE_URL, model=self.model
        )
        return await provider.generate(prompt, **kwargs)

    async def list_models(self) -> list:
        """Lists available models for Grok (future series)."""
        return [
            {"id": "grok-4.20-beta-0309", "name": "Grok 4.20 Beta"},
            {"id": "grok-4-fast", "name": "Grok 4 Fast"},
            {"id": "grok-4-mini", "name": "Grok 4 Mini"},
        ]


class LLMProviderFactory:
    """Factory for creating LLM providers."""

    @staticmethod
    def create(provider_name: str | None = None) -> LLMProvider:
        provider_name = provider_name or config.JUDGE_PROVIDER
        provider_name = provider_name.lower()

        if provider_name == "ollama":
            return OllamaProvider()
        elif provider_name == "openai":
            return OpenAIProvider()
        elif provider_name == "anthropic" or provider_name == "claude":
            return AnthropicProvider()
        elif provider_name == "gemini" or provider_name == "google":
            return GeminiProvider()
        elif provider_name == "xai" or provider_name == "grok":
            return GrokProvider()
        else:
            raise ValueError(f"Unknown LLM provider: {provider_name}")


__all__ = [
    "LLMProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "GrokProvider",
    "LLMProviderFactory",
    "LLMError",
    "LLMTransientError",
    "LLMRateLimitError",
    "LLMQuotaExceededError",
    "LLMAuthenticationError",
    "LLMInvalidRequestError",
    "LLMModelNotFoundError",
    "classify_llm_error",
    "execute_with_resilience",
]
