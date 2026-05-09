from typing import Any

from .. import config
from ..events import emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub


class GeminiAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Ecosystem Adapter for Google Gemini API.
    Registers the 'gemini' protocol.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="gemini")

    def on_discover_adapters(self, registry: Any):
        """Register the gemini:// protocol."""
        print("      [Plugin] Registering Gemini adapter via on_discover_adapters hook.")
        registry.register("gemini", self.execute_gemini_query)

    async def execute_gemini_query(
        self, payload: dict[str, Any], url: str = None
    ) -> dict[str, Any]:
        """
        Executes a query against the Google Gemini API using the modern google-genai SDK.
        """
        from google import genai
        from google.genai import types

        api_key = payload.get("api_key")
        model = payload.get("model", config.GEMINI_MODEL)

        # Check if Vertex AI is requested via base_url or metadata
        vertexai = "vertex" in (url or "").lower() or payload.get("metadata", {}).get(
            "vertexai", False
        )

        if not api_key and not vertexai:
            api_key = config.GOOGLE_API_KEY

        # SDK Client initialization
        # Note: Session pooling is managed internally by the SDK's transport.
        client = genai.Client(api_key=api_key, vertexai=vertexai)

        prompt = payload.get("task_description") or ""
        contents = []

        if "messages" in payload:
            for m in payload["messages"]:
                contents.append(
                    types.Content(
                        role="user" if m["role"] == "user" else "model",
                        parts=[types.Part(text=m["content"])],
                    )
                )
        else:
            contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]

        async def _call():
            print(f"      [Adapter] Executing Gemini SDK generate_content: {model}")
            return await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=payload.get("temperature", 0.7),
                    top_p=payload.get("top_p", 0.95),
                    max_output_tokens=payload.get("max_tokens", 2048),
                ),
            )

        try:
            response = await self.call_with_retry(_call)

            if not response or not response.text:
                return {
                    "status": "error",
                    "action": "error",
                    "message": f"Empty or invalid response from Gemini SDK: {response}",
                }

            output = response.text.strip()
            action = DualNormalizationHub.normalize_text(output)

            # [Industrial Telemetry]: Extract token usage
            usage = response.usage_metadata
            if usage:
                emit(
                    "metric_update",
                    {
                        "adapter": "gemini",
                        "tokens": usage.total_token_count,
                        "prompt_tokens": usage.prompt_token_count,
                        "completion_tokens": usage.candidates_token_count,
                    },
                )

            return {
                "status": "success",
                "output": output,
                "action": action,
                "metadata": {
                    "model": model,
                    "framework": "gemini",
                    "usage": usage.to_json() if usage else {},
                },
            }
        except Exception as e:
            return {"status": "error", "action": "error", "message": f"Gemini SDK Error: {str(e)}"}
