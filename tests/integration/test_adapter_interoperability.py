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
from aiohttp import web

from eval_runner.adapters.ag2 import AG2AdapterPlugin
from eval_runner.adapters.claude import ClaudeAdapterPlugin
from eval_runner.adapters.crewai import CrewAIAdapterPlugin
from eval_runner.adapters.gemini import GeminiAdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
from eval_runner.adapters.ollama import OllamaAdapterPlugin
from eval_runner.adapters.openai import OpenAIAdapterPlugin
from eval_runner.adapters.openapi import OpenAPIAdapterPlugin

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
@pytest.mark.parametrize(
    ("provider", "key_name", "model_name"),
    [
        ("openai", "OPENAI_API_KEY", "OPENAI_MODEL"),
        ("claude", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"),
        ("gemini", "GOOGLE_API_KEY", "GEMINI_MODEL"),
        ("grok", "XAI_API_KEY", "XAI_MODEL"),
    ],
)
async def test_real_provider_native_tool_interoperability(
    adapter_certification_enabled: None,
    provider: str,
    key_name: str,
    model_name: str,
) -> None:
    """Certify provider-native function/tool-call normalization, not just text transport."""
    environment = _require_environment(key_name, model_name)
    function = {
        "name": "release_check",
        "description": "Return the supplied certification value.",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    }
    payload: dict[str, Any] = {
        "api_key": environment[key_name],
        "model": environment[model_name],
        "task_description": "Call release_check with value CERTIFIED. Do not answer with text.",
        "timeout": 45,
    }

    if provider == "openai":
        payload.update(
            {
                "api_mode": "responses",
                "tools": [{"type": "function", **function}],
                "tool_choice": {"type": "function", "name": "release_check"},
            }
        )
        result = await OpenAIAdapterPlugin().execute_openai_query(payload)
    elif provider == "claude":
        payload.update(
            {
                "tools": [
                    {
                        "name": function["name"],
                        "description": function["description"],
                        "input_schema": function["parameters"],
                    }
                ],
                "tool_choice": {"type": "tool", "name": "release_check"},
            }
        )
        result = await ClaudeAdapterPlugin().execute_claude_query(payload)
    elif provider == "gemini":
        payload.update(
            {"api_mode": "interactions", "tools": [{"function_declarations": [function]}]}
        )
        result = await GeminiAdapterPlugin().execute_gemini_query(payload)
    else:
        payload.update(
            {
                "api_mode": "responses",
                "tools": [{"type": "function", **function}],
                "tool_choice": {"type": "function", "name": "release_check"},
            }
        )
        result = await GrokAdapterPlugin().execute_grok_query(payload)

    assert result["status"] == "success", result
    assert result["action"] in {"call_tool", "call_multiple_tools"}, result


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
async def test_real_provider_structured_output_interoperability(
    adapter_certification_enabled: None,
    provider: str,
    key_name: str,
    model_name: str,
) -> None:
    """Certify the provider-specific structured-output request path."""
    environment = _require_environment(key_name, model_name)
    schema = {
        "type": "object",
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
        "additionalProperties": False,
    }
    payload: dict[str, Any] = {
        "api_key": environment[key_name],
        "model": environment[model_name],
        "task_description": 'Return exactly {"result":"CERTIFIED"}.',
        "response_json_schema": schema,
        "timeout": 45,
    }
    if provider == "openai":
        payload.update(
            {
                "api_mode": "responses",
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "release_check", "schema": schema, "strict": True},
                },
            }
        )
        result = await OpenAIAdapterPlugin().execute_openai_query(payload)
    elif provider == "claude":
        payload["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
        result = await ClaudeAdapterPlugin().execute_claude_query(payload)
    elif provider == "gemini":
        payload.update(
            {
                "api_mode": "generate_content",
                "response_mime_type": "application/json",
                "response_schema": schema,
            }
        )
        result = await GeminiAdapterPlugin().execute_gemini_query(payload)
    else:
        payload.update(
            {
                "api_mode": "responses",
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "release_check", "schema": schema, "strict": True},
                },
            }
        )
        result = await GrokAdapterPlugin().execute_grok_query(payload)
    _assert_provider_success(result)
    assert "CERTIFIED" in str(result.get("output") or result.get("content")), result


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

    def reference_tool(value: str) -> str:
        return value.upper()

    def reference_agent(value: dict[str, Any]) -> dict[str, Any]:
        tool_result = reference_tool(value["message"])
        return {
            "answer": tool_result,
            "tool_calls": [{"name": "reference_tool", "input": value["message"]}],
            "state_mutated": True,
            "action": "final_answer",
        }

    runnable = RunnableLambda(reference_agent)
    result = await LangChainAdapterPlugin().execute_langchain_query(
        {"input": {"message": "CERTIFIED"}, "metadata": {"runnable": runnable}}
    )

    assert result["status"] == "success", result
    assert result["output"]["answer"] == "CERTIFIED"
    assert result["output"]["state_mutated"] is True


