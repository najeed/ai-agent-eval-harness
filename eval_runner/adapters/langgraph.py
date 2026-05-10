# eval_runner/adapters/langgraph.py
from typing import Any

from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import AESCallbackHandler, BaseAdapter, DualNormalizationHub


class LangGraphAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Industrial Adapter: Provides native LangGraph support with high-fidelity telemetry.
    Supports versioned protocols (e.g., 'langgraph:v1') for immutable benchmarking.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="langgraph")

    def on_discover_adapters(self, registry: Any):
        """Register versioned langgraph protocols."""
        print("      [Plugin] Registering LangGraph adapters (v2) via on_discover_adapters hook.")
        registry.register("langgraph", self.execute_langgraph_node)
        registry.register("langgraph:v2", self.execute_langgraph_node)

    async def execute_langgraph_node(
        self, payload: dict[str, Any], endpoint: str = None
    ) -> dict[str, Any]:
        """
        Executes a LangGraph node or graph with standardized ainvoke and telemetry.
        """
        node_id = payload.get("node_id", "default_node")
        input_data = payload.get("input", {})
        config_data = payload.get("config", {})

        # Path to the compiled graph in metadata
        graph_path = payload.get("metadata", {}).get("graph_path")

        try:
            # Check for real SDK
            import importlib

            try:
                import langgraph

                version = getattr(langgraph, "__version__", "unknown")
                is_installed = True
            except ImportError:
                version = "unknown"
                is_installed = False

            # [No-Masking Policy] If SDK missing, fail explicitly (including simulations)
            if not is_installed:
                raise ImportError(
                    "LangGraph SDK not installed. Required for industrial-grade execution."
                )

            if not graph_path:
                return await self._execute_simulation(node_id, input_data)

            module_name, attr_name = graph_path.split(":")
            module = importlib.import_module(module_name)
            app = getattr(module, attr_name)

            print(f"      [Adapter] Executing LangGraph ainvoke: {graph_path}")

            # Use common high-fidelity telemetry handler
            handler = AESCallbackHandler(adapter_name="langgraph", identifier=node_id)

            # Execute with callbacks for telemetry
            # Wrap in call_with_retry if it's a remote graph or if we want resilience
            async def _call():
                return await app.ainvoke(input_data, config={"callbacks": [handler], **config_data})

            output = await self.call_with_retry(_call)

            # Normalize output
            if isinstance(output, dict):
                action = DualNormalizationHub.normalize(output, 200)
            else:
                action = DualNormalizationHub.normalize_text(str(output))

            return {
                "status": "success",
                "output": output,
                "action": action,
                "metadata": {
                    "framework": "langgraph",
                    "version": version,
                    "graph_path": graph_path,
                    "protocol": "v2",
                },
            }

        except ImportError as e:
            emit(CoreEvents.ERROR, {"message": f"LangGraph SDK not installed: {e}"})
            return {
                "status": "error",
                "action": "error",
                "message": f"LangGraph SDK not installed: {e}",
                "metadata": {"framework": "langgraph", "mode": "failed"},
            }
        except (AttributeError, ValueError) as e:
            emit(CoreEvents.ERROR, {"message": f"LangGraph execution failed: {e}"})
            return {
                "status": "error",
                "action": "error",
                "message": f"LangGraph execution failed: {e}",
                "metadata": {"framework": "langgraph", "mode": "failed"},
            }

    async def _execute_simulation(self, node_id: str, input_data: Any) -> dict[str, Any]:
        """Fallback simulation for testing environments."""
        try:
            import langgraph

            _ = langgraph
        except ImportError:
            raise ImportError(
                "LangGraph SDK not installed. Required for industrial-grade execution."
            ) from None

        handler = AESCallbackHandler(adapter_name="langgraph", identifier=node_id)
        handler.on_chain_start({}, input_data)
        handler.on_node_start({"id": [node_id]}, input_data)
        handler.on_node_end({"output": "simulated"})
        handler.on_chain_end({"output": "simulated"})

        output = f"Processed {node_id} via LangGraph v2 Simulation"
        return {
            "status": "success",
            "output": output,
            "action": "final_answer",
            "metadata": {
                "framework": "langgraph",
                "version": "simulated",
                "protocol": "v2",
                "mode": "simulated",
            },
        }
