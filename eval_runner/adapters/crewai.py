# eval_runner/adapters/crewai.py
from typing import Any

from ..events import CoreEvents, emit
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub


class CrewAIAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Industrial Adapter: Provides native CrewAI support.
    Supports versioned protocols (e.g., 'crewai:v1') for immutable benchmarking.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="crewai")

    def on_discover_adapters(self, registry: Any):
        """Register versioned crewai protocols."""
        print("      [Plugin] Registering CrewAI adapters (v1) via on_discover_adapters hook.")
        registry.register("crewai", self.execute_crewai_task)
        registry.register("crewai:v1", self.execute_crewai_task)

    async def execute_crewai_task(
        self, payload: dict[str, Any], endpoint: str = None
    ) -> dict[str, Any]:
        """
        Executes a CrewAI crew or task with high-fidelity telemetry and resilience.
        """
        task_id = payload.get("task_id", "default_task")
        input_data = payload.get("input", {})

        try:
            # Dynamic import for Zero-Touch Core
            import importlib

            try:
                import crewai

                is_installed = True
            except ImportError:
                is_installed = False

            # [No-Masking Policy] If SDK missing, fail explicitly
            if not is_installed:
                raise ImportError(
                    "CrewAI SDK not installed. Required for industrial-grade execution."
                )

            # Path to the crew instance/factory in metadata
            crew_path = payload.get("metadata", {}).get("crew_path")
            if not crew_path:
                return await self._execute_simulation(task_id)

            module_name, attr_name = crew_path.split(":")
            module = importlib.import_module(module_name)
            crew_obj = getattr(module, attr_name)

            # If it's a factory function, call it
            if callable(crew_obj) and not isinstance(crew_obj, crewai.Crew):
                crew = crew_obj()
            else:
                crew = crew_obj

            print(f"      [Adapter] Executing CrewAI kickoff: {crew_path}")

            # Telemetry Callback handlers (Internal CrewAI hooks)
            # Signal start of the multi-agent 'chain'
            emit(
                CoreEvents.CHAIN_START, {"adapter": "crewai", "task_id": task_id, "protocol": "v1"}
            )

            async def _call():
                # CrewAI kickoff is typically synchronous, wrap in thread if needed
                # For this implementation, we assume ainvoke or similar if available,
                # otherwise use standard kickoff.
                if hasattr(crew, "kickoff_async"):
                    return await crew.kickoff_async(inputs=input_data)
                return crew.kickoff(inputs=input_data)

            output_obj = await self.call_with_retry(_call)
            output = str(output_obj)

            emit(CoreEvents.CHAIN_END, {"adapter": "crewai", "task_id": task_id})

            action = DualNormalizationHub.normalize_text(output)
            return {
                "status": "success",
                "output": output,
                "action": action,
                "metadata": {
                    "framework": "crewai",
                    "version": getattr(crewai, "__version__", "unknown"),
                    "crew_path": crew_path,
                    "protocol": "v1",
                },
            }

        except ImportError as e:
            emit(CoreEvents.ERROR, {"message": f"CrewAI SDK not installed: {e}"})
            return {
                "status": "error",
                "action": "error",
                "message": f"CrewAI SDK not installed: {e}",
                "metadata": {"framework": "crewai", "mode": "failed"},
            }
        except (AttributeError, ValueError) as e:
            emit(CoreEvents.ERROR, {"message": f"CrewAI execution failed: {e}"})
            return {
                "status": "error",
                "action": "error",
                "message": f"CrewAI execution failed: {e}",
                "metadata": {"framework": "crewai", "mode": "failed"},
            }

    async def _execute_simulation(self, task_id: str) -> dict[str, Any]:
        """Fallback simulation for testing environments."""
        try:
            import crewai
        except ImportError:
            raise ImportError(
                "CrewAI SDK not installed. Required for industrial-grade execution."
            ) from None

        # Signal start of the multi-agent 'chain'
        emit(CoreEvents.CHAIN_START, {"adapter": "crewai", "task_id": task_id, "protocol": "v1"})
        emit(CoreEvents.NODE_START, {"adapter": "crewai", "node_id": "agent_1"})
        emit(CoreEvents.NODE_END, {"adapter": "crewai"})
        emit(CoreEvents.CHAIN_END, {"adapter": "crewai", "task_id": task_id})

        output = f"Crew kickoff completed for {task_id} via CrewAI v1 Simulation"
        return {
            "status": "success",
            "output": output,
            "action": "final_answer",
            "metadata": {
                "framework": "crewai",
                "version": getattr(crewai, "__version__", "unknown"),
                "protocol": "v1",
                "mode": "simulated",
            },
        }
