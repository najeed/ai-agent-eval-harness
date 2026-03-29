import aiohttp
import os
from typing import Any, Dict
from ..plugins import BaseEvalPlugin
from .. import config


class GeminiAdapterPlugin(BaseEvalPlugin):
    """
    Ecosystem Adapter for Google Gemini API.
    Registers the 'gemini' protocol.
    """

    def on_discover_adapters(self, registry: Any):
        """Register the gemini:// protocol."""
        print("      [Plugin] Registering Gemini adapter via on_discover_adapters hook.")
        registry.register("gemini", self.execute_gemini_query)

    async def execute_gemini_query(self, payload: Dict[str, Any], url: str = None) -> Dict[str, Any]:
        """
        Executes a query against the Google Gemini API.
        """
        api_key = payload.get("api_key") or config.GOOGLE_API_KEY
        model = payload.get("model", config.GEMINI_MODEL)
        # Google Generative AI endpoint
        url = url or f"{config.GEMINI_BASE_URL}/{model}:generateContent?key={api_key}"

        prompt = payload.get("task_description") or ""
        if "messages" in payload:
            # Simple translation of chat messages to Gemini parts
            contents = []
            for m in payload["messages"]:
                contents.append(
                    {
                        "role": "user" if m["role"] == "user" else "model",
                        "parts": [{"text": m["content"]}],
                    }
                )
        else:
            contents = [{"parts": [{"text": prompt}]}]

        gemini_payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": payload.get("temperature", 0.7),
                "topP": payload.get("top_p", 0.95),
                "maxOutputTokens": payload.get("max_tokens", 2048),
            },
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=gemini_payload, timeout=30) as response:
                    if response.status != 200:
                        err_text = await response.text()
                        return {
                            "status": "error",
                            "message": f"Gemini API returned {response.status}: {err_text}",
                        }

                    data = await response.json()
                    # Gemini response structure: candidates[0].content.parts[0].text
                    output = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    return {
                        "status": "success",
                        "output": output,
                        "metadata": {"model": model, "framework": "gemini"},
                    }
        except Exception as e:
            return {"status": "error", "message": str(e)}
