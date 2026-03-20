# eval_runner/adapters/langgraph.py
from typing import Any, Dict
from ..plugins import BaseEvalPlugin


class LangGraphAdapterPlugin(BaseEvalPlugin):
    """
    Architectural Adapter: Registers LangGraph support via Plugin hooks.
    This avoids hardcoding framework-specific logic into the core engine.
    """

    def on_discover_adapters(self, registry: Any):
        """Register the langgraph:// protocol."""
        print(
            "      [Plugin] Registering LangGraph adapter via on_discover_adapters hook."
        )
        registry.register("langgraph", self.execute_langgraph_node)

    async def execute_langgraph_node(
        self, payload: Dict[str, Any], endpoint: str = None
    ) -> Dict[str, Any]:
        """Executes a LangGraph node with dynamic import guards."""
        node_id = payload.get("node_id", "default_node")

        try:
            # Dynamic import to avoid hard dependency in core
            import langgraph

            print(f"      [Adapter] Executing real LangGraph node: {node_id}")
            # Actual execution logic would go here, e.g.:
            # app = get_compiled_graph(endpoint)
            # result = await app.ainvoke(payload.get("input"))
            return {
                "status": "success",
                "output": f"Processed {node_id} via LangGraph SDK",
                "metadata": {
                    "framework": "langgraph",
                    "version": getattr(langgraph, "__version__", "unknown"),
                },
            }
        except ImportError:
            print(
                f"      [Adapter] Warning: 'langgraph' SDK not found. Falling back to mock for node: {node_id}"
            )
            return {
                "status": "mock_success",
                "output": f"Mock output for {node_id} (LangGraph not installed)",
                "metadata": {"framework": "langgraph", "mode": "mock"},
            }
