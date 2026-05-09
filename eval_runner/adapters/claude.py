from typing import Any

from .. import config
from ..events import emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub, SessionManager


class ClaudeAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Ecosystem Adapter for Anthropic Claude API.
    Registers the 'claude' protocol.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="claude")

    def on_discover_adapters(self, registry: Any):
        """Register the claude:// protocol."""
        print("      [Plugin] Registering Claude adapter via on_discover_adapters hook.")
        registry.register("claude", self.execute_claude_query)

    async def execute_claude_query(
        self, payload: dict[str, Any], url: str = None
    ) -> dict[str, Any]:
        """
        Executes a query against the Anthropic Claude Messages API with industrial hardening.
        """

        api_key = payload.get("api_key") or config.ANTHROPIC_API_KEY
        model = payload.get("model", config.ANTHROPIC_MODEL)
        url = url or config.ANTHROPIC_BASE_URL

        headers = {
            "x-api-key": str(api_key or "missing"),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        messages = payload.get("messages", [])
        system_prompt = payload.get("system_prompt", "")
        if not messages and "task" in payload:
            messages = [{"role": "user", "content": payload["task"]}]

        claude_payload = {
            "model": model,
            "max_tokens": payload.get("max_tokens", 4096),
            "messages": messages,
            "temperature": payload.get("temperature", 0.7),
        }
        if system_prompt:
            claude_payload["system"] = system_prompt

        async def _call():
            session = await SessionManager.get_session()
            async with session.post(url, json=claude_payload, headers=headers) as response:
                if response.status != 200:
                    response.raise_for_status()
                return await response.json(), response.status

        try:
            data, status = await self.call_with_retry(_call)
            output = data.get("content", [{}])[0].get("text", "")
            action = DualNormalizationHub.normalize_text(output)

            # [Industrial Telemetry]: Extract token usage
            usage = data.get("usage", {})
            if usage:
                emit(
                    "metric_update",
                    {
                        "adapter": "claude",
                        "tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                        "prompt_tokens": usage.get("input_tokens", 0),
                        "completion_tokens": usage.get("output_tokens", 0),
                    },
                )

            return {
                "status": "success",
                "output": output,
                "action": action,
                "metadata": {
                    "model": model,
                    "framework": "claude",
                    "usage": usage,
                },
            }
        except Exception as e:
            return {"status": "error", "action": "error", "message": str(e)}
