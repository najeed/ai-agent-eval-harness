"""Opt-in interoperability certification for real adapter dependencies.

These tests deliberately use no transport or SDK mocks.  They are excluded
from routine CI because provider calls may be billable and framework remote
targets are deployment-owned.  Invoke them only in the release environment:

    AGENTV_ADAPTER_CERTIFICATION=1 pytest -m adapter_certification
"""

from __future__ import annotations

import os
import sys
from types import ModuleType
from typing import Any

import pytest

from eval_runner.adapters.claude import ClaudeAdapterPlugin
from eval_runner.adapters.gemini import GeminiAdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
from eval_runner.adapters.ollama import OllamaAdapterPlugin
from eval_runner.adapters.openai import OpenAIAdapterPlugin

_CERTIFICATION_ENV = "AGENTV_ADAPTER_CERTIFICATION"


@pytest.fixture
def adapter_certification_enabled() -> None:
    """Require an explicit release-environment opt-in before contacting a target."""
    if os.getenv(_CERTIFICATION_ENV, "").strip().lower() not in {"1", "true", "yes", "on"}:
        pytest.skip(f"{_CERTIFICATION_ENV}=1 is required for adapter certification.")


def _require_environment(*names: str) -> dict[str, str]:
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        pytest.skip("Adapter certification configuration is missing: " + ", ".join(missing))
    return {name: os.environ[name] for name in names}


def _assert_provider_success(result: dict[str, Any]) -> None:
    assert result["status"] == "success", result
    assert result["action"] != "error", result
    assert result.get("output") is not None or result.get("content") is not None, result


@pytest.mark.adapter_certification
@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "key_name", "model_name"),
    [
        ("openai", "OPENAI_API_KEY", "OPENAI_MODEL"),
        ("claude", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"),
        ("gemini", "GOOGLE_API_KEY", "GEMINI_MODEL"),
        ("grok", "XAI_API_KEY", "XAI_MODEL"),
    ],
)
async def test_real_provider_streaming_history_interoperability(
    adapter_certification_enabled: None,
    provider: str,
    key_name: str,
    model_name: str,
) -> None:
    """Prove a pinned provider accepts history and its native streaming protocol."""
    environment = _require_environment(key_name, model_name)
    payload: dict[str, Any] = {
        "api_key": environment[key_name],
        "model": environment[model_name],
        "task_description": "Reply with the single word CERTIFIED.",
        "history": [{"role": "user", "content": "This is a release interoperability check."}],
        "stream": True,
        "timeout": 45,
    }

    if provider == "openai":
        payload["api_mode"] = "responses"
        result = await OpenAIAdapterPlugin().execute_openai_query(payload)
    elif provider == "claude":
        result = await ClaudeAdapterPlugin().execute_claude_query(payload)
    elif provider == "gemini":
        payload["api_mode"] = "interactions"
        result = await GeminiAdapterPlugin().execute_gemini_query(payload)
    else:
        payload["api_mode"] = "responses"
        result = await GrokAdapterPlugin().execute_grok_query(payload)

    _assert_provider_success(result)


@pytest.mark.adapter_certification
@pytest.mark.live
@pytest.mark.asyncio
async def test_real_ollama_streaming_history_interoperability(
    adapter_certification_enabled: None,
) -> None:
    """Prove the pinned local Ollama server accepts NDJSON streaming and history."""
    environment = _require_environment("OLLAMA_API_URL", "OLLAMA_MODEL")
    result = await OllamaAdapterPlugin().execute_ollama_query(
        {
            "url": environment["OLLAMA_API_URL"],
            "model": environment["OLLAMA_MODEL"],
            "task_description": "Reply with the single word CERTIFIED.",
            "history": [{"role": "user", "content": "This is a local release check."}],
            "stream": True,
            "timeout": 45,
        }
    )
    _assert_provider_success(result)


@pytest.mark.adapter_certification
@pytest.mark.asyncio
async def test_real_langchain_runnable_interoperability(
    adapter_certification_enabled: None,
) -> None:
    """Execute an installed LangChain Runnable without replacing its execution API."""
    pytest.importorskip("langchain_core")
    from langchain_core.runnables import RunnableLambda

    runnable = RunnableLambda(lambda value: {"answer": value["message"], "action": "final_answer"})
    result = await LangChainAdapterPlugin().execute_langchain_query(
        {"input": {"message": "CERTIFIED"}, "metadata": {"runnable": runnable}}
    )

    assert result["status"] == "success", result
    assert result["output"]["answer"] == "CERTIFIED"


@pytest.mark.adapter_certification
@pytest.mark.asyncio
async def test_real_langgraph_compiled_graph_interoperability(
    adapter_certification_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execute an installed, compiled LangGraph graph through the local path."""
    pytest.importorskip("langgraph")
    from langgraph.graph import END, StateGraph

    workflow = StateGraph(dict)
    workflow.add_node("respond", lambda state: {"answer": state["message"]})
    workflow.set_entry_point("respond")
    workflow.add_edge("respond", END)

    module = ModuleType("adapter_certification_graph")
    module.graph = workflow.compile()
    monkeypatch.setitem(sys.modules, module.__name__, module)

    result = await LangGraphAdapterPlugin().execute_langgraph_node(
        {
            "input": {"message": "CERTIFIED"},
            "metadata": {"graph_path": f"{module.__name__}:graph"},
        }
    )

    assert result["status"] == "success", result
    assert result["output"]["answer"] == "CERTIFIED"
