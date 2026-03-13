# eval_runner/adapters/crewai.py
from typing import Any, Dict
from ..plugins import BaseEvalPlugin


class CrewAIAdapterPlugin(BaseEvalPlugin):
    """
    Architectural Adapter: Registers CrewAI support via Plugin hooks.
    Ensures the core engine remains framework-agnostic.
    """
    
    def on_discover_adapters(self, registry: Any):
        """Register the crewai:// protocol."""
        print("      [Plugin] Registering CrewAI adapter via on_discover_adapters hook.")
        registry.register("crewai", self.execute_crewai_task)

    async def execute_crewai_task(self, payload: Dict[str, Any], endpoint: str = None) -> Dict[str, Any]:
        """Mock execution of a CrewAI agent task."""
        task_id = payload.get("task_id", "default_task")
        print(f"      [Adapter] Executing CrewAI task: {task_id}")
        return {
            "status": "success",
            "output": f"Completed CrewAI task {task_id}",
            "metadata": {"framework": "crewai"}
        }
