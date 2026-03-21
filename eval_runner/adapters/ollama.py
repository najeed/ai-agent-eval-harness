# eval_runner/adapters/ollama.py
import aiohttp
from typing import Any, Dict
from ..plugins import BaseEvalPlugin


class OllamaAdapterPlugin(BaseEvalPlugin):
    """
    Ecosystem Adapter for Ollama (Local LLM Server).
    Registers the 'ollama' protocol to allow direct communication with Ollama agents.
    """

    def on_discover_adapters(self, registry: Any):
        """Register the ollama:// protocol."""
        print("      [Plugin] Registering Ollama adapter via on_discover_adapters hook.")
        registry.register("ollama", self.execute_ollama_query)

    async def execute_ollama_query(self, payload: Dict[str, Any], url: str = None) -> Dict[str, Any]:
        """
        Executes a query against a local Ollama instance.
        Expects payload to contain 'model' and 'task' (or 'messages').
        """
        base_url = url or payload.get("ollama_url") or "http://localhost:11434/api/chat"
        model = payload.get("model", "llama3")

        # Translate harness task into Ollama chat format
        messages = payload.get("messages", [])
        if not messages and "task" in payload:
            messages = [{"role": "user", "content": payload["task"]}]

        ollama_payload = {"model": model, "messages": messages, "stream": False}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(base_url, json=ollama_payload, timeout=30) as response:
                    if response.status != 200:
                        return {
                            "status": "error",
                            "message": f"Ollama returned {response.status}",
                        }

                    data = await response.json()
                    return {
                        "status": "success",
                        "output": data.get("message", {}).get("content", ""),
                        "metadata": {"model": model, "framework": "ollama"},
                    }
        except Exception as e:
            return {"status": "error", "message": str(e)}
