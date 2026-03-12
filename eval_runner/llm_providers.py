import os
import aiohttp
import json
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> str:
        """Generates a response for the given prompt."""
        pass

class OllamaProvider(LLMProvider):
    """Local Ollama provider."""
    
    def __init__(self, host: Optional[str] = None, model: Optional[str] = None):
        self.host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3")

    async def generate(self, prompt: str, **kwargs) -> str:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.host}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": kwargs.get("temperature", 0.0)}
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("response", "").strip()
                    else:
                        raise Exception(f"Ollama error: {response.status}")
            except Exception as e:
                raise Exception(f"Ollama connection failed: {e}")

class OpenAIProvider(LLMProvider):
    """OpenAI and compatible API provider."""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o")

    async def generate(self, prompt: str, **kwargs) -> str:
        if not self.api_key:
            raise Exception("OpenAI API key missing.")
            
        async with aiohttp.ClientSession() as session:
            try:
                headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": kwargs.get("temperature", 0.0)
                    },
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data["choices"][0]["message"]["content"].strip()
                    else:
                        error_data = await response.text()
                        raise Exception(f"OpenAI error: {response.status} - {error_data}")
            except Exception as e:
                raise Exception(f"OpenAI request failed: {e}")

class AnthropicProvider(LLMProvider):
    """Anthropic (Claude) provider."""
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620")

    async def generate(self, prompt: str, **kwargs) -> str:
        if not self.api_key:
            raise Exception("Anthropic API key missing.")
            
        async with aiohttp.ClientSession() as session:
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json={
                    "model": self.model,
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": kwargs.get("temperature", 0.0)
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["content"][0]["text"].strip()
                else:
                    raise Exception(f"Anthropic error: {response.status}")

class GeminiProvider(LLMProvider):
    """Google Gemini provider."""
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

    async def generate(self, prompt: str, **kwargs) -> str:
        if not self.api_key:
            raise Exception("Google API key missing.")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": kwargs.get("temperature", 0.0)}
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                else:
                    raise Exception(f"Gemini error: {response.status}")

class GrokProvider(LLMProvider):
    """xAI Grok provider (OpenAI-compatible)."""
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("XAI_API_KEY")
        self.model = model or os.getenv("XAI_MODEL", "grok-beta")

    async def generate(self, prompt: str, **kwargs) -> str:
        # Grok uses OpenAI-compatible API
        provider = OpenAIProvider(
            api_key=self.api_key,
            base_url="https://api.x.ai/v1",
            model=self.model
        )
        return await provider.generate(prompt, **kwargs)

class LLMProviderFactory:
    """Factory for creating LLM providers."""
    
    @staticmethod
    def create(provider_name: Optional[str] = None) -> LLMProvider:
        provider_name = provider_name or os.getenv("JUDGE_PROVIDER", "ollama")
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
