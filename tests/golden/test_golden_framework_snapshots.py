"""
tests/golden/test_golden_framework_snapshots.py
Golden Verification Corpus: Framework Contract Snapshots
(LangGraph, AutoGen/AG2, CrewAI, OpenAI, Claude, Gemini)
"""

import pytest

from eval_runner.engine import AgentAdapterRegistry


def test_golden_framework_adapter_registration_and_taxonomy():
    AgentAdapterRegistry.reset()
    AgentAdapterRegistry._discover()

    # Verify authoritative taxonomy mappings
    assert AgentAdapterRegistry.ADAPTER_TAXONOMY["langgraph"] == "frameworks"
    assert AgentAdapterRegistry.ADAPTER_TAXONOMY["ag2"] == "frameworks"
    assert AgentAdapterRegistry.ADAPTER_TAXONOMY["crewai"] == "frameworks"
    assert AgentAdapterRegistry.ADAPTER_TAXONOMY["openai"] == "providers"
    assert AgentAdapterRegistry.ADAPTER_TAXONOMY["claude"] == "providers"
    assert AgentAdapterRegistry.ADAPTER_TAXONOMY["gemini"] == "providers"


@pytest.mark.asyncio
async def test_golden_framework_adapter_mock_dispatches():
    # Discover baseline first
    AgentAdapterRegistry.reset()
    AgentAdapterRegistry._discover()

    # Register deterministic mock handlers for the standard ecosystem
    called = {}

    async def mock_langgraph(payload, endpoint=None):
        called["langgraph"] = payload
        return {"action": "langgraph_step_executed", "result": "state_updated"}

    async def mock_ag2(payload, endpoint=None):
        called["ag2"] = payload
        return {"action": "ag2_speaker_turn", "result": "consensus_reached"}

    async def mock_crewai(payload, endpoint=None):
        called["crewai"] = payload
        return {"action": "crewai_task_complete", "result": "delegation_finished"}

    async def mock_openai(payload, endpoint=None):
        called["openai"] = payload
        return {"action": "openai_completion", "result": "response_generated"}

    async def mock_claude(payload, endpoint=None):
        called["claude"] = payload
        return {"action": "claude_message", "result": "response_generated"}

    async def mock_gemini(payload, endpoint=None):
        called["gemini"] = payload
        return {"action": "gemini_content", "result": "response_generated"}

    AgentAdapterRegistry.register("langgraph", mock_langgraph, allow_override=True)
    AgentAdapterRegistry.register("ag2", mock_ag2, allow_override=True)
    AgentAdapterRegistry.register("crewai", mock_crewai, allow_override=True)
    AgentAdapterRegistry.register("openai", mock_openai, allow_override=True)
    AgentAdapterRegistry.register("claude", mock_claude, allow_override=True)
    AgentAdapterRegistry.register("gemini", mock_gemini, allow_override=True)

    # Test wire contracts for all 6 target frameworks/providers
    for proto in ["langgraph", "ag2", "crewai", "openai", "claude", "gemini"]:
        res = await AgentAdapterRegistry.call_agent(
            protocol=proto,
            endpoint="http://localhost:8000",
            message=f"Execute task for {proto}",
            history=[],
        )
        assert res is not None
        assert "action" in res
        assert called[proto]["task_description"] == f"Execute task for {proto}"
