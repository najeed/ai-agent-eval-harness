# eval_runner/adapters/openai.py
import os
from typing import Any

from ..events import emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub, SessionManager


class OpenAIAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Ecosystem Adapter for OpenAI-compatible APIs.
    Registers the 'openai' protocol.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="openai")

    def on_discover_adapters(self, registry: Any):
        """Register the openai:// protocol."""
        print("      [Plugin] Registering OpenAI adapter via on_discover_adapters hook.")
        registry.register("openai", self.execute_openai_query)

    async def execute_openai_query(
        self, payload: dict[str, Any], base_url: str = None
    ) -> dict[str, Any]:
        """
        Executes a query against an OpenAI-compatible endpoint with industrial hardening.
        """

        api_key = payload.get("api_key") or os.getenv("OPENAI_API_KEY")
        base_url = (
            base_url or payload.get("base_url") or "https://api.openai.com/v1/chat/completions"
        )
        model = payload.get("model", "gpt-5.4-mini")

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

        async def _call():
            session = await SessionManager.get_session()
            async with session.post(base_url, json=openai_payload, headers=headers) as response:
                if response.status != 200:
                    # Trigger retry logic for transient codes
                    response.raise_for_status()
                return await response.json(), response.status

        try:
            data, status = await self.call_with_retry(_call)
            output = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            action = DualNormalizationHub.normalize_text(output)

            # [Industrial Telemetry]: Extract token usage
            usage = data.get("usage", {})
            if usage:
                emit(
                    "metric_update",
                    {
                        "adapter": "openai",
                        "tokens": usage.get("total_tokens"),
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                    },
                )

            return {
                "status": "success",
                "output": output,
                "action": action,
                "metadata": {
                    "model": model,
                    "framework": "openai",
                    "usage": usage,
                },
            }
        except Exception as e:
            return {"status": "error", "action": "error", "message": str(e)}
