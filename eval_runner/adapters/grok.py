import os
from typing import Any

from .. import config
from ..events import emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub, SessionManager


class GrokAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Ecosystem Adapter for xAI Grok.
    Registers the 'grok' protocol.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="grok")

    def on_discover_adapters(self, registry: Any):
        """Register the grok:// protocol."""
        print("      [Plugin] Registering Grok adapter via on_discover_adapters hook.")
        registry.register("grok", self.execute_grok_query)

    async def execute_grok_query(self, payload: dict[str, Any], url: str = None) -> dict[str, Any]:
        """
        Calls the xAI Grok API with industrial hardening.
        """

        api_key = payload.get("api_key") or os.getenv("XAI_API_KEY")
        if not api_key:
            return {"status": "error", "action": "error", "message": "xAI API key missing."}

        model = payload.get("model") or config.XAI_MODEL
        endpoint = url or (config.XAI_BASE_URL + "/chat/completions")
        prompt = payload.get("task_description") or str(payload)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        grok_payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": payload.get("temperature", 0.0),
        }

        async def _call():
            session = await SessionManager.get_session()
            async with session.post(endpoint, headers=headers, json=grok_payload) as response:
                if response.status != 200:
                    response.raise_for_status()
                return await response.json(), response.status

        try:
            data, status = await self.call_with_retry(_call)
            output = data["choices"][0]["message"]["content"]
            action = DualNormalizationHub.normalize_text(output)

            # [Industrial Telemetry]: Extract token usage
            usage = data.get("usage", {})
            if usage:
                emit(
                    "metric_update",
                    {
                        "adapter": "grok",
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
                    "framework": "grok",
                    "usage": usage,
                },
            }
        except Exception as e:
            return {
                "status": "error",
                "action": "error",
                "message": f"Grok request failed: {str(e)}",
            }
