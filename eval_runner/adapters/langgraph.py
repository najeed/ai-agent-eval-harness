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
        print("      [Plugin] Registering LangGraph adapter via on_discover_adapters hook.")
        registry.register("langgraph", self.execute_langgraph_node)

    async def execute_langgraph_node(self, payload: Dict[str, Any], endpoint: str = None) -> Dict[str, Any]:
        """Mock execution of a LangGraph node."""
        node_id = payload.get("node_id", "default_node")
        print(f"      [Adapter] Executing LangGraph node: {node_id}")
        return {
            "status": "success",
            "output": f"Processed {node_id} via LangGraph Adapter",
            "metadata": {"framework": "langgraph"}
        }
