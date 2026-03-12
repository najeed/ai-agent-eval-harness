from typing import Dict, Any
from ..plugins import BaseEvalPlugin
from .. import config

class GrokAdapterPlugin(BaseEvalPlugin):
    """
    Ecosystem Adapter for xAI Grok.
    Registers the 'grok' protocol.
    """
    
    def on_discover_adapters(self, registry: Any):
        """Register the grok:// protocol."""
        print("      [Plugin] Registering Grok adapter via on_discover_adapters hook.")
        registry.register("grok", self.execute_grok_query)

    async def execute_grok_query(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calls the xAI Grok API.
        Standardizes the output to match the harness expectations.
        """
        api_key = payload.get("api_key") or os.getenv("XAI_API_KEY")
        if not api_key:
            return {"status": "error", "message": "xAI API key missing."}
            
        model = payload.get("model") or config.XAI_MODEL
        prompt = payload.get("task") or str(payload)
        
        async with aiohttp.ClientSession() as session:
            try:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                async with session.post(
                    config.XAI_BASE_URL + "/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": payload.get("temperature", 0.0)
                    },
                    timeout=aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        output = data["choices"][0]["message"]["content"]
                        return {
                            "status": "success",
                            "output": output,
                            "metadata": {"model": model, "framework": "grok"}
                        }
                    else:
                        return {
                            "status": "error",
                            "message": f"xAI API error: {response.status}"
                        }
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Grok request failed: {str(e)}"
                }
