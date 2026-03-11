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

    async def execute_crewai_task(self, task_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Mock execution of a CrewAI agent task."""
        print(f"      [Adapter] Executing CrewAI task: {task_id}")
        return {
            "status": "success",
            "output": f"Completed CrewAI task {task_id}",
            "metadata": {"framework": "crewai"}
        }
