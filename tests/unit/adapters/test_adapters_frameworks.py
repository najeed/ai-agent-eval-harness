from unittest.mock import MagicMock, patch

import pytest

from eval_runner.adapters.ag2 import AG2AdapterPlugin
from eval_runner.adapters.crewai import CrewAIAdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.adapters.langgraph import (
    LangGraphAdapterPlugin,
    _LangGraphTelemetryHandler,
    _stream_chunk_summary,
    _summarize_state_field,
)


@pytest.mark.asyncio
async def test_crewai_adapter_requires_native_crew_binding():
    plugin = CrewAIAdapterPlugin()
    with patch.dict("sys.modules", {"crewai": MagicMock(__version__="1.0")}):
        res = await plugin.execute_crewai_task({"task_id": "test_crew"})
        assert res["status"] == "error"
        assert res["action"] == "error"


@pytest.mark.asyncio
async def test_langgraph_adapter_requires_execution_target():
    plugin = LangGraphAdapterPlugin()
    with patch.dict("sys.modules", {"langgraph": MagicMock(__version__="2.0")}):
        res = await plugin.execute_langgraph_node({"node_id": "test_node"})
        assert res["status"] == "error"
        assert res["action"] == "error"


@pytest.mark.asyncio
async def test_framework_adapters_error_reporting():
    # LangChain fails closed when no local or remote target is configured.
    plugin = LangChainAdapterPlugin()
    res = await plugin.execute_langchain_query({})
    assert res["status"] == "error"
    assert res["action"] == "error"

    # AG2 missing URL -> should reach error (no SDK, no config URL)
    plugin = AG2AdapterPlugin()
    with (
        patch("eval_runner.adapters.ag2.config") as mock_cfg,
        patch.dict("sys.modules", {"ag2": None}),
    ):
        mock_cfg.AG2_API_URL = None
        with pytest.raises(ValueError, match="requires a non-empty task/message"):
            await plugin.execute_ag2_query({})


def test_langgraph_telemetry_helpers_bound_untrusted_values():
    summary = _stream_chunk_summary("updates", {"name": "n", "node": "node"}, 1)
    assert summary["name"] == "n"
    assert summary["node"] == "node"

    summary = _stream_chunk_summary("updates", type("Chunk", (), {"id": "chunk-1"})(), 2)
    assert summary["id"] == "chunk-1"

    state = _summarize_state_field({"first": 1, "second": 2})
    assert state["keys"] == ["first", "second"]

    handler = _LangGraphTelemetryHandler("langgraph", "node")
    with patch("eval_runner.adapters.langgraph.emit") as mock_emit:
        handler.on_chain_error(ValueError("bad graph"))
        handler.on_tool_start({"name": "search"}, "input")
        handler.on_node_start({"name": "planner"}, {})

    assert mock_emit.call_count == 3


def test_ag2_a2a_card_signature_verifier_is_forwarded():
    adapter = AG2AdapterPlugin()
    verifier = object()
    a2a_config = MagicMock()
    ag2 = MagicMock()

    adapter._build_remote_agent(
        ag2,
        a2a_config,
        {"card_signature_verifier": verifier},
        {},
        "https://agent.example/agent-card.json",
        "remote-agent",
    )

    assert a2a_config.call_args.kwargs["card_signature_verifier"] is verifier
