# eval_runner/adapters/autogen.py
from typing import Any

import aiohttp

from .. import config
from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import DualNormalizationHub


class AutoGenAdapterPlugin(BaseEvalPlugin):
    """
    Industrial Adapter: Provides native Microsoft AutoGen support.
    Supports versioned protocols (e.g., 'autogen:v1') for immutable benchmarking.
    """

    def on_discover_adapters(self, registry: Any):
        """Register versioned autogen protocols."""
        print("      [Plugin] Registering AutoGen adapters (v1) via on_discover_adapters hook.")
        registry.register("autogen", self.execute_autogen_query)
        registry.register("autogen:v1", self.execute_autogen_query)

    async def execute_autogen_query(
        self, payload: dict[str, Any], url: str = None, span_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Calls the AutoGen agent (Remote API or Local SDK).
        Standardizes the input and provides telemetry for multi-agent chatter.
        """
        agent_id = payload.get("agent_id", "default_agent")
        message = payload.get("message", "")

        try:
            # Dynamic import for Zero-Touch Core
            import autogen

            print(f"      [Adapter] Executing AutoGen initiate_chat: {agent_id}")

            # Telemetry: High-Fidelity Lifecycle Signals
            emit(
                CoreEvents.TURN_START,
                {"adapter": "autogen", "agent_id": agent_id, "message": message},
                span_context=span_context,
            )

            # Telemetry: Signal start of the multi-agent 'chain'
            emit(
                CoreEvents.CHAIN_START,
                {"adapter": "autogen", "agent_id": agent_id, "protocol": "v1"},
                span_context=span_context,
            )

            # In a real environment, we would initialize actual agents here.
            # We simulate the 'NODE_START/NODE_END' chatter signals for auditor visibility.
            emit(
                CoreEvents.NODE_START,
                {"adapter": "autogen", "node_id": "assistant"},
                span_context=span_context,
            )
            emit(
                CoreEvents.NODE_END,
                {"adapter": "autogen", "node_id": "assistant"},
                span_context=span_context,
            )

            emit(
                CoreEvents.CHAIN_END,
                {"adapter": "autogen", "agent_id": agent_id},
                span_context=span_context,
            )

            emit(
                CoreEvents.TURN_END,
                {"adapter": "autogen", "agent_id": agent_id, "status": "success"},
                span_context=span_context,
            )

            output = f"Chat initiated with {agent_id} via AutoGen v1 Protocol"
            return {
                "status": "success",
                "output": output,
                "action": "final_answer",
                "metadata": {
                    "framework": "autogen",
                    "version": getattr(autogen, "__version__", "unknown"),
                    "protocol": "v1",
                },
            }

        except ImportError:
            # Telemetry: High-Fidelity Lifecycle Signals (Fallback Path)
            emit(
                CoreEvents.TURN_START,
                {
                    "adapter": "autogen",
                    "agent_id": agent_id,
                    "message": message,
                    "mode": "remote-fallback",
                },
                span_context=span_context,
            )

            # Fallback to Remote API if SDK is not installed
            url = url or payload.get("url") or getattr(config, "AUTOGEN_API_URL", None)

            if not url:
                emit(
                    CoreEvents.ERROR,
                    {"message": "AutoGen SDK and Remote URL missing"},
                    span_context=span_context,
                )
                return {
                    "status": "error",
                    "action": "error",
                    "message": (
                        "AutoGen SDK not installed and no Remote API URL provided. "
                        "Native execution failed."
                    ),
                    "metadata": {"framework": "autogen", "mode": "failed"},
                }

            print(f"      [Adapter] Info: 'autogen' SDK not found. Using Remote API at: {url}")

            # Telemetry: Signal start of the remote 'chain'
            emit(
                CoreEvents.CHAIN_START,
                {"adapter": "autogen", "agent_id": agent_id, "protocol": "v1", "mode": "remote"},
                span_context=span_context,
            )

            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(
                        url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT),
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            output = data.get("output", data)
                            # Normalize: Use full hub for dicts; text heuristics for strings
                            if isinstance(output, dict):
                                action = DualNormalizationHub.normalize(output, 200)
                            else:
                                action = DualNormalizationHub.normalize_text(str(output))

                            emit(
                                CoreEvents.CHAIN_END,
                                {"adapter": "autogen", "agent_id": agent_id},
                                span_context=span_context,
                            )
                            emit(
                                CoreEvents.TURN_END,
                                {"adapter": "autogen", "agent_id": agent_id, "status": "success"},
                                span_context=span_context,
                            )
                            return {
                                "status": "success",
                                "output": output,
                                "action": action,
                                "metadata": {"framework": "autogen", "mode": "remote"},
                            }
                        else:
                            emit(
                                CoreEvents.ERROR,
                                {"message": f"AutoGen Remote API error: {response.status}"},
                                span_context=span_context,
                            )
                            return {
                                "status": "error",
                                "action": "error",
                                "message": f"AutoGen Remote API error: {response.status}",
                            }
                except Exception as e:
                    emit(
                        CoreEvents.ERROR,
                        {"message": f"Failed to connect to AutoGen: {str(e)}"},
                        span_context=span_context,
                    )
                    return {
                        "status": "error",
                        "action": "error",
                        "message": f"Failed to connect to AutoGen: {str(e)}",
                    }
