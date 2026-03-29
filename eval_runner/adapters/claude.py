import aiohttp
from typing import Any, Dict
from ..plugins import BaseEvalPlugin
from .. import config


class ClaudeAdapterPlugin(BaseEvalPlugin):
    """
    Ecosystem Adapter for Anthropic Claude API.
    Registers the 'claude' protocol.
    """

    def on_discover_adapters(self, registry: Any):
        """Register the claude:// protocol."""
        print("      [Plugin] Registering Claude adapter via on_discover_adapters hook.")
        registry.register("claude", self.execute_claude_query)

    async def execute_claude_query(self, payload: Dict[str, Any], url: str = None) -> Dict[str, Any]:
        """
        Executes a query against the Anthropic Claude Messages API.
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
        if payload.get("force_error"):
            claude_payload["force_error"] = True

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=claude_payload, headers=headers, timeout=30) as response:
                    if response.status != 200:
                        err_text = await response.text()
                        return {
                            "status": "error",
                            "message": f"Claude API returned {response.status}: {err_text}",
                        }

                    data = await response.json()
                    # Claude response structure: content[0].text
                    output = data.get("content", [{}])[0].get("text", "")
                    return {
                        "status": "success",
                        "output": output,
                        "metadata": {"model": model, "framework": "claude"},
                    }
        except Exception as e:
            return {"status": "error", "message": str(e)}
