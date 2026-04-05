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
        Executes a query against the Google Gemini API using the modern google-genai SDK.
        """
        from google import genai
        from google.genai import types

        api_key = payload.get("api_key") or config.GOOGLE_API_KEY
        model = payload.get("model", config.GEMINI_MODEL)
        
        # Check if Vertex AI is requested via base_url or metadata
        vertexai = "vertex" in (url or "").lower() or payload.get("metadata", {}).get("vertexai", False)
        
        client = genai.Client(api_key=api_key, vertexai=vertexai)

        prompt = payload.get("task_description") or ""
        contents = []

        if "messages" in payload:
            # SDK Content conversion
            for m in payload["messages"]:
                contents.append(
                    types.Content(
                        role="user" if m["role"] == "user" else "model",
                        parts=[types.Part(text=m["content"])]
                    )
                )
        else:
            contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]

        try:
            print(f"      [Adapter] Executing Gemini SDK generate_content: {model}")
            response = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=payload.get("temperature", 0.7),
                    top_p=payload.get("top_p", 0.95),
                    max_output_tokens=payload.get("max_tokens", 2048),
                )
            )

            if not response or not response.text:
                return {
                    "status": "error",
                    "message": f"Empty or invalid response from Gemini SDK: {response}",
                }

            return {
                "status": "success",
                "output": response.text.strip(),
                "metadata": {
                    "model": model, 
                    "framework": "gemini", 
                    "usage": response.usage_metadata.to_json() if response.usage_metadata else {}
                },
            }
        except Exception as e:
            return {"status": "error", "message": f"Gemini SDK Error: {str(e)}"}
