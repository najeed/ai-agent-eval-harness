# eval_runner/adapters/langchain.py
import aiohttp
from typing import Any, Dict
from ..plugins import BaseEvalPlugin


class LangChainAdapterPlugin(BaseEvalPlugin):
    """
    Ecosystem Adapter for LangChain (specifically LangServe/RemoteRunnable).
    Registers the 'langchain' protocol.
    """

    def on_discover_adapters(self, registry: Any):
        """Register the langchain:// protocol."""
        print("      [Plugin] Registering LangChain adapter via on_discover_adapters hook.")
        registry.register("langchain", self.execute_langserve_query)

    async def execute_langserve_query(self, payload: Dict[str, Any], url: str = None) -> Dict[str, Any]:
        """
        Executes a query against a LangServe remote endpoint.
        Expects payload to contain 'url' and 'input'.
        """
        url = url or payload.get("url") or payload.get("base_url")
        if not url:
            return {
                "status": "error",
                "message": "Missing 'url' or 'base_url' in payload for langchain adapter",
            }

        # LangServe typically has /invoke endpoint
        if not url.endswith("/invoke"):
            url = url.rstrip("/") + "/invoke"

        langserve_input = {"input": payload.get("input") or payload.get("task_description") or {}}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=langserve_input, timeout=60) as response:
                    if response.status != 200:
                        return {
                            "status": "error",
                            "message": f"LangServe returned {response.status}",
                        }

                    data = await response.json()
                    # LangServe output is usually in 'output' field
                    return {
                        "status": "success",
                        "output": str(data.get("output", "")),
                        "metadata": {"framework": "langchain", "endpoint": url},
                    }
        except Exception as e:
            return {"status": "error", "message": str(e)}
