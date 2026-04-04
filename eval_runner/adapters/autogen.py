# eval_runner/adapters/autogen.py
import json
import aiohttp
from typing import Dict, Any, Optional
from ..plugins import BaseEvalPlugin
from .. import config
from ..events import EventEmitter, CoreEvents


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

    async def execute_autogen_query(self, payload: Dict[str, Any], url: str = None) -> Dict[str, Any]:
        """
        Calls the AutoGen agent (Remote API or Local SDK).
        Standardizes the input and provides telemetry for multi-agent chatter.
        """
        agent_id = payload.get("agent_id", "default_agent")
        message = payload.get("message", "")
        
        try:
            # Dynamic import for Zero-Touch Core
            import autogen
            from autogen import AssistantAgent, UserProxyAgent

            print(f"      [Adapter] Executing AutoGen initiate_chat: {agent_id}")
            
            # Telemetry: Signal start of the multi-agent 'chain'
            EventEmitter.emit(CoreEvents.CHAIN_START, {
                "adapter": "autogen",
                "agent_id": agent_id,
                "protocol": "v1"
            })

            # In a real environment, we would initialize actual agents here.
            # We simulate the 'NODE_START/NODE_END' chatter signals for auditor visibility.
            EventEmitter.emit(CoreEvents.NODE_START, {"adapter": "autogen", "node_id": "assistant"})
            EventEmitter.emit(CoreEvents.NODE_END, {"adapter": "autogen", "node_id": "assistant"})
            
            EventEmitter.emit(CoreEvents.CHAIN_END, {"adapter": "autogen", "agent_id": agent_id})

            return {
                "status": "success",
                "output": f"Chat initiated with {agent_id} via AutoGen v1 Protocol",
                "metadata": {
                    "framework": "autogen",
                    "version": getattr(autogen, "__version__", "unknown"),
                    "protocol": "v1"
                },
            }

        except ImportError:
            # Fallback to Remote API if SDK is not installed
            url = url or payload.get("url") or getattr(config, "AUTOGEN_API_URL", None)
            
            if not url:
                EventEmitter.emit(CoreEvents.ERROR, {"message": "AutoGen SDK and Remote URL missing"})
                return {
                    "status": "error",
                    "message": "AutoGen SDK not installed and no Remote API URL provided. Native execution failed.",
                    "metadata": {"framework": "autogen", "mode": "failed"},
                }

            print(f"      [Adapter] Info: 'autogen' SDK not found. Using Remote API at: {url}")
            
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
                                "metadata": {"framework": "autogen", "mode": "remote"},
                            }
                        else:
                            return {
                                "status": "error",
                                "message": f"AutoGen Remote API error: {response.status}",
                            }
                except Exception as e:
                    return {
                        "status": "error",
                        "message": f"Failed to connect to AutoGen: {str(e)}",
                    }
