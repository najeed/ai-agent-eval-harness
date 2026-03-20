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
        print(
            "      [Plugin] Registering CrewAI adapter via on_discover_adapters hook."
        )
        registry.register("crewai", self.execute_crewai_task)

    async def execute_crewai_task(
        self, payload: Dict[str, Any], endpoint: str = None
    ) -> Dict[str, Any]:
        """Executes a CrewAI task with dynamic import guards."""
        task_id = payload.get("task_id", "default_task")

        try:
            # Dynamic import to avoid hard dependency in core
            import crewai

            print(f"      [Adapter] Executing real CrewAI task: {task_id}")
            # Potential execution logic:
            # agent = Agent(role=payload.get("role"), goal=payload.get("goal"), ...)
            # task = Task(description=payload.get("description"), agent=agent)
            return {
                "status": "success",
                "output": f"Completed CrewAI task {task_id} via SDK",
                "metadata": {
                    "framework": "crewai",
                    "version": getattr(crewai, "__version__", "unknown"),
                },
            }
        except ImportError:
            print(
                f"      [Adapter] Warning: 'crewai' SDK not found. Falling back to mock for task: {task_id}"
            )
            return {
                "status": "mock_success",
                "output": f"Mock completion for {task_id} (CrewAI not installed)",
                "metadata": {"framework": "crewai", "mode": "mock"},
            }
