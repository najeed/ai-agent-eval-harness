import sys
from types import ModuleType
from unittest.mock import patch

import pytest

from eval_runner.adapters.crewai import CrewAIAdapterPlugin
from eval_runner.events import subscribe, unsubscribe


@pytest.mark.asyncio
async def test_crewai_adapter_real_integration():
    """Verify that the adapter works with real CrewAI components."""
    # This test requires the real crewai package
    pytest.importorskip("crewai")
    from crewai import Agent, Crew, Task

    # Setup a real crew with minimal components
    agent = Agent(
        role="Tester",
        goal="Test integration",
        backstory="I am a test agent",
        allow_delegation=False,
        verbose=True,
    )

    task = Task(description="Just return 'success'", agent=agent, expected_output="success")

    crew = Crew(agents=[agent], tasks=[task], verbose=True)

    # Register the crew in sys.modules
    mock_module = ModuleType("real_crews")
    mock_module.my_crew = crew
    sys.modules["real_crews"] = mock_module

    adapter = CrewAIAdapterPlugin()
    payload = {
        "task_id": "crew_integration_test",
        "metadata": {"crew_path": "real_crews:my_crew"},
    }

    events_captured = []

    def listener(event):
        events_captured.append(event.name)

    subscribe(listener)
    try:
        # We need to mock the actual execution of the crew to avoid needing an LLM
        # but we want to verify the adapter calls kickoff() correctly.
        with patch.object(Crew, "kickoff", return_value="real crew success"):
            result = await adapter.execute_crewai_task(payload)

            assert result["status"] == "success"
            assert "real crew success" in result["output"]
            # Verify telemetry via event bus subscription
            assert "chain_start" in events_captured
            assert "chain_end" in events_captured
    finally:
        unsubscribe(listener)
        del sys.modules["real_crews"]
