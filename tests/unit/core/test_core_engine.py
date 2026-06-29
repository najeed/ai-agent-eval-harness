"""
Consolidated Engine & Runner Test Suite for AgentV Evaluation Harness.
Verifies multi-turn execution, pass@k, consistency scoring, adapter discovery,
routing resolution (mappings, extensions, failover), and determinism (seeding).
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from eval_runner import analyzer, config, failure_corpus, loader, utils
from eval_runner.engine import AgentAdapterRegistry, run_evaluation
from eval_runner.routing import RoutingRegistry
from eval_runner.runner import DefaultRunner

# --- 1. Core Execution & Protocols ---


@pytest.mark.asyncio
async def test_engine_pass_at_k():
    """Verify engine runs k attempts and calculates pass@k."""
    scenario = {
        "aes_version": 1.4,
        "id": "test-k",
        "metadata": {"name": "test-k", "compliance_level": "Standard"},
        "workflow": {
            "nodes": [
                {
                    "id": "t1",
                    "task_description": "d",
                    "success_criteria": [{"metric": "generic_accuracy", "threshold": 0.5}],
                }
            ],
            "edges": [],
        },
    }
    attempt = 0

    async def mock_agent(*args):
        nonlocal attempt
        attempt += 1
        return {"action": "final_answer", "summary": "Success" if attempt == 1 else ""}

    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_agent):
        results = await run_evaluation(scenario, attempts=2)
        assert len(results) == 2


# --- 2. Adapter Registry & Routing ---


@pytest.mark.asyncio
async def test_adapter_and_routing(tmp_path, monkeypatch):
    AgentAdapterRegistry.reset()
    monkeypatch.chdir(tmp_path)

    # Setup Config Directory
    config_dir = tmp_path / ".aes" / "config"
    adapters_dir = config_dir / "adapters"
    routing_dir = config_dir / "routing"
    adapters_dir.mkdir(parents=True)
    routing_dir.mkdir(parents=True)

    # 1. Adapter Discovery
    (adapters_dir / "policy.json").write_text(
        json.dumps({"adapters": {"active_protocols": ["http"]}})
    )
    monkeypatch.setattr(config, "AES_CONFIG_DIR", config_dir)
    config.RegistryManager.reload()

    AgentAdapterRegistry._discover()
    assert "http" in AgentAdapterRegistry._adapters

    # 2. Routing Resolution
    (routing_dir / "manifest.json").write_text(
        json.dumps(
            {"routing": {"mappings": {"default": {"protocol": "http", "endpoint": "http://def"}}}}
        )
    )

    config.RegistryManager.reload()
    RoutingRegistry.reload()
    resolved = RoutingRegistry.resolve(["any"])
    assert resolved["endpoint"] == "http://def"


# --- 3. Determinism & Seeding ---


@pytest.mark.asyncio
async def test_incremental_seeding():
    """Verify Industrial Seeding Protocol: Seed = Base + (Attempt - 1)"""
    runner = DefaultRunner()
    scenario = {"id": "s1"}
    with patch("eval_runner.session.SessionManager") as MockSession:
        MockSession.return_value.execute_tasks = AsyncMock(return_value=[])
        await runner.run(scenario, attempts=3, seed=100)

        # Check seeds: 100, 101, 102
        assert MockSession.call_args_list[0][1]["seed"] == 100
        assert MockSession.call_args_list[1][1]["seed"] == 101
        assert MockSession.call_args_list[2][1]["seed"] == 102


# --- 4. Task Metrics & Criteria ---


@pytest.mark.asyncio
async def test_engine_state_verification():
    scenario = {
        "aes_version": 1.4,
        "id": "s",
        "metadata": {"name": "s", "compliance_level": "Standard"},
        "initial_state": {"plan": "B"},
        "tools": {
            "update": {
                "state_changes": [{"path": "plan", "value": "P"}],
                "output": {"status": "success"},
            }
        },
        "workflow": {
            "nodes": [
                {
                    "id": "t1",
                    "task_description": "d",
                    "required_tools": ["update"],
                    "expected_state_changes": [{"path": "plan", "value": "P"}],
                    "success_criteria": [{"metric": "state_verification", "threshold": 1.0}],
                }
            ],
            "edges": [],
        },
    }
    responses = [
        {"action": "call_tool", "tool_name": "update", "tool_params": {}, "summary": "U"},
        {"action": "final_answer", "summary": "Done"},
    ]
    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent",
        side_effect=lambda *args: responses.pop(0),
    ):
        results = await run_evaluation(scenario)
        metric = next(m for m in results[0]["metrics"] if m["metric"] == "state_verification")
        assert metric["success"] is True


# === Ported from test_engine.py ===


@pytest.mark.asyncio
async def test_engine_consistency_score():
    """Verify consistency score is calculated across identical attempts."""
    scenario = {
        "aes_version": 1.4,
        "id": "test-consistency",
        "metadata": {"name": "test-consistency", "compliance_level": "Standard"},
        "workflow": {"nodes": [{"id": "task-1", "task_description": "Do something"}], "edges": []},
    }

    async def mock_agent(*args):
        return {"action": "final_answer", "summary": "Identical result"}

    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_agent):
        results = await run_evaluation(scenario, attempts=2)
        task_res = results[-1][0]
        consistency_metric = next(
            (m for m in task_res["metrics"] if m["metric"] == "consistency_score"), None
        )
        assert consistency_metric is not None
        assert consistency_metric["score"] == 1.0


@pytest.mark.asyncio
async def test_engine_single_tool_call():
    """Agent calls one tool, sandbox responds, agent sends final_answer."""
    scenario = {
        "aes_version": 1.4,
        "id": "test-scenario",
        "metadata": {"name": "Test Scenario", "compliance_level": "Standard"},
        "industry": "test",
        "workflow": {
            "nodes": [
                {
                    "id": "task-1",
                    "task_description": "Do the thing.",
                    "required_tools": ["tool_a"],
                    "success_criteria": [{"metric": "tool_call_correctness", "threshold": 1.0}],
                }
            ],
            "edges": [],
        },
    }
    responses = [
        {
            "action": "call_tool",
            "tool_name": "tool_a",
            "tool_params": {"id": "123"},
            "summary": "Called.",
        },
        {"action": "final_answer", "summary": "Task complete."},
    ]

    async def mock_agent(*args):
        return responses.pop(0)

    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_agent):
        results = await run_evaluation(scenario)

    assert results[0]["task_id"] == "task-1"
    metric = next(m for m in results[0]["metrics"] if m["metric"] == "tool_call_correctness")
    assert metric["score"] == 1.0
    assert metric["success"] is True


@pytest.mark.asyncio
async def test_engine_multiple_tools():
    """Agent calls multiple tools in one turn."""
    scenario = {
        "aes_version": 1.4,
        "id": "test-multi",
        "metadata": {"name": "Test Multi", "compliance_level": "Standard"},
        "industry": "test",
        "workflow": {
            "nodes": [
                {
                    "id": "task-1",
                    "task_description": "Do the thing.",
                    "required_tools": ["tool_a", "tool_b"],
                    "success_criteria": [{"metric": "tool_call_correctness", "threshold": 1.0}],
                }
            ],
            "edges": [],
        },
    }
    responses = [
        {
            "action": "call_multiple_tools",
            "tool_names": ["tool_a", "tool_b"],
            "summary": "Ran both.",
        },
        {"action": "final_answer", "summary": "All done."},
    ]

    async def mock_agent(*args):
        return responses.pop(0)

    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_agent):
        results = await run_evaluation(scenario)

    metric = next(m for m in results[0]["metrics"] if m["metric"] == "tool_call_correctness")
    assert metric["score"] == 1.0


@pytest.mark.asyncio
async def test_engine_final_answer_first_turn():
    """Agent sends final_answer immediately — tool_call_correctness should be 0.0."""
    scenario = {
        "aes_version": 1.4,
        "id": "test-no-tool",
        "metadata": {"name": "Test No Tool", "compliance_level": "Standard"},
        "industry": "test",
        "workflow": {
            "nodes": [
                {
                    "id": "task-1",
                    "task_description": "Do the thing.",
                    "required_tools": ["tool_a"],
                    "success_criteria": [{"metric": "tool_call_correctness", "threshold": 1.0}],
                }
            ],
            "edges": [],
        },
    }

    async def mock_agent(*args):
        return {"action": "final_answer", "summary": "I already know."}

    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_agent):
        results = await run_evaluation(scenario)

    metric = next(m for m in results[0]["metrics"] if m["metric"] == "tool_call_correctness")
    assert metric["score"] == 0.0
    assert results[0]["turns_taken"] == 1


@pytest.mark.asyncio
async def test_engine_max_turns_reached(monkeypatch):
    """Agent never finishes — should stop at MAX_TURNS."""
    monkeypatch.setattr("eval_runner.config.EVAL_MAX_TURNS", 2)

    async def mock_agent(*args):
        return {"action": "call_tool", "tool_name": "tool_a", "tool_params": {}, "summary": "Turn"}

    scenario = {
        "aes_version": 1.4,
        "id": "test-maxturns",
        "metadata": {"name": "Test MaxTurns", "compliance_level": "Standard"},
        "industry": "test",
        "workflow": {
            "nodes": [
                {
                    "id": "task-1",
                    "task_description": "Do the thing.",
                    "required_tools": ["tool_a"],
                    "success_criteria": [{"metric": "tool_call_correctness", "threshold": 1.0}],
                }
            ],
            "edges": [],
        },
    }
    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_agent):
        results = await run_evaluation(scenario)

    assert results[0]["turns_taken"] <= 3


@pytest.mark.asyncio
async def test_engine_connection_error():
    """Agent API unreachable — should handle gracefully and return empty metrics."""
    scenario = {
        "aes_version": 1.4,
        "id": "test-err",
        "metadata": {"name": "Test Err", "compliance_level": "Standard"},
        "industry": "test",
        "workflow": {
            "nodes": [
                {
                    "id": "task-1",
                    "task_description": "Do the thing.",
                    "required_tools": ["tool_a"],
                    "success_criteria": [{"metric": "tool_call_correctness", "threshold": 1.0}],
                }
            ],
            "edges": [],
        },
    }
    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent",
        side_effect=Exception("Connection Error"),
    ):
        results = await run_evaluation(scenario)

    metric = next(m for m in results[0]["metrics"] if m["metric"] == "tool_call_correctness")
    assert metric["score"] == 0.0


@pytest.mark.asyncio
async def test_engine_policy_violation():
    """Verify that a policy violation is enforced and metric fails."""
    scenario = {
        "aes_version": 1.4,
        "id": "policy-test",
        "metadata": {"name": "policy-test", "compliance_level": "Standard"},
        "industry": "test",
        "policies": {"apply_refund": {"max_limit": 50}},
        "workflow": {
            "nodes": [
                {
                    "id": "task-1",
                    "task_description": "Refund the customer.",
                    "required_tools": ["apply_refund"],
                    "success_criteria": [{"metric": "policy_compliance", "threshold": 1.0}],
                }
            ],
            "edges": [],
        },
    }
    responses = [
        {
            "action": "call_tool",
            "tool_name": "apply_refund",
            "tool_params": {"amount": 100},
            "summary": "Try refund.",
        },
        {"action": "final_answer", "summary": "Limited to 50."},
    ]

    async def mock_agent(*args):
        return responses.pop(0)

    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_agent):
        results = await run_evaluation(scenario)

    compliance = next(m for m in results[0]["metrics"] if m["metric"] == "policy_compliance")
    assert compliance["score"] == 0.0


# === Ported from test_engine_runner.py ===


@pytest.mark.asyncio
async def test_adapter_registry_discovery():
    """Test that adapters are discovered and registered correctly."""
    AgentAdapterRegistry.reset()
    with patch(
        "eval_runner.config.RegistryManager.get_resolved_registry",
        return_value={"adapters": {"active_protocols": ["http", "local", "socket"]}},
    ):
        AgentAdapterRegistry._discover()
        assert "http" in AgentAdapterRegistry._adapters
        assert "local" in AgentAdapterRegistry._adapters
        assert "socket" in AgentAdapterRegistry._adapters


@pytest.mark.asyncio
async def test_adapter_registry_call_agent():
    """Test calling an agent through the registry."""
    mock_adapter = AsyncMock(return_value={"action": "test"})
    AgentAdapterRegistry.register("test-proto-ported", mock_adapter)
    result = await AgentAdapterRegistry.call_agent(
        "test-proto-ported", "test://url", "do thing", []
    )
    assert result["action"] == "test"


@pytest.mark.asyncio
async def test_run_evaluation_caps_attempts():
    """Test that attempts are capped by MAX_ENGINE_ATTEMPTS."""
    scenario = {"id": "s1"}
    with patch("eval_runner.runner.DefaultRunner.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = [{"task_id": "t1", "metrics": []}]
        await run_evaluation(scenario, attempts=100)
        call_args = mock_run.call_args[0]
        assert call_args[1] == config.MAX_ENGINE_ATTEMPTS


@pytest.mark.asyncio
async def test_default_runner_events():
    """Test that runner emits correct core events."""
    runner = DefaultRunner()
    scenario = {"id": "event-test"}
    with (
        patch("eval_runner.events.EventEmitter.emit") as mock_emit,
        patch(
            "eval_runner.session.SessionManager.execute_tasks", new_callable=AsyncMock
        ) as mock_exec,
    ):
        mock_exec.return_value = []
        await runner.run(scenario, attempts=1)
        from eval_runner.events import CoreEvents

        emitted = [call[0][0] for call in mock_emit.call_args_list]
        assert CoreEvents.RUN_START in emitted
        assert CoreEvents.RUN_END in emitted


@pytest.mark.asyncio
async def test_run_evaluation_plugin_init():
    """Test that run_evaluation initializes internal plugins."""
    from eval_runner import plugins

    scenario = {"id": "plugin-init-test"}
    with patch("eval_runner.runner.DefaultRunner.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = []
        await run_evaluation(scenario)
        plugin_types = [type(p).__name__ for p in plugins.manager.plugins]
        assert "FlightRecorderPlugin" in plugin_types
        assert "ReportingPlugin" in plugin_types


# === Ported from test_engine_utilities.py ===


def test_normalize_industry_cases():
    assert utils.normalize_industry("  FINTECH  ") == "finance"
    assert utils.normalize_industry("Unknown Industry") == "unknown_industry"
    assert utils.normalize_industry("") == "generic"
    assert utils.normalize_industry(None) == "generic"


def test_is_path_safe_logic(tmp_path):
    assert utils.is_path_safe(tmp_path / "file.txt", tmp_path) is True
    assert utils.is_path_safe(".", tmp_path) is True


def test_generate_id():
    uid = utils.generate_id("test")
    assert uid.startswith("test-")
    assert len(uid.split("-")) == 3


def test_deep_diff_comprehensive():
    assert utils.deep_diff(1, 1.0) == []
    diff = utils.deep_diff(1, "1")
    assert any("types differ" in d for d in diff)
    d1 = {"a": 1, "b": 2}
    d2 = {"a": 1, "c": 3}
    diff = utils.deep_diff(d1, d2)
    assert any("b: key missing" in d for d in diff)
    assert any("c: key extra" in d for d in diff)
    diff = utils.deep_diff([1, 2], [1, 2, 3])
    assert any("lengths differ" in d for d in diff)


def test_loader_load_csv_jsonl(tmp_path):
    csv_file = tmp_path / "test.csv"
    csv_file.write_text("id,val\n1,a\n2,b", encoding="utf-8")
    assert len(loader.load_dataset(csv_file)) == 2

    jsonl_file = tmp_path / "test.jsonl"
    jsonl_file.write_text(
        json.dumps({"id": "j1"}) + "\n" + json.dumps({"id": "j2"}), encoding="utf-8"
    )
    assert len(loader.load_dataset(jsonl_file)) == 2


def test_loader_load_dataset_jsonl_error(tmp_path):
    jsonl_file = tmp_path / "bad.jsonl"
    jsonl_file.write_text("invalid json", encoding="utf-8")
    with patch("builtins.print"):
        assert loader.load_dataset(jsonl_file) == []


def test_loader_load_dataset_directory(tmp_path):
    scenario_dir = tmp_path / "scenarios"
    scenario_dir.mkdir()
    s1 = scenario_dir / "s1.json"
    s1.write_text(
        json.dumps(
            {
                "metadata": {
                    "id": "s1",
                    "name": "S1",
                    "compliance_level": "Standard",
                },
                "aes_version": 1.4,
                "workflow": {"nodes": [], "edges": []},
                "evaluation": {"metrics": []},
            }
        ),
        encoding="utf-8",
    )
    assert len(loader.load_dataset(scenario_dir)) == 1


def test_loader_load_scenario_invalid_workflow(tmp_path):
    scenario_file = tmp_path / "invalid_workflow.json"
    scenario_file.write_text(
        json.dumps(
            {
                "id": "test",
                "metadata": {"id": "test", "compliance_level": "Standard", "name": "T"},
                "aes_version": 1.4,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Scenario missing required 'workflow' block"):
        loader.load_scenario(str(scenario_file))


def test_loader_load_scenario_unsupported_version(tmp_path):
    scenario_file = tmp_path / "old.json"
    scenario_file.write_text(
        json.dumps(
            {
                "id": "test",
                "metadata": {"id": "test", "compliance_level": "Standard", "name": "T"},
                "aes_version": 0.1,
                "workflow": {"nodes": [], "edges": []},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported AES version"):
        loader.load_scenario(str(scenario_file))


def test_loader_load_dataset_benchmark_uri():
    with patch("eval_runner.benchmarks.gaia.GAIABenchmark.load", return_value=[{"id": "GAIA-1"}]):
        assert len(loader.load_dataset("gaia://2023")) == 1


def test_loader_load_dataset_invalid_uri():
    with patch("builtins.print") as mock_print:
        assert loader.load_dataset("unknown://protocol") == []
        mock_print.assert_any_call("      [Loader] Warning: Unknown benchmark scheme 'unknown'")


@pytest.mark.asyncio
async def test_analyzer_comprehensive():
    await analyzer.analyze_repo("http://github.com/telecom-agent")
    await analyzer.analyze_repo("http://github.com/finance-agent")
    results = await analyzer.analyze_repo("http://github.com/unknown")
    assert results[0]["metadata"]["pattern"] == "AgentExecutor(...)"


def test_failure_corpus_no_log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    with patch("builtins.print") as mock_print:
        failure_corpus.search("test")
        mock_print.assert_any_call(
            "ℹ️  No master log found at runs/run.jsonl. Try running an evaluation first."
        )


def test_failure_corpus_comprehensive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(exist_ok=True)
    master_log = runs_dir / "run.jsonl"
    events = [
        {
            "event": "tool_call",
            "status": "error",
            "triage_tag": "API_FAILURE",
            "run_id": "r1",
            "timestamp": "1",
        },
        "",
        {"event": "agent_response", "content": "hello world", "run_id": "r2", "timestamp": "2"},
        "invalid json line",
    ]
    for i in range(11):
        events.append(
            {
                "event": "tool_call",
                "status": "error",
                "triage_tag": "LIMIT",
                "run_id": f"L{i}",
                "timestamp": "3",
            }
        )

    with open(master_log, "w", encoding="utf-8") as f:
        for e in events:
            f.write((json.dumps(e) if isinstance(e, dict) else e) + "\n")

    with patch("builtins.print") as mock_print:
        failure_corpus.search("api failure")
        mock_print.assert_any_call("✅ Found 1 matching failure events:")
        failure_corpus.search("limit")
        all_calls = "".join(str(c) for c in mock_print.call_args_list)
        assert "more" in all_calls
        failure_corpus.search("nothing")
        mock_print.assert_any_call("❌ No matching failures found for 'nothing'.")


def test_failure_corpus_error_handling():
    with (
        patch("eval_runner.failure_corpus.Path.exists", return_value=True),
        patch("builtins.open", side_effect=Exception("Read error")),
        patch("builtins.print") as mock_print,
    ):
        failure_corpus.search("test")
        mock_print.assert_any_call("❌ Error searching corpus: Read error")


# --- Coverage booster for runner.py and engine.py ---


@pytest.mark.asyncio
async def test_runner_otel_parent_context():

    from eval_runner.runner import DefaultRunner

    scenario = {
        "id": "test-otel",
        "span_context": {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
    }
    runner = DefaultRunner()

    # Mock trace.get_tracer to track start_span
    mock_tracer = patch("opentelemetry.trace.get_tracer").start()
    mock_span = mock_tracer.return_value.start_span.return_value
    mock_span.is_recording.return_value = True

    try:
        # 1. Test scenario["span_context"] path
        await runner.run(scenario, attempts=1)

        # 2. Test metadata["traceparent"] path
        metadata = {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
        await runner.run({"id": "test-otel-meta"}, attempts=1, metadata=metadata)
    finally:
        patch.stopall()


@pytest.mark.asyncio
async def test_runner_otel_init_failure():
    from eval_runner.runner import DefaultRunner

    runner = DefaultRunner()

    # Mock trace.get_tracer to raise an exception
    with patch("opentelemetry.trace.get_tracer", side_effect=Exception("Tracer failed")):
        # Should catch telemetry exception and proceed normally
        res = await runner.run({"id": "test-otel-fail"}, attempts=1)
        assert isinstance(res, list)


@pytest.mark.asyncio
async def test_runner_post_process_error():
    from eval_runner.runner import DefaultRunner

    runner = DefaultRunner()

    # Mock calculate_pass_at_k to raise an exception
    with patch.object(runner, "calculate_pass_at_k", side_effect=ValueError("Post-process crash")):
        # Should catch post-process failure gracefully
        res = await runner.run({"id": "test-post-fail"}, attempts=1)
        assert isinstance(res, list)


@pytest.mark.asyncio
async def test_runner_finally_span_end_exception():
    from opentelemetry.trace import Span

    from eval_runner.runner import DefaultRunner

    runner = DefaultRunner()

    # Mock Span.end to raise an exception
    with patch.object(Span, "end", side_effect=Exception("End failed")):
        res = await runner.run({"id": "test-span-end-fail"}, attempts=1)
        assert isinstance(res, list)


@pytest.mark.asyncio
async def test_engine_discover_already_discovered():
    from eval_runner.engine import AgentAdapterRegistry

    # If already discovered, should return early
    AgentAdapterRegistry._discovered = True
    # Verify no discovery takes place
    with patch("eval_runner.config.RegistryManager.get_resolved_registry") as mock_resolved:
        AgentAdapterRegistry._discover()
        mock_resolved.assert_not_called()
    AgentAdapterRegistry._discovered = False


@pytest.mark.asyncio
async def test_engine_dispatcher_otel_carrier():

    from eval_runner.engine import AgentAdapterRegistry

    # Patch propagation.inject to insert traceparent
    def mock_inject(carrier, context=None):
        carrier["traceparent"] = "mock-traceparent"

    async def mock_adapter(payload, endpoint):
        return {"status": "success", "action": "test"}

    AgentAdapterRegistry.register("openapi", mock_adapter, allow_override=True)

    class DummyTurnCtx:
        turn_number = 1
        metadata = {}
        input_payload = {}
        otel_context = None

    turn_ctx = DummyTurnCtx()

    with patch("opentelemetry.trace.propagation.inject", side_effect=mock_inject, create=True):
        res = await AgentAdapterRegistry.call_agent(
            "openapi", "hello", "local", [], turn_ctx=turn_ctx
        )
        assert turn_ctx.span_context == {"traceparent": "mock-traceparent"}
        assert res["status"] == "success"


@pytest.mark.asyncio
async def test_engine_dispatcher_adapter_exception():
    from eval_runner.engine import AgentAdapterRegistry

    async def mock_adapter_fail(payload, endpoint):
        raise ValueError("Adapter execution crashed")

    AgentAdapterRegistry.register("openapi", mock_adapter_fail, allow_override=True)

    class DummyTurnCtx:
        turn_number = 1
        metadata = {}
        input_payload = {}
        otel_context = None

    turn_ctx = DummyTurnCtx()

    # Verify it records exception and propagates/re-raises
    with pytest.raises(ValueError, match="Adapter execution crashed"):
        await AgentAdapterRegistry.call_agent("openapi", "hello", "local", [], turn_ctx=turn_ctx)


@pytest.mark.asyncio
async def test_engine_dispatcher_span_end_exception():
    from opentelemetry.trace import Span

    from eval_runner.engine import AgentAdapterRegistry

    async def mock_adapter(payload, endpoint):
        return {"status": "success"}

    AgentAdapterRegistry.register("openapi", mock_adapter, allow_override=True)

    class DummyTurnCtx:
        turn_number = 1
        metadata = {}
        input_payload = {}
        otel_context = None

    turn_ctx = DummyTurnCtx()

    with patch.object(Span, "end", side_effect=Exception("Span end failure")):
        res = await AgentAdapterRegistry.call_agent(
            "openapi", "hello", "local", [], turn_ctx=turn_ctx
        )
        assert res["status"] == "success"