@pytest.mark.adapter_certification
@pytest.mark.live
@pytest.mark.asyncio
async def test_real_langserve_interoperability(adapter_certification_enabled: None) -> None:
    """Execute against a release-owned LangServe deployment without an HTTP substitute."""
    environment = _require_environment("LANGSERVE_CERTIFICATION_URL")
    result = await LangChainAdapterPlugin().execute_langchain_query(
        {"input": {"message": "CERTIFIED"}, "timeout": 45},
        endpoint=environment["LANGSERVE_CERTIFICATION_URL"],
    )
    _assert_provider_success(result)


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
    workflow.add_node(
        "tool",
        lambda state: {
            "tool_calls": [{"name": "reference_tool", "input": state["message"]}],
            "tool_result": state["message"].upper(),
        },
    )
    workflow.add_node(
        "respond",
        lambda state: {"answer": state["tool_result"], "state_mutated": True},
    )
    workflow.set_entry_point("tool")
    workflow.add_edge("tool", "respond")
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
    assert result["output"]["state_mutated"] is True


@pytest.mark.adapter_certification
@pytest.mark.live
@pytest.mark.asyncio
async def test_real_remote_langgraph_interoperability(
    adapter_certification_enabled: None,
) -> None:
    """Execute against a release-owned LangGraph Server RemoteGraph deployment."""
    environment = _require_environment(
        "LANGGRAPH_CERTIFICATION_URL",
        "LANGGRAPH_CERTIFICATION_ASSISTANT_ID",
    )
    result = await LangGraphAdapterPlugin().execute_langgraph_node(
        {
            "input": {"message": "CERTIFIED"},
            "assistant_id": environment["LANGGRAPH_CERTIFICATION_ASSISTANT_ID"],
            "timeout": 45,
        },
        endpoint=environment["LANGGRAPH_CERTIFICATION_URL"],
    )
    _assert_provider_success(result)


@pytest.mark.adapter_certification
@pytest.mark.live
@pytest.mark.asyncio
async def test_real_ag2_agent_interoperability(adapter_certification_enabled: None) -> None:
    """Execute a release-owned AG2 agent through its native async ask API."""
    environment = _require_environment("AG2_CERTIFICATION_AGENT_PATH")
    result = await AG2AdapterPlugin().execute_ag2_query(
        {
            "message": "Reply with the single word CERTIFIED.",
            "metadata": {"agent_path": environment["AG2_CERTIFICATION_AGENT_PATH"]},
            "timeout": 45,
        }
    )
    _assert_provider_success(result)


@pytest.mark.adapter_certification
@pytest.mark.live
@pytest.mark.asyncio
async def test_real_crewai_crew_interoperability(adapter_certification_enabled: None) -> None:
    """Execute a release-owned CrewAI Crew through native async kickoff."""
    environment = _require_environment("CREWAI_CERTIFICATION_CREW_PATH")
    result = await CrewAIAdapterPlugin().execute_crewai_task(
        {
            "task_description": "Reply with the single word CERTIFIED.",
            "metadata": {"crew_path": environment["CREWAI_CERTIFICATION_CREW_PATH"]},
            "timeout": 45,
        }
    )
    _assert_provider_success(result)


@pytest.mark.adapter_certification
@pytest.mark.asyncio
async def test_openapi_reference_service_interoperability(
    adapter_certification_enabled: None,
    aiohttp_server: Any,
) -> None:
    """Exercise discovery, bearer auth, request construction, 202 polling, and normalization."""
    observed: dict[str, Any] = {"polls": 0}
    app = web.Application()

    async def openapi_document(request: web.Request) -> web.Response:
        origin = f"{request.scheme}://{request.host}"
        return web.json_response(
            {
                "openapi": "3.1.0",
                "servers": [{"url": origin}],
                "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}},
                "paths": {
                    "/apply": {
                        "post": {
                            "operationId": "apply",
                            "security": [{"bearer": []}],
                            "requestBody": {
                                "content": {"application/json": {"schema": {"type": "object"}}}
                            },
                        }
                    }
                },
            }
        )

    async def apply(request: web.Request) -> web.Response:
        assert request.headers["Authorization"] == "Bearer certification-token"
        assert await request.json() == {"message": "CERTIFIED"}
        return web.json_response({}, status=202, headers={"Location": "/status/42"})

    async def status(request: web.Request) -> web.Response:
        observed["polls"] += 1
        return web.json_response({"status": "completed", "result": "CERTIFIED"})

    app.router.add_get("/openapi.json", openapi_document)
    app.router.add_post("/apply", apply)
    app.router.add_get("/status/42", status)
    server = await aiohttp_server(app)
    endpoint = str(server.make_url("/apply"))

    result = await OpenAPIAdapterPlugin().execute_openapi_query(
        {
            "spec_url": str(server.make_url("/openapi.json")),
            "operation_id": "apply",
            "input_payload": {"message": "CERTIFIED"},
            "metadata": {"auth": {"token": "certification-token"}},
        },
        endpoint=endpoint,
    )

    assert result["status"] == "success", result
    assert result["action"] == "final_answer", result
    assert observed["polls"] == 1
