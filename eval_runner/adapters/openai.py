# eval_runner/adapters/openai.py
import aiohttp
import os
from typing import Any, Dict
from ..plugins import BaseEvalPlugin


class OpenAIAdapterPlugin(BaseEvalPlugin):
    """
    Ecosystem Adapter for OpenAI-compatible APIs.
    Registers the 'openai' protocol.
    """

    def on_discover_adapters(self, registry: Any):
        """Register the openai:// protocol."""
        print(
            "      [Plugin] Registering OpenAI adapter via on_discover_adapters hook."
        )
        registry.register("openai", self.execute_openai_query)

    async def execute_openai_query(
        self, payload: Dict[str, Any], base_url: str = None
    ) -> Dict[str, Any]:
        """
        Executes a query against an OpenAI-compatible endpoint.
        """
        api_key = payload.get("api_key") or os.getenv("OPENAI_API_KEY")
        base_url = (
            base_url
            or payload.get("base_url")
            or "https://api.openai.com/v1/chat/completions"
        )
        model = payload.get("model", "gpt-4-turbo-preview")

        messages = payload.get("messages", [])
        if not messages and "task" in payload:
            messages = [{"role": "user", "content": payload["task"]}]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        openai_payload = {
            "model": model,
            "messages": messages,
            "temperature": payload.get("temperature", 0.7),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    base_url, json=openai_payload, headers=headers, timeout=30
                ) as response:
                    if response.status != 200:
                        err_text = await response.text()
                        return {
                            "status": "error",
                            "message": f"OpenAI returned {response.status}: {err_text}",
                        }

                    data = await response.json()
                    return {
                        "status": "success",
                        "output": data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", ""),
                        "metadata": {"model": model, "framework": "openai"},
                    }
        except Exception as e:
            return {"status": "error", "message": str(e)}
