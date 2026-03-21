import json
import aiohttp
from typing import Dict, Any
from ..plugins import BaseEvalPlugin
from .. import config


class AutoGenAdapterPlugin(BaseEvalPlugin):
    """
    Ecosystem Adapter for Microsoft AutoGen agents.
    Registers the 'autogen' protocol.
    """

    def on_discover_adapters(self, registry: Any):
        """Register the autogen:// protocol."""
        print("      [Plugin] Registering AutoGen adapter via on_discover_adapters hook.")
        registry.register("autogen", self.execute_autogen_query)

    async def execute_autogen_query(self, payload: Dict[str, Any], url: str = None) -> Dict[str, Any]:
        """
        Calls the AutoGen agent endpoint.
        Standardizes the input to AutoGen's expected format.
        """
        url = url or payload.get("url") or config.AUTOGEN_API_URL

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT),
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "status": "success",
                            "output": data.get("output", data),
                            "metadata": {"framework": "autogen"},
                        }
                    else:
                        error_text = await response.text()
                        return {
                            "status": "error",
                            "message": f"AutoGen adapter error: {response.status} - {error_text}",
                        }
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Failed to connect to AutoGen agent: {str(e)}",
                }
