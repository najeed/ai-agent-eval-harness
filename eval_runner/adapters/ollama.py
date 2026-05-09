from typing import Any

from .. import config
from ..events import emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub, SessionManager


class OllamaAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Ecosystem Adapter for Ollama (Local LLM Server).
    Registers the 'ollama' protocol to allow direct communication with Ollama agents.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="ollama")

    def on_discover_adapters(self, registry: Any):
        """Register the ollama:// protocol."""
        print("      [Plugin] Registering Ollama adapter via on_discover_adapters hook.")
        registry.register("ollama", self.execute_ollama_query)

    async def execute_ollama_query(
        self, payload: dict[str, Any], url: str = None
    ) -> dict[str, Any]:
        """
        Executes a query against a local Ollama instance with industrial hardening.
        """

        base_url = url or payload.get("ollama_url") or config.OLLAMA_API_URL
        model = payload.get("model", "llama4")

        # Translate harness task into Ollama chat format
        messages = payload.get("messages", [])
        if not messages and "task" in payload:
            messages = [{"role": "user", "content": payload["task"]}]

        ollama_payload = {"model": model, "messages": messages, "stream": False}

        async def _call():
            session = await SessionManager.get_session()
            async with session.post(base_url, json=ollama_payload) as response:
                if response.status != 200:
                    response.raise_for_status()
                return await response.json(), response.status

        try:
            data, status = await self.call_with_retry(_call)
            output = data.get("message", {}).get("content", "")
            action = DualNormalizationHub.normalize_text(output)

            # [Industrial Telemetry]: Ollama typically provides 'eval_count' as tokens
            tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
            if tokens:
                emit(
                    "metric_update",
                    {
                        "adapter": "ollama",
                        "tokens": tokens,
                        "prompt_tokens": data.get("prompt_eval_count", 0),
                        "completion_tokens": data.get("eval_count", 0),
                    },
                )

            return {
                "status": "success",
                "output": output,
                "action": action,
                "metadata": {
                    "model": model,
                    "framework": "ollama",
                    "usage": {
                        "prompt_eval_count": data.get("prompt_eval_count"),
                        "eval_count": data.get("eval_count"),
                    },
                },
            }
        except Exception as e:
            return {"status": "error", "action": "error", "message": str(e)}
