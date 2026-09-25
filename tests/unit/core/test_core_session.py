import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.execution_ir import (
    CompiledEvaluationPlan,
    CompiledOracle,
    ExecutionIdentity,
)
from eval_runner.session import ExecutionMode, NodeVerdict, SessionManager, _InterpreterEventBridge
from eval_runner.workflow_interpreter import WorkflowOutcome, WorkflowStatus


@pytest.fixture
def base_scenario():
    return {
        "id": "session_test",
        "run_id": "test_run_456",
        "max_turns": 3,
        "metadata": {"agent": {"endpoint": "mock://test", "protocol": "http"}},
        "initial_state": {},
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "task_description": "Do the thing",
                    "expected_outcome": [
                        {"target": "message", "expected": "success", "mode": "exact"}
                    ],
                }
            ],
            "edges": [],
        },
        "tools": {},
        "evaluation": {"metrics": [{"id": "global_metric", "type": "exact_match"}]},
    }


# --- Session Initialization Tests ---


def test_session_manager_initialization(base_scenario, tmp_path):
    session = SessionManager("test_run_456", base_scenario, log_root=tmp_path)

    assert session.run_id == "test_run_456"
    assert session.identifier == "session_test"
    assert session.session_metadata["protocol"] == "http"
    assert session.session_metadata["agent"] == "mock://test"

    # Check persistence
    assert session.run_vault == tmp_path / "test_run_456"
    assert (session.run_vault / "scenario_original.json").exists()
    assert (session.run_vault / "scenario_resolved.json").exists()


def test_session_manager_routing_discovery(base_scenario, tmp_path):
    base_scenario["capabilities"] = ["test_capability"]

    mock_registry_resolve = {
        "protocol": "custom",
        "endpoint": "custom://agent",
        "metadata": {"custom_meta": 1},
    }

    with patch("eval_runner.routing.RoutingRegistry.resolve", return_value=mock_registry_resolve):
        session = SessionManager("test_run_456", base_scenario, log_root=tmp_path)

        assert session.session_metadata["protocol"] == "custom"
        assert session.session_metadata["agent"] == "custom://agent"
        assert session.session_metadata["custom_meta"] == 1


# --- Node Execution Tests ---


@pytest.mark.asyncio
async def test_session_execute_tasks_success(base_scenario, tmp_path):
    session = SessionManager("test_run_456", base_scenario, log_root=tmp_path)
    # [A2] Minimum-oracle rule: every executable node must declare at least
    # one assertion source; zero-assertion nodes are rejected at compile time.
    session.scenario["workflow"]["nodes"][0]["success_criteria"] = [
        {"metric": "task_completion", "threshold": 1.0}
    ]

    mock_agent_response = {"action": "completed", "tool_name": None, "message": "success"}

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_agent:
        mock_agent.return_value = mock_agent_response
        with patch.object(session, "_calculate_metrics", new_callable=AsyncMock) as mock_metrics:
            mock_metrics.return_value = {"status": "success", "metrics": [{"success": True}]}

            results = await session.execute_tasks(attempt_number=1)
            assert len(results) == 2  # node_1 + global_evaluation
            assert results[0]["status"] == "success"
            assert results[1]["status"] == "success"


@pytest.mark.asyncio
async def test_session_execute_tasks_cycle_error(base_scenario, tmp_path):
    base_scenario["workflow"]["nodes"].append({"id": "node_2"})
    base_scenario["workflow"]["edges"] = [
        {"from": "node_1", "to": "node_2"},
        {"from": "node_2", "to": "node_1"},  # pure cycle: no terminal node
    ]

    session = SessionManager("test_run_456", base_scenario, log_root=tmp_path)

    results = await session.execute_tasks(1)
    assert len(results) > 0
    assert results[-1]["status"] == "failure"
    # A pure cycle declares no canonical entry; the IR compiler rejects it.
    assert "workflow" in results[-1]["message"].lower()
    assert results[-1].get("triage_tag") == "EVALUATION_INVALID"


@pytest.mark.asyncio
async def test_session_execute_tasks_empty_topology(base_scenario, tmp_path):
    base_scenario["workflow"]["nodes"] = []
    session = SessionManager("test_run_456", base_scenario, log_root=tmp_path)

    results = await session.execute_tasks(1)
    assert len(results) > 0
    assert results[-1]["status"] == "failure"
    # Empty topology is an invalid evaluation, never a silent pass.
    assert "no executable nodes" in results[-1]["message"]
    assert results[-1].get("triage_tag") == "EVALUATION_INVALID"


# --- Turn Handlers (Tools and Hitl) ---


@pytest.mark.asyncio
async def test_handle_tool_call(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    mock_sandbox = AsyncMock()
    mock_sandbox.execute.return_value = {"status": "success"}
    mock_sandbox.state = {}
    mock_sandbox.get_full_state.return_value = {}

    agent_resp = {"tool_name": "test_tool", "tool_params": {}}
    history = []
    actions = {"used_tools": []}
    turn_ctx = MagicMock()

    await session._handle_tool_call(1, agent_resp, mock_sandbox, history, actions, turn_ctx)

    assert "test_tool" in actions["used_tools"]
    mock_sandbox.execute.assert_awaited_with("test_tool", {})


@pytest.mark.asyncio
async def test_handle_multiple_tools(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    mock_sandbox = AsyncMock()
    mock_sandbox.execute.return_value = {"status": "success"}
    mock_sandbox.state = {}
    mock_sandbox.get_full_state.return_value = {}

    agent_resp = {"tool_names": ["t1", "t2"]}
    history = []
    actions = {"used_tools": []}
    turn_ctx = MagicMock()

    await session._handle_multiple_tools(1, agent_resp, mock_sandbox, history, actions, turn_ctx)

    assert "t1" in actions["used_tools"]
    assert "t2" in actions["used_tools"]
    assert mock_sandbox.execute.call_count == 2
    # Legacy check: should pass empty dicts
    mock_sandbox.execute.assert_any_await("t1", {})
    mock_sandbox.execute.assert_any_await("t2", {})


@pytest.mark.asyncio
async def test_handle_multiple_tools_parameterized(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    mock_sandbox = AsyncMock()
    mock_sandbox.execute.return_value = {"status": "success"}
    mock_sandbox.state = {}
    mock_sandbox.get_full_state.return_value = {}

    agent_resp = {
        "tool_calls": [{"tool": "t1", "params": {"p1": 1}}, {"tool": "t2", "params": {"p2": 2}}]
    }
    history = []
    actions = {"used_tools": []}
    turn_ctx = MagicMock()

    await session._handle_multiple_tools(1, agent_resp, mock_sandbox, history, actions, turn_ctx)

    assert "t1" in actions["used_tools"]
    assert "t2" in actions["used_tools"]
    assert mock_sandbox.execute.call_count == 2
    mock_sandbox.execute.assert_any_await("t1", {"p1": 1})
    mock_sandbox.execute.assert_any_await("t2", {"p2": 2})

    # Verify history recording
    assert len(history) == 1
    assert history[0]["role"] == "environment"
    assert len(history[0]["content"]) == 2
    assert history[0]["content"][0]["status"] == "success"


@pytest.mark.asyncio
async def test_handle_multiple_tools_duplicate_calls(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    mock_sandbox = AsyncMock()
    mock_sandbox.execute.side_effect = lambda tn, tp: {"status": "success", "params": tp}
    mock_sandbox.state = {}
    mock_sandbox.get_full_state.return_value = {}

    agent_resp = {
        "tool_calls": [{"tool": "t1", "params": {"id": 1}}, {"tool": "t1", "params": {"id": 2}}]
    }
    history = []
    actions = {"used_tools": []}
    turn_ctx = MagicMock()

    await session._handle_multiple_tools(1, agent_resp, mock_sandbox, history, actions, turn_ctx)

    assert actions["used_tools"] == ["t1", "t1"]
    assert mock_sandbox.execute.call_count == 2

    results = history[0]["content"]
    assert results[0]["params"]["id"] == 1
    assert results[1]["params"]["id"] == 2


@pytest.mark.asyncio
async def test_handle_tool_call_interceptor_block(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    # Setup plugin interceptor to block
    session.plugin_manager.trigger_interceptor = MagicMock(return_value=False)

    mock_sandbox = AsyncMock()
    agent_resp = {"tool_name": "test_tool"}

    await session._handle_tool_call(
        1, agent_resp, mock_sandbox, [], {"used_tools": []}, MagicMock()
    )

    mock_sandbox.execute.assert_not_called()


@pytest.mark.asyncio
async def test_handle_tool_call_interceptor_short_circuit(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    session.plugin_manager.trigger_interceptor = MagicMock(
        return_value={"short_circuit_result": {"hacked": True}}
    )

    mock_sandbox = AsyncMock()
    agent_resp = {"tool_name": "test_tool"}
    history = []

    await session._handle_tool_call(
        1, agent_resp, mock_sandbox, history, {"used_tools": []}, MagicMock()
    )

    mock_sandbox.execute.assert_not_called()
    assert "hacked" in history[-1]["content"]


# --- Parity State Verification Tests ---


@pytest.mark.asyncio
async def test_verify_state_parity_success(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    node = {
        "expected_outcome": [
            {"target": "message", "expected": "ok", "mode": "exact"},
            {"target": "state", "property": "k1", "expected": 1, "mode": "exact"},
            {"target": "shim:db.val", "expected": "db_val", "mode": "exact"},
        ],
        "timeout": 0.1,
    }

    mock_sandbox = AsyncMock()
    mock_sandbox.get_active_simulators = MagicMock(return_value={"db": AsyncMock()})
    mock_sandbox.get_active_simulators.return_value["db"].get_snapshot.return_value = {
        "val": "db_val"
    }
    mock_sandbox.get_full_state.return_value = {"k1": 1}

    history = [{"role": "agent", "content": "ok"}]

    result, evidence = await session._verify_state_parity(node, mock_sandbox, history)
    assert result is True
    assert len(evidence) == 3
    assert all(row["passed"] for row in evidence)


@pytest.mark.asyncio
async def test_verify_state_parity_timeout(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {"expected_outcome": [{"target": "message", "expected": "ok"}], "timeout": 0.1}
    mock_sandbox = AsyncMock()
    mock_sandbox.get_active_simulators = MagicMock(return_value={})
    history = [{"role": "agent", "content": "wrong"}]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result, evidence = await session._verify_state_parity(node, mock_sandbox, history)

    assert result is False
    assert all(not row["passed"] for row in evidence)


@pytest.mark.asyncio
async def test_verify_state_parity_unsupported_target(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {"expected_outcome": [{"target": "weird", "expected": "ok"}], "timeout": 0.1}
    mock_sandbox = AsyncMock()
    mock_sandbox.get_active_simulators = MagicMock(return_value={})

    result, evidence = await session._verify_state_parity(node, mock_sandbox, [])
    assert result is False
    assert evidence and evidence[0].get("error")


# --- Agent Error Handling ---


@pytest.mark.asyncio
async def test_execute_node_agent_error(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=Exception("API down")
    ):
        with patch.object(session, "_calculate_metrics", new_callable=AsyncMock) as mock_calc:
            mock_calc.return_value = {}
            res = await session._execute_node(
                base_scenario["workflow"]["nodes"][0], 1, 0, AsyncMock(), [], {}
            )

            assert res["status"] == "failure"
            assert "API down" in res["message"]


# --- Teardown ---


@pytest.mark.asyncio
async def test_session_teardown(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    mock_sandbox = AsyncMock()
    mock_sandbox.terminal_jail = tmp_path / "jail"
    mock_sandbox.terminal_jail.mkdir()
    (mock_sandbox.terminal_jail / "terminal.log").write_text("log")

    session.forensics = MagicMock()

    await session.teardown(mock_sandbox)

    mock_sandbox.teardown.assert_awaited()
    session.forensics.register_artifact.assert_called()
    session.forensics.collect.assert_called()


# --- Additional Metric and Parity Coverage ---


@pytest.mark.asyncio
async def test_session_state_parity_regex_numerical(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    node = {
        "expected_outcome": [
            {"target": "state", "property": "val", "expected": "regex:^[0-9]+$", "mode": "regex"},
            {"target": "state", "property": "num", "expected": 1.0, "mode": "numerical_tolerance"},
            {"target": "message", "expected": "test", "mode": "regex"},
        ],
        "timeout": 0.1,
    }
    mock_sandbox = AsyncMock()
    mock_sandbox.get_active_simulators = MagicMock(return_value={})
    mock_sandbox.get_full_state.return_value = {"val": "123", "num": 1.0000000001}
    history = [{"role": "agent", "content": "testing 123"}]

    result, _evidence = await session._verify_state_parity(node, mock_sandbox, history)
    assert result is True


@pytest.mark.asyncio
async def test_session_calculate_metrics_hygiene_and_dispatch(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    node = {
        "id": "node_1",
        "state_hygiene": {
            "rules": [
                {"path": "val", "expected": 1, "op": "eq"},
                {"path": "missing", "op": "not_exists"},
                {"path": "val", "op": "exists"},
                {"path": "list", "expected": "item", "op": "contains"},
            ]
        },
        "success_criteria": [{"metric": "exact_match", "expected": "ok"}],
    }

    mock_sandbox = AsyncMock()
    mock_sandbox.state = {"val": 1, "list": ["item"]}
    history = [{"role": "agent", "content": "ok"}]
    actions = {"used_tools": []}

    async def dummy_exact_match(actual, expected):
        return 1.0 if actual == expected else 0.0

    with patch("eval_runner.metrics.MetricRegistry.get", return_value=dummy_exact_match):
        with patch("eval_runner.metrics.MetricRegistry.get_source", return_value="CORE"):
            res = await session._calculate_metrics(node, 1, 1, history, mock_sandbox, actions)

    assert res["task_id"] == "node_1"
    assert len(res["state_hygiene"]) == 4
    assert all(r["success"] for r in res["state_hygiene"])
    assert res["metrics"][0]["success"] is True


@pytest.mark.asyncio
async def test_session_handle_hitl(base_scenario, tmp_path, monkeypatch):
    """[P0-9] CI must NEVER auto-approve a human gate: the request resolves to
    an explicit HITL_UNRESOLVED marker and flags the session accordingly."""
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    agent_resp = {"prompt": "Confirm action"}
    history = []
    actions = {}
    turn_ctx = MagicMock()

    monkeypatch.setenv("CI", "true")
    res = await session._handle_hitl(1, agent_resp, history, actions, turn_ctx)
    assert "HITL_UNRESOLVED" in res
    assert "Auto-approved" not in res
    assert session._hitl_unresolved is True


@pytest.mark.asyncio
async def test_session_execute_node_hitl_and_processing(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    node = {"id": "node_1", "task_description": "task"}
    mock_sandbox = AsyncMock()
    mock_sandbox.get_full_state.return_value = {}

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_agent:
        # Simulate processing then hitl then final_answer
        mock_agent.side_effect = [
            {"action": "processing"},
            {"action": "hitl_pause", "prompt": "verify"},
            {"action": "final_answer"},
        ]

        with patch.object(session, "_handle_hitl", new_callable=AsyncMock) as mock_hitl:
            mock_hitl.return_value = "ok"
            with patch.object(
                session, "_calculate_metrics", new_callable=AsyncMock
            ) as mock_metrics:
                mock_metrics.return_value = {"metrics": []}

                res = await session._execute_node(node, 1, 0, mock_sandbox, [], {})

                assert res["status"] == "success"


@pytest.mark.asyncio
async def test_session_execute_node_error_action(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {"id": "node_1"}

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_agent:
        mock_agent.return_value = {"action": "error"}
        with patch.object(session, "_calculate_metrics", new_callable=AsyncMock) as mock_metrics:
            mock_metrics.return_value = {"metrics": []}
            res = await session._execute_node(node, 1, 0, AsyncMock(), [], {})
            assert res["status"] == "failure"


@pytest.mark.asyncio
async def test_session_execute_node_unknown_action(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {"id": "node_1"}

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_agent:
        mock_agent.return_value = {"action": "weird"}
        with patch.object(session, "_calculate_metrics", new_callable=AsyncMock) as mock_metrics:
            mock_metrics.return_value = {"metrics": []}
            res = await session._execute_node(node, 1, 0, AsyncMock(), [], {})
            assert res["status"] == "failure"


@pytest.mark.asyncio
async def test_session_execute_node_empty_response(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {"id": "node_1"}

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_agent:
        mock_agent.return_value = None
        with patch.object(session, "_calculate_metrics", new_callable=AsyncMock) as mock_metrics:
            mock_metrics.return_value = {"metrics": []}
            res = await session._execute_node(node, 1, 0, AsyncMock(), [], {})
            assert res["status"] == "failure"
            assert "returned no payload" in res["message"]


def test_session_manager_plugin_reloading(base_scenario, tmp_path):
    mock_prov = {"CustomPlugin": {"origin": "EXTERNAL", "path": "/fake/path"}}
    from eval_runner import plugins as global_plugins

    with patch.object(global_plugins.manager, "provenance_map", mock_prov):
        with patch("eval_runner.plugins.PluginManager.load") as mock_load:
            SessionManager("test_run", base_scenario, log_root=tmp_path)
            mock_load.assert_called_with("/fake/path")


def test_session_routing_local_socket(base_scenario, tmp_path, monkeypatch):
    base_scenario["metadata"] = {"agent": {"protocol": "local"}}
    monkeypatch.setenv("AGENT_LOCAL_CMD", "echo")
    session1 = SessionManager("run1", base_scenario, log_root=tmp_path)
    assert session1.session_metadata["agent"] == "echo"

    base_scenario["metadata"] = {"agent": {"protocol": "socket"}}
    monkeypatch.setenv("AGENT_SOCKET_ADDR", "localhost:9000")
    session2 = SessionManager("run2", base_scenario, log_root=tmp_path)
    assert session2.session_metadata["agent"] == "localhost:9000"


@pytest.mark.asyncio
async def test_multiple_tools_interceptor(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    def mock_trigger(name, ctx, tn, *args):
        if tn == "t1":
            return False
        if tn == "t2":
            return {"short_circuit_result": {"hacked": True}}
        return True

    session.plugin_manager.trigger_interceptor = MagicMock(side_effect=mock_trigger)

    mock_sandbox = AsyncMock()
    mock_sandbox.state = {}
    mock_sandbox.get_full_state.return_value = {}

    agent_resp = {"tool_names": ["t1", "t2"]}
    actions = {"used_tools": []}

    await session._handle_multiple_tools(1, agent_resp, mock_sandbox, [], actions, MagicMock())

    mock_sandbox.execute.assert_not_called()


def test_session_fork(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    forked = session.fork([], {})
    assert forked.run_id == "test_run"
    assert forked.scenario["_fork_depth"] == 1

    forked.fork_depth = config.MAX_FORK_DEPTH
    with pytest.raises(RuntimeError, match="Fork Bomb Prevention"):
        forked.fork([], {})


def test_session_extract_tool_registry(base_scenario, tmp_path):
    base_scenario["tools"] = {"t1": {"parameters": {"p1": {}}}, "t2": {"expected_params": ["p2"]}}
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    reg = session._extract_tool_registry()
    assert "p1" in reg["t1"]["parameters"]
    assert "p2" in reg["t2"]["parameters"]


def test_session_sanitize_history(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    res = session._sanitize_for_history([1, 2, "three"])
    assert res == [1, 2, "three"]

    class WeirdObj:
        pass

    res = session._sanitize_for_history(WeirdObj())
    assert "WeirdObj" in res


@pytest.mark.asyncio
async def test_session_get_shim_snapshots(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    mock_sandbox = MagicMock()

    class DummyShim:
        async def get_snapshot(self):
            return {"ok": 1}

    mock_sandbox.get_active_simulators.return_value = {"shim1": DummyShim()}

    snaps = await session._get_shim_snapshots(mock_sandbox, ["shim1", "unknown"])
    assert snaps["shim1"]["ok"] == 1


def test_capture_telemetry_error(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    with patch("psutil.Process", side_effect=Exception("psutil error")):
        session._capture_telemetry()
        assert len(session.resource_telemetry) == 0


@pytest.mark.asyncio
async def test_session_execute_tasks_node_failure(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    base_scenario["workflow"]["nodes"].append({"id": "node_2"})
    base_scenario["workflow"]["edges"] = [{"from": "node_1", "to": "node_2"}]

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_agent:
        # First node fails
        mock_agent.return_value = {"action": "error"}
        with patch.object(session, "_calculate_metrics", new_callable=AsyncMock) as mock_calc:
            mock_calc.side_effect = lambda *args, **kwargs: {"status": "failure", "metrics": []}
            res = await session.execute_tasks(1)
            assert res[0]["status"] == "failure"


@pytest.mark.asyncio
async def test_metrics_dispatch_error_and_skip(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {"success_criteria": [{"metric": "non_existent_metric"}, {"metric": "crashing_metric"}]}

    def mock_get(name):
        if name == "non_existent_metric":
            return None

        def crash(*args, **kwargs):
            raise Exception("crash")

        return crash

    with patch("eval_runner.metrics.MetricRegistry.get", side_effect=mock_get):
        res = await session._calculate_metrics(node, 1, 1, [], AsyncMock(), {"used_tools": []})
        # Strict assertion semantics: unknown metrics and evaluator
        # exceptions produce EVALUATION_INVALID rows, never silent skips.
        assert len(res["metrics"]) == 2
        assert all(m["status"] == "EVALUATION_INVALID" for m in res["metrics"])
        assert res["evaluation_valid"] is False
        assert res["triage_tag"] == "EVALUATION_INVALID"


def test_sanitize_history_type_error(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    class Unencodable:
        def __str__(self):
            return "custom_str"

    with patch("eval_runner.trace_utils.AESJsonEncoder.default", side_effect=TypeError):
        res = session._sanitize_for_history(Unencodable())
        assert res == "custom_str"


@pytest.mark.asyncio
async def test_session_hitl_interactive(base_scenario, tmp_path, monkeypatch):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    agent_resp = {"prompt": "Confirm?"}
    monkeypatch.setenv("CI", "false")

    with patch("sys.stdin.isatty", return_value=True):
        with patch("builtins.input", return_value="my response"):
            res = await session._handle_hitl(1, agent_resp, [], {}, MagicMock())
            assert res == "my response"

        with patch("builtins.input", return_value="exit"):
            with pytest.raises(InterruptedError):
                await session._handle_hitl(1, agent_resp, [], {}, MagicMock())


@pytest.mark.asyncio
async def test_session_hitl_non_interactive(base_scenario, tmp_path, monkeypatch):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    agent_resp = {"prompt": "Confirm?"}
    monkeypatch.setenv("CI", "false")

    with patch("sys.stdin.isatty", return_value=False):
        res = await session._handle_hitl(1, agent_resp, [], {}, MagicMock())
        assert "non-interactive" in res


def test_get_last_env_message(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    # list
    history = [{"role": "environment", "content": ["list", "of", "items"]}]
    msg = session._get_last_env_message(history)
    assert "Tools returned" in msg

    # dict with message
    history = [{"role": "environment", "content": {"message": "hello"}}]
    msg = session._get_last_env_message(history)
    assert msg == "hello"

    # dict with content
    history = [{"role": "environment", "content": {"content": "world"}}]
    msg = session._get_last_env_message(history)
    assert msg == "world"

    # string fallback
    history = [{"role": "environment", "content": "direct string"}]
    msg = session._get_last_env_message(history)
    assert msg == "direct string"

    # empty history
    assert session._get_last_env_message([]) == ""


@pytest.mark.asyncio
async def test_session_tool_redirection_and_completed(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {"id": "node_1"}

    # Trigger redirection
    session.plugin_manager.trigger_interceptor = MagicMock(
        return_value={"tool_name": "redirected_tool", "arguments": {}}
    )

    mock_sandbox = AsyncMock()
    mock_sandbox.state = {}
    mock_sandbox.get_full_state.return_value = {}

    agent_resp = {"action": "call_tool", "tool_name": "original_tool", "tool_params": {}}

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_agent:
        # Simulate tool call, then completed
        mock_agent.side_effect = [agent_resp, {"action": "completed"}]

        with patch.object(session, "_calculate_metrics", new_callable=AsyncMock) as mock_metrics:
            mock_metrics.return_value = {"metrics": []}
            res = await session._execute_node(node, 1, 0, mock_sandbox, [], {"used_tools": []})
            assert res["status"] == "success"
            mock_sandbox.execute.assert_awaited_with("redirected_tool", {})


def test_session_manager_initialization_with_metadata(base_scenario, tmp_path):
    metadata = {"custom_key": "custom_val"}
    session = SessionManager("test_run_456", base_scenario, metadata=metadata, log_root=tmp_path)
    assert session.session_metadata["custom_key"] == "custom_val"


def test_session_telemetry_no_psutil(base_scenario, tmp_path):
    with patch("eval_runner.session.psutil", None):
        session = SessionManager("test_run", base_scenario, log_root=tmp_path)
        session._capture_telemetry()
        assert len(session.resource_telemetry) == 0


def test_session_import_error_psutil(base_scenario, tmp_path):
    with patch("eval_runner.session.psutil", None):
        session = SessionManager("test_run_psutil", base_scenario, log_root=tmp_path)
        session._capture_telemetry()
        assert len(session.resource_telemetry) == 0


def test_session_plugin_reload_error(base_scenario, tmp_path):
    from unittest.mock import PropertyMock

    mock_prov = {"CustomPlugin": {"origin": "EXTERNAL", "path": "/fake/path"}}
    with patch(
        "eval_runner.plugins.PluginManager.provenance_map", new_callable=PropertyMock, create=True
    ) as mock_prop:
        mock_prop.return_value = mock_prov
        with patch("eval_runner.plugins.PluginManager.load", side_effect=Exception("Load error")):
            SessionManager("test_run", base_scenario, log_root=tmp_path)


def test_session_plugin_archive_error(base_scenario, tmp_path):
    from unittest.mock import PropertyMock

    mock_prov = {"CustomPlugin": {"origin": "EXTERNAL", "path": "/fake/path"}}
    with patch(
        "eval_runner.plugins.PluginManager.provenance_map", new_callable=PropertyMock, create=True
    ) as mock_prop:
        mock_prop.return_value = mock_prov
        with patch("eval_runner.plugins.PluginManager.load"):
            with patch(
                "eval_runner.forensics.ForensicCollector.archive_plugin",
                side_effect=Exception("Archive error"),
            ):
                SessionManager("test_run", base_scenario, log_root=tmp_path)


def test_session_manual_init_event(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    session.event_bus.emit("MANUAL_INIT", {})
    assert "init" in session.protocol_sequence


@pytest.mark.asyncio
async def test_session_execute_tasks_missing_node(base_scenario, tmp_path):
    base_scenario["workflow"]["edges"] = [{"from": "node_1", "to": "node_missing"}]
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    session.scenario["workflow"]["nodes"][0]["expected_outcome"] = []
    # Dangling edges are an invalid control-flow contract: the IR
    # compiler rejects the plan fail-fast instead of executing phantom nodes.
    res = await session.execute_tasks(1)
    assert len(res) == 1
    assert res[0]["status"] == "failure"
    assert "unknown target node" in res[0]["message"]
    assert res[0].get("triage_tag") == "EVALUATION_INVALID"


@pytest.mark.asyncio
async def test_session_execute_node_throttle(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {"id": "node_1"}
    with patch("eval_runner.config.EVAL_TURN_THROTTLE", 0.01):
        with patch(
            "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
        ) as mock_agent:
            mock_agent.return_value = {"action": "completed"}
            with patch.object(session, "_calculate_metrics", new_callable=AsyncMock) as mock_calc:
                mock_calc.return_value = {"status": "success", "metrics": []}
                await session._execute_node(node, 1, 0, AsyncMock(), [], {})


@pytest.mark.asyncio
async def test_session_execute_node_multiple_tools(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {"id": "node_1"}
    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_agent:
        mock_agent.side_effect = [
            {"action": "call_multiple_tools", "tool_names": ["t1"]},
            {"action": "completed"},
        ]
        mock_sandbox = AsyncMock()
        mock_sandbox.state = {}
        mock_sandbox.get_full_state.return_value = {}
        with patch.object(session, "_calculate_metrics", new_callable=AsyncMock) as mock_calc:
            mock_calc.return_value = {"status": "success", "metrics": []}
            await session._execute_node(node, 1, 0, mock_sandbox, [], {"used_tools": []})
            assert mock_sandbox.execute.call_count == 1


@pytest.mark.asyncio
async def test_verify_state_parity_shim_path_variants(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {
        "expected_outcome": [
            {"target": "shim:db.sub", "property": "val", "expected": "ok", "mode": "exact"},
            {"target": "shim:db", "expected": {"sub": {"val": "ok"}, "val": "ok"}, "mode": "exact"},
        ],
        "timeout": 0.1,
    }
    mock_sandbox = AsyncMock()
    mock_sandbox.get_active_simulators = MagicMock(return_value={"db": AsyncMock()})
    mock_sandbox.get_active_simulators.return_value["db"].get_snapshot = AsyncMock(
        return_value={"sub": {"val": "ok"}, "val": "ok"}
    )
    result, _evidence = await session._verify_state_parity(node, mock_sandbox, [])
    assert result is True


@pytest.mark.asyncio
async def test_verify_state_parity_contains_and_tolerance(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    mock_sandbox = AsyncMock()
    mock_sandbox.get_active_simulators = MagicMock(return_value={})
    mock_sandbox.get_full_state.return_value = {"val": "hello world", "num": "invalid"}

    # Contains list
    node = {
        "expected_outcome": [
            {
                "target": "state",
                "property": "val",
                "expected": ["hello", "missing"],
                "mode": "contains",
            }
        ],
        "timeout": 0.1,
    }
    passed, _ = await session._verify_state_parity(node, mock_sandbox, [])
    assert passed is True

    # Contains str
    node = {
        "expected_outcome": [
            {"target": "state", "property": "val", "expected": "hello", "mode": "contains"}
        ],
        "timeout": 0.1,
    }
    passed, _ = await session._verify_state_parity(node, mock_sandbox, [])
    assert passed is True

    # Numerical tolerance exception branch
    node = {
        "expected_outcome": [
            {"target": "state", "property": "num", "expected": 1.0, "mode": "numerical_tolerance"}
        ],
        "timeout": 0.1,
    }
    passed, _ = await session._verify_state_parity(node, mock_sandbox, [])
    assert passed is False


@pytest.mark.asyncio
async def test_multiple_tools_interceptor_mutate(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    session.plugin_manager.trigger_interceptor = MagicMock(
        return_value={"tool_name": "redirected", "arguments": {"p": 1}}
    )
    mock_sandbox = AsyncMock()
    mock_sandbox.state = {}
    mock_sandbox.get_full_state.return_value = {}
    agent_resp = {"tool_names": ["t1"]}
    await session._handle_multiple_tools(
        1, agent_resp, mock_sandbox, [], {"used_tools": []}, MagicMock()
    )
    mock_sandbox.execute.assert_awaited_with("redirected", {"p": 1})


def test_get_last_env_message_non_env(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    assert session._get_last_env_message([{"role": "user"}]) == ""


@pytest.mark.asyncio
async def test_calculate_metrics_expected_outcome_resolution(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {
        "expected_outcome": [{"target": "message", "expected": "msg_success"}],
        "success_criteria": [{"metric": "exact_match"}],
    }

    received_criterion = None

    async def dummy_metric(criterion):
        nonlocal received_criterion
        received_criterion = criterion
        return 1.0

    with patch("eval_runner.metrics.MetricRegistry.get", return_value=dummy_metric):
        with patch("eval_runner.metrics.MetricRegistry.get_source", return_value="CORE"):
            await session._calculate_metrics(node, 1, 1, [], AsyncMock(), {"used_tools": []})
            assert received_criterion["expected"] == "msg_success"


@pytest.mark.asyncio
async def test_calculate_metrics_isolation(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {"success_criteria": [{"metric": "external_metric"}]}

    def dummy_metric(history):
        return 1.0

    with patch("eval_runner.metrics.MetricRegistry.get", return_value=dummy_metric):
        with patch("eval_runner.metrics.MetricRegistry.get_source", return_value="EXTERNAL_PLUGIN"):
            history = [{"role": "user"}]
            await session._calculate_metrics(node, 1, 1, history, AsyncMock(), {"used_tools": []})


def test_session_case_insensitive_protocol(base_scenario, tmp_path):
    base_scenario["metadata"] = {"agent": {"protocol": "HTTP"}}
    session = SessionManager("test_run_case_insensitive", base_scenario, log_root=tmp_path)
    assert session.session_metadata["protocol"] == "http"
    assert session.metadata["protocol"] == "http"


@pytest.mark.asyncio
async def test_adapter_resolution_case_insensitive():
    from eval_runner.engine import AgentAdapterRegistry

    # Check that HTTP protocol resolves without error by mocking call_agent's adapter func
    mock_func = AsyncMock(return_value={"action": "completed"})
    with patch.dict(AgentAdapterRegistry._adapters, {"http": mock_func}):
        res = await AgentAdapterRegistry.call_agent(
            protocol="HTTP", endpoint="http://test", message="hello", history=[]
        )
        assert res == {"action": "completed"}


@pytest.mark.asyncio
async def test_parallel_branch_state_and_history_isolation(tmp_path):
    """[P2.1/P2.2] Sibling parallel nodes must execute in isolated ExecutionInstanceContexts
    against dedicated sandbox forks without cross-branch history or state contamination.
    """
    scenario = {
        "id": "parallel_isolation_test",
        "run_id": "run_parallel_iso",
        "max_turns": 2,
        "metadata": {
            "agent": {"endpoint": "mock://test", "protocol": "http"},
            "execution_mode": "simulated",
        },
        "initial_state": {"counter": 0},
        "workflow": {
            "nodes": [
                {
                    "id": "root",
                    "task_description": "Root",
                    "success_criteria": [{"metric": "m_root", "threshold": 1.0}],
                },
                {
                    "id": "branch_left",
                    "task_description": "Left",
                    "success_criteria": [{"metric": "m_left", "threshold": 1.0}],
                },
                {
                    "id": "branch_right",
                    "task_description": "Right",
                    "success_criteria": [{"metric": "m_right", "threshold": 1.0}],
                },
            ],
            "edges": [
                {"from": "root", "to": "branch_left", "type": "parallel"},
                {"from": "root", "to": "branch_right", "type": "parallel"},
            ],
        },
        "tools": {
            "tool_l": {
                "output": {"status": "success"},
                "state_changes": [{"path": "left_val", "value": "L"}],
            },
            "tool_r": {
                "output": {"status": "success"},
                "state_changes": [{"path": "right_val", "value": "R"}],
            },
        },
    }

    session = SessionManager("run_parallel_iso", scenario, log_root=tmp_path)
    observed_histories = {}

    async def mock_call_agent(protocol, endpoint, message, history=None, turn_ctx=None, **kwargs):
        if history is not None:
            # Capture the exact history seen by this branch at call time
            observed_histories[message] = [h["content"] for h in history if "content" in h]
        return {"action": "completed", "tool_name": None}

    async def fake_calculate_metrics(node, attempt, turn, hist=None, sbox=None, acts=None):
        criteria = node.get("success_criteria", [])
        m_list = [
            {"id": c.get("metric"), "metric": c.get("metric"), "success": True} for c in criteria
        ]
        return {"status": "success", "metrics": m_list}

    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_call_agent):
        with patch.object(session, "_calculate_metrics", side_effect=fake_calculate_metrics):
            results = await session.execute_tasks(attempt_number=1)
            assert len(results) >= 3
            # Both parallel branches executed successfully
            assert any(r.get("scenario_node_id") == "branch_left" for r in results)
            assert any(r.get("scenario_node_id") == "branch_right" for r in results)

            # Neither branch saw each other's message history during execution
            left_hist = observed_histories.get("Left", [])
            right_hist = observed_histories.get("Right", [])
            assert "Right" not in left_hist
            assert "Left" not in right_hist


@pytest.mark.asyncio
async def test_parallel_branch_state_merge_order_is_deterministic(tmp_path):
    """[F1] Parallel branches merge state in deterministic (node_id, iteration) order."""
    scenario = {
        "id": "scenario_merge_determinism",
        "initial_state": {"target_key": "initial"},
        "workflow": {
            "nodes": [
                {
                    "id": "root",
                    "task_description": "Root",
                    "entry": True,
                    "success_criteria": [{"metric": "m1"}],
                },
                {"id": "branch_z", "task_description": "Z", "success_criteria": [{"metric": "m1"}]},
                {"id": "branch_a", "task_description": "A", "success_criteria": [{"metric": "m1"}]},
            ],
            "edges": [
                {"from": "root", "to": "branch_z", "type": "parallel"},
                {"from": "root", "to": "branch_a", "type": "parallel"},
            ],
        },
    }

    session = SessionManager("run_merge_det", scenario, log_root=tmp_path)
    merged_events = []
    session.event_bus.subscribe(
        lambda evt: merged_events.append(evt.data if hasattr(evt, "data") else evt)
    )

    async def mock_call_agent(protocol, endpoint, message, history=None, turn_ctx=None, **kwargs):
        # Branch Z writes "Z_WIN", Branch A writes "A_WIN" into its sandbox state
        if message == "Z":
            # Simulate artificial latency: branch Z completes slower
            await asyncio.sleep(0.02)
            turn_ctx.sandbox.state["target_key"] = "Z_WIN"
        elif message == "A":
            turn_ctx.sandbox.state["target_key"] = "A_WIN"
        return {"action": "completed", "tool_name": None}

    async def fake_calculate_metrics(node, attempt, turn, hist=None, sbox=None, acts=None):
        return {"status": "success", "metrics": [{"metric": "m1", "success": True}]}

    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_call_agent):
        with patch.object(session, "_calculate_metrics", side_effect=fake_calculate_metrics):
            results = await session.execute_tasks(attempt_number=1)
            assert len(results) >= 3

            # Merge order is sorted by (node_id, iteration): branch_a merges BEFORE branch_z
            # So branch_z's state write is applied last, resulting deterministically in "Z_WIN"
            assert session.sandbox.state["target_key"] == "Z_WIN"
            assert len(merged_events) >= 1
            # Verify exact recorded merge order
            assert any(
                "branch_a" in e.get("merge_order", [])[0]
                and "branch_z" in e.get("merge_order", [])[1]
                for e in merged_events
                if isinstance(e, dict) and len(e.get("merge_order", [])) == 2
            )


@pytest.mark.asyncio
async def test_tool_dependency_cycle_fails_closed(tmp_path):
    """[W5] Circular tool dependencies fail closed rather than serial fallback."""
    scenario = {
        "id": "scenario_deadlock",
        "workflow": {
            "nodes": [
                {
                    "id": "node1",
                    "task_description": "Deadlock tool test",
                    "success_criteria": [{"metric": "m1"}],
                }
            ]
        },
    }

    session = SessionManager("run_deadlock", scenario, log_root=tmp_path)
    mock_sandbox = AsyncMock()
    mock_sandbox.state = {}
    mock_sandbox.get_full_state = AsyncMock(return_value={})
    mock_sandbox.get_active_simulators = MagicMock(return_value={})
    tool_calls = [
        {"id": "tool_1", "tool": "file_writer", "params": {}, "depends_on": ["tool_2"]},
        {"id": "tool_2", "tool": "file_reader", "params": {}, "depends_on": ["tool_1"]},
    ]

    history = []
    actions = {"used_tools": []}
    turn_ctx = MagicMock()
    turn_ctx.span_context = None

    await session._handle_multiple_tools(
        turn=1,
        agent_response={"tool_calls": tool_calls},
        sandbox=mock_sandbox,
        history=history,
        actions=actions,
        turn_ctx=turn_ctx,
    )

    env_responses = next(h["content"] for h in history if h.get("role") == "environment")
    assert len(env_responses) == 2
    assert all(r.get("error_type") == "DEPENDENCY_CYCLE" for r in env_responses)
    assert all(r.get("status") == "failed" for r in env_responses)


def test_session_ingest_external_tool_receipts(base_scenario, tmp_path):
    """Verify ingestion of external tool execution receipts with SHA3-256 digests (P0-03)."""
    from eval_runner.events import CoreEvents

    session = SessionManager("test_run_receipts", base_scenario, log_root=tmp_path)
    events_emitted = []
    session.event_bus.subscribe(lambda e: events_emitted.append(e))

    # 1. Direct tool_calls with result
    agent_resp = {
        "action": "final_answer",
        "tool_calls": [
            {
                "tool": "clinical_lookup",
                "arguments": {"patient_id": "PAT-99"},
                "result": {"status": "eligible"},
            },
            {
                "function": {"name": "ehr_fetch"},
                "args": {"ehr_id": "EHR-123"},
                # result is None
            },
        ],
    }
    node = {"id": "node_audit"}
    receipts = session._ingest_external_tool_receipts(
        agent_response=agent_resp,
        turn=1,
        node=node,
        protocol="http",
        endpoint="http://agent.local",
    )
    assert len(receipts) == 2
    assert receipts[0]["tool"] == "clinical_lookup"
    assert receipts[0]["source"] == "external_agent_telemetry"
    assert receipts[0]["provenance"] == "reported"
    assert receipts[0]["receipt_hash"].startswith("sha3_256:")
    assert receipts[1]["tool"] == "ehr_fetch"

    # Check event bus emitted EXTERNAL_TOOL_CALL and EXTERNAL_TOOL_RESULT
    call_events = [e for e in events_emitted if e.name == CoreEvents.EXTERNAL_TOOL_CALL]
    result_events = [e for e in events_emitted if e.name == CoreEvents.EXTERNAL_TOOL_RESULT]
    assert len(call_events) == 2
    assert len(result_events) == 1

    # 2. Telemetry inside metadata.raw_response.intermediate_steps
    agent_resp_meta = {
        "action": "final_answer",
        "metadata": {
            "raw_response": {
                "intermediate_steps": [
                    {"name": "step_calc", "parameters": {"expr": "1+1"}, "output": "2"}
                ]
            }
        },
    }
    receipts_meta = session._ingest_external_tool_receipts(
        agent_response=agent_resp_meta,
        turn=2,
        node=node,
        protocol="openapi",
        endpoint="http://agent.local",
    )
    assert len(receipts_meta) == 1
    assert receipts_meta[0]["tool"] == "step_calc"

    # 3. Non-dict or empty response
    assert session._ingest_external_tool_receipts("raw_string", 3, node, "http", None) == []
    assert session._ingest_external_tool_receipts({}, 3, node, "http", None) == []

    # 4. Fallback on canonical json failure
    with patch(
        "agentv_runtime.canonical.canonical_json_encode", side_effect=Exception("encode fail")
    ):
        receipts_fallback = session._ingest_external_tool_receipts(
            agent_response={"tool_calls": [{"tool": "t_fb", "arguments": {}}]},
            turn=4,
            node=node,
            protocol="http",
            endpoint=None,
        )
        assert len(receipts_fallback) == 1
        assert receipts_fallback[0]["receipt_hash"].startswith("sha3_256:")


# --- Consolidated Session Execution & Behavioral Coverage ---


@pytest.mark.asyncio
async def test_session_psutil_missing(base_scenario, tmp_path):
    with patch("eval_runner.session.psutil", None):
        session = SessionManager("test_run", base_scenario, log_root=tmp_path)
        session._capture_telemetry()
        assert len(session.resource_telemetry) == 0


@pytest.mark.asyncio
async def test_session_metadata_update(base_scenario, tmp_path):
    session = SessionManager(
        "test_run", base_scenario, metadata={"extra": "data"}, log_root=tmp_path
    )
    assert session.session_metadata["extra"] == "data"


@pytest.mark.asyncio
async def test_session_plugin_load_failure(base_scenario, tmp_path):
    with patch("eval_runner.plugins.PluginManager.load", side_effect=Exception("Load fail")):
        from eval_runner import plugins

        with patch.object(
            plugins.manager, "provenance_map", {"P1": {"origin": "EXTERNAL", "path": "p"}}
        ):
            session = SessionManager("test_run", base_scenario, log_root=tmp_path)
            assert session.run_id == "test_run"


@pytest.mark.asyncio
async def test_session_plugin_archive_failure(base_scenario, tmp_path):
    with patch(
        "eval_runner.forensics.ForensicCollector.archive_plugin",
        side_effect=Exception("Archive fail"),
    ):
        from eval_runner import plugins

        with patch.object(
            plugins.manager, "provenance_map", {"P1": {"origin": "EXTERNAL", "path": "p"}}
        ):
            session = SessionManager("test_run", base_scenario, log_root=tmp_path)
            assert session.run_id == "test_run"


@pytest.mark.asyncio
async def test_session_empty_topology_and_trace_init(base_scenario, tmp_path):
    scenario = {"id": "empty", "workflow": {"nodes": []}}
    session = SessionManager("test_run", scenario, log_root=tmp_path)
    session.event_bus.emit("MANUAL_INIT", {})
    results = await session.execute_tasks(1)
    assert results[0]["status"] == "failure"


@pytest.mark.asyncio
async def test_session_unrecognized_action_and_throttle(base_scenario, tmp_path):
    with patch("eval_runner.config.EVAL_TURN_THROTTLE", 0.01):
        session = SessionManager("test_run", base_scenario, log_root=tmp_path)
        mock_sandbox = AsyncMock()
        mock_sandbox.state = {}
        mock_sandbox.get_full_state.return_value = {}

        with patch(
            "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
        ) as mock_agent:
            mock_agent.return_value = {"action": "jump"}
            with patch.object(
                session, "_calculate_metrics", new_callable=AsyncMock
            ) as mock_metrics:
                mock_metrics.return_value = {"metrics": []}
                res = await session._execute_node(
                    base_scenario["workflow"]["nodes"][0], 1, 0, mock_sandbox, [], {}
                )
                assert res["status"] == "failure"


@pytest.mark.asyncio
async def test_session_state_parity_exhaustive(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {
        "expected_outcome": [
            {"target": "shim:db.table", "expected": "ok"},
            {"target": "state", "property": "n", "expected": 1.0, "mode": "numerical_tolerance"},
            {"target": "message", "expected": "missing", "mode": "exact"},
        ],
        "timeout": 0.1,
    }
    mock_sandbox = MagicMock()
    mock_db = AsyncMock()
    mock_db.get_snapshot.return_value = "ok"
    mock_sandbox.get_active_simulators.return_value = {"db": mock_db}
    mock_sandbox.get_full_state = AsyncMock(return_value={"n": 2.0})

    res, _ev = await session._verify_state_parity(
        node, mock_sandbox, [{"role": "agent", "content": "not_missing"}]
    )
    assert res is False


@pytest.mark.asyncio
async def test_session_state_parity_regex_numerical_exhaustive(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {
        "expected_outcome": [
            {"target": "state", "property": "s", "expected": "regex:hello", "mode": "regex"},
            {"target": "state", "property": "v", "expected": 1.0, "mode": "numerical_tolerance"},
        ],
        "timeout": 0.1,
    }
    mock_sandbox = MagicMock()
    mock_sandbox.get_active_simulators.return_value = {}
    mock_sandbox.get_full_state = AsyncMock(return_value={"s": "hello world", "v": 1.000000000001})

    res, _ev = await session._verify_state_parity(node, mock_sandbox, [])
    assert res is True


@pytest.mark.asyncio
async def test_session_contains_assertion_list(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {
        "expected_outcome": [{"target": "message", "expected": ["a", "b"], "mode": "contains"}],
        "timeout": 0.1,
    }
    mock_sandbox = MagicMock()
    mock_sandbox.get_active_simulators.return_value = {}

    res, _ev = await session._verify_state_parity(
        node, mock_sandbox, [{"role": "agent", "content": "alpha"}]
    )
    assert res is True
    res, _ev = await session._verify_state_parity(
        node, mock_sandbox, [{"role": "agent", "content": "zzz"}]
    )
    assert res is False


@pytest.mark.asyncio
async def test_handle_multiple_tools_exhaustive(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    mock_sandbox = AsyncMock()
    mock_sandbox.state = {}
    mock_sandbox.execute.return_value = {"status": "success"}
    mock_sandbox.get_full_state.return_value = {}

    with patch.object(
        session.plugin_manager, "trigger_interceptor", return_value={"short_circuit_result": "fast"}
    ):
        agent_resp = {"tool_calls": [{"tool": "t1"}]}
        await session._handle_multiple_tools(
            1, agent_resp, mock_sandbox, [], {"used_tools": []}, MagicMock()
        )

    with patch.object(session.plugin_manager, "trigger_interceptor", return_value=False):
        await session._handle_multiple_tools(
            1, agent_resp, mock_sandbox, [], {"used_tools": []}, MagicMock()
        )


@pytest.mark.asyncio
async def test_calculate_metrics_exhaustive(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {
        "state_hygiene": {"rules": [{"path": "a", "op": "eq", "expected": 1}]},
        "expected_outcome": [{"target": "message", "expected": "goal"}],
        "expected_state_changes": [{"path": "a", "value": 1}],
        "success_criteria": [{"metric": "m1"}],
    }
    mock_sandbox = AsyncMock()
    mock_sandbox.state = {"a": 1}
    session.resource_telemetry = []

    async def metric(forensic_telemetry, expected, expected_state_changes):
        return (
            1.0
            if forensic_telemetry is not None and expected == "goal" and expected_state_changes
            else 0.0
        )

    with patch("eval_runner.metrics.MetricRegistry.get", return_value=metric):
        with patch("eval_runner.metrics.MetricRegistry.get_source", return_value="CORE"):
            res = await session._calculate_metrics(node, 1, 1, [], mock_sandbox, {"used_tools": []})
            assert res["metrics"][0]["score"] == 1.0


@pytest.mark.asyncio
async def test_session_history_duplication_fix(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    session.scenario["workflow"] = {
        "nodes": [
            {
                "id": "n1",
                "task_description": "t1",
                "state_hygiene": {"rules": [{"path": "__unset_probe__", "op": "not_exists"}]},
            },
            {
                "id": "n2",
                "task_description": "t2",
                "state_hygiene": {"rules": [{"path": "__unset_probe__", "op": "not_exists"}]},
            },
        ],
        "edges": [{"from": "n1", "to": "n2"}],
    }
    session.scenario["evaluation"] = {"metrics": [{"metric": "m1"}]}
    mock_sandbox = AsyncMock()
    mock_sandbox.state = {}
    mock_sandbox.get_full_state.return_value = {}
    mock_sandbox.setup = AsyncMock()
    mock_sandbox.teardown = AsyncMock()

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock_agent:
        mock_agent.return_value = {"action": "completed"}

        async def dummy_metric(*args, **kwargs):
            return 1.0

        with patch("eval_runner.metrics.MetricRegistry.get", return_value=dummy_metric):
            with patch("eval_runner.metrics.MetricRegistry.get_source", return_value="CORE"):
                results = await session.execute_tasks(1)
                global_res = next(r for r in results if r["task_id"] == "global_evaluation")
                assert len(global_res["conversation_history"]) == 4


@pytest.mark.asyncio
async def test_session_telemetry_error_branch(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    with patch("psutil.Process", side_effect=Exception("Fatal Tele")):
        session._capture_telemetry()


@pytest.mark.asyncio
async def test_session_turn_number_and_checkpoint_branches(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    session.turn_state_manager = None
    session.turn_number = 5
    assert session.turn_number == 5

    session.checkpoint_manager.load_latest_checkpoint = MagicMock(return_value=None)
    assert session.restore_from_checkpoint() is False

    chk_data = {
        "turn": "3",
        "metadata": {"custom_meta": 123},
        "session_metadata": {"extra_meta": 456},
    }
    assert session.restore_from_checkpoint(chk_data) is True
    assert session.turn_number == 3
    assert session.session_metadata["custom_meta"] == 123
    assert session.session_metadata["extra_meta"] == 456


@pytest.mark.asyncio
async def test_session_execute_tasks_cancellation_branch(base_scenario, tmp_path):
    cancel_evt = threading.Event()
    cancel_evt.set()

    session = SessionManager(
        "test_run", base_scenario, log_root=tmp_path, cancellation_event=cancel_evt
    )
    session.scenario["workflow"] = {
        "nodes": [
            {
                "id": "node_cancel",
                "task_description": "task",
                "state_hygiene": {"rules": [{"path": "__unset_probe__", "op": "not_exists"}]},
            }
        ],
    }

    mock_sandbox = AsyncMock()
    mock_sandbox.setup = AsyncMock()
    mock_sandbox.teardown = AsyncMock()

    with patch("eval_runner.session.ToolSandbox", return_value=mock_sandbox):
        results = await session.execute_tasks(1)
        assert results[0]["status"] == "aborted"
        assert results[0]["message"] == "Execution cancelled"


@pytest.mark.asyncio
async def test_session_hitl_non_interactive_approval_and_rejection(
    base_scenario, tmp_path, monkeypatch
):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    monkeypatch.setenv("FORCE_HITL_SUSPEND", "1")
    monkeypatch.delenv("CI", raising=False)

    class MockApproval:
        def __init__(self, action, response):
            self.action = action
            self.response = response

        async def wait(self):
            pass

    turn_ctx = MagicMock(task_id="task_1")

    with (
        patch("sys.stdin.isatty", return_value=False),
        patch.object(
            session.approval_manager,
            "request_approval",
            return_value=MockApproval("approve", "Approved by reviewer"),
        ),
    ):
        res = await session._handle_hitl(1, {"prompt": "Please confirm transfer"}, [], {}, turn_ctx)
        assert res == "Approved by reviewer"

    with (
        patch("sys.stdin.isatty", return_value=False),
        patch.object(
            session.approval_manager,
            "request_approval",
            return_value=MockApproval("reject", "Violates policy"),
        ),
    ):
        with pytest.raises(InterruptedError, match="Human reviewer rejected"):
            await session._handle_hitl(1, {"prompt": "Please confirm transfer"}, [], {}, turn_ctx)


def test_runner_dependency_graph_and_run_scenario():
    from agentv_runtime.config import ResolvedRuntimeConfig
    from eval_runner.runner import DefaultRunner, run_scenario

    runner = DefaultRunner()
    mock_store = MagicMock()
    mock_resolver = MagicMock()
    mock_artifact = MagicMock()
    mock_chk = MagicMock()
    mock_policy = MagicMock()
    mock_signer = MagicMock()

    runner.set_dependency_graph(
        run_store=mock_store,
        config_resolver=mock_resolver,
        artifact_store=mock_artifact,
        checkpoint_store=mock_chk,
        policy_evaluator=mock_policy,
        signing_backend=mock_signer,
        resolved_config={"timeout_seconds": 60},
    )
    assert runner.run_store is mock_store
    assert runner.artifact_store is mock_artifact

    cfg = ResolvedRuntimeConfig(timeout_seconds=90)
    runner.set_dependency_graph(resolved_config=cfg)
    assert runner.resolved_config.timeout_seconds == 90

    async def fake_run(*args, **kwargs):
        return MagicMock()

    with patch.object(runner, "run", side_effect=fake_run):
        res = run_scenario(
            {"id": "scen_test", "workflow": {"nodes": []}},
            runner=runner,
            run_store=mock_store,
        )
        assert res is not None


def test_session_save_and_restore_checkpoint(tmp_path):
    run_id = "run-checkpoint-001"
    scenario = {"id": "s1", "title": "Scenario 1", "turns": []}
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")

    session.turn_number = 3
    session.metadata["test_key"] = "test_val"

    ckpt_id = session.save_checkpoint(checkpoint_id="ckpt_1", metadata={"custom": "data"})
    assert ckpt_id is not None

    session.turn_number = 0
    ok = session.restore_from_checkpoint(checkpoint_data={"turn": 5})
    assert ok is True
    assert session.turn_number == 5


@pytest.mark.asyncio
async def test_session_reconciliation_live_and_hybrid(tmp_path):
    run_id = "run-reconciliation-001"
    scenario = {
        "id": "s_reconcile",
        "title": "Reconcile Scenario",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "prompt": "Hello",
                    "expected_outcome": [{"target": "state", "property": "counter", "expected": 1}],
                    "success_criteria": [{"metric": "exact_match", "expected": "completed"}],
                }
            ]
        },
    }
    session = SessionManager(
        run_id,
        scenario,
        metadata={"execution_mode": "live"},
        log_root=tmp_path / "runs",
    )
    session.execution_mode = ExecutionMode.LIVE

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch(
            "eval_runner.tool_sandbox.ToolSandbox.get_full_state",
            new_callable=AsyncMock,
            return_value={"counter": 1},
        ),
    ):
        results = await session.execute_tasks(1)
        assert len(results) >= 1
        node_res = next((r for r in results if r.get("task_id") == "node_1"), None)
        assert node_res is not None
        assert "reconciliation" in node_res
        assert node_res["reconciliation"]["execution_mode"] == "live"


@pytest.mark.asyncio
async def test_session_cancellation_branches(tmp_path):
    run_id = "run-cancel-001"
    scenario = {
        "id": "s_cancel",
        "title": "Cancel Scenario",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "prompt": "Hello",
                    "expected_outcome": [{"target": "state", "property": "ok", "expected": True}],
                    "success_criteria": [{"metric": "exact_match", "expected": "ok"}],
                }
            ]
        },
    }
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")
    session.cancellation_event = threading.Event()
    session.cancellation_event.set()

    results = await session.execute_tasks(1)
    assert len(results) >= 1

    session2 = SessionManager(run_id, scenario, log_root=tmp_path / "runs")
    session2.cancellation_event = threading.Event()
    node_def = {"id": "node_1", "prompt": "Hi"}
    session2.cancellation_event.set()
    res_turn = await session2._execute_node(
        node_def,
        1,
        0,
        session2.tool_sandbox if hasattr(session2, "tool_sandbox") else MagicMock(),
        [],
        {},
    )
    assert res_turn is not None


@pytest.mark.asyncio
async def test_session_state_capture_exceptions(tmp_path):
    run_id = "run-state-exc-001"
    scenario = {
        "id": "s_state_exc",
        "title": "State Exc Scenario",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "prompt": "Hello",
                    "expected_outcome": {"target": "state", "property": "counter", "expected": 1},
                    "success_criteria": [{"metric": "exact_match", "expected": "completed"}],
                }
            ]
        },
    }
    session = SessionManager(
        run_id,
        scenario,
        metadata={"execution_mode": "live"},
        log_root=tmp_path / "runs",
    )
    session.execution_mode = ExecutionMode.LIVE

    with (
        patch(
            "eval_runner.tool_sandbox.ToolSandbox.get_full_state",
            side_effect=RuntimeError("State capture error"),
        ),
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
    ):
        results = await session.execute_tasks(1)
        assert len(results) >= 1


def test_session_build_verification_decision_missing_oracles(tmp_path):
    run_id = "run-missing-oracles"
    scenario = {"id": "s_missing", "title": "Missing Oracles", "workflow": {"nodes": []}}
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")

    identity = ExecutionIdentity(
        evaluation_run_id=run_id,
        scenario_version_id="1.0.0",
        case_id="case_1",
        attempt_id="attempt_1",
        attempt_number=1,
    )
    outcome = WorkflowOutcome(status=WorkflowStatus.COMPLETED, reason="ok")
    task_results = [
        {
            "task_id": "node_1",
            "metrics": [{"metric": "other_metric", "passed": True}],
        }
    ]

    decision = session._build_verification_decision(
        outcome,
        task_results,
        identity,
        required_oracles=["node_1:sc:required_metric"],
    )
    assert decision["decision"] == "EVALUATION_INVALID"
    assert any(
        "Required oracle 'node_1:sc:required_metric' was missing" in b for b in decision["because"]
    )


@pytest.mark.asyncio
async def test_session_evaluate_consensus_model_shorthand(tmp_path):
    run_id = "run-judge-model"
    scenario = {"id": "s_judge", "title": "Judge", "workflow": {"nodes": []}}
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")
    session._last_transition_expectations = ["Hello Expected"]

    panel = [{"model": "gemini-3.7-flash", "provider": "mock"}]
    res = await session._evaluate_consensus({"consensus": {"panel": panel}}, [])
    assert res is not None


@pytest.mark.asyncio
async def test_session_consensus_inconclusive(tmp_path):
    run_id = "run-consensus-001"
    scenario = {
        "id": "s_consensus",
        "title": "Consensus Scenario",
        "evaluation": {"consensus": {"panel": ["judge_1", "judge_2"], "ija_threshold": 0.8}},
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "prompt": "Test",
                    "expected_outcome": [{"target": "state", "property": "ok", "expected": True}],
                    "success_criteria": [{"metric": "exact_match", "expected": "ok"}],
                }
            ]
        },
    }
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")

    inconclusive_consensus = {
        "status": "INCONCLUSIVE",
        "evaluated": True,
        "agreement": 0.5,
    }

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session,
            "_evaluate_consensus",
            new_callable=AsyncMock,
            return_value=inconclusive_consensus,
        ),
    ):
        results = await session.execute_tasks(1)
        verdict_node = next(
            r for r in results if r.get("synthetic") or r.get("verification_decision")
        )
        assert verdict_node["verification_decision"]["decision"] == "INCONCLUSIVE"
        assert any(
            "Judge panel disagreement" in b
            for b in verdict_node["verification_decision"]["because"]
        )


@pytest.mark.asyncio
async def test_session_fatal_forensic_exception(tmp_path):
    from eval_runner.workflow_interpreter import WorkflowInterpreter

    run_id = "run-fatal-001"
    scenario = {
        "id": "s_fatal",
        "title": "Fatal Scenario",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "prompt": "Test",
                    "expected_outcome": [{"target": "state", "property": "ok", "expected": True}],
                    "success_criteria": [{"metric": "exact_match", "expected": "ok"}],
                }
            ]
        },
    }
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")

    with patch.object(
        WorkflowInterpreter, "run", side_effect=RuntimeError("Unrecoverable Node Crash")
    ):
        crash_results = await session.execute_tasks(1)
        fatal_node = next(r for r in crash_results if r.get("triage_tag") == "FATAL_ENGINE_ERROR")
        assert "Forensic Exception during node execution" in fatal_node["message"]


def test_session_last_agent_summary_branches():
    h_str = [{"role": "user", "content": "hi"}, {"role": "agent", "content": "Agent replied hello"}]
    assert SessionManager._last_agent_summary(h_str) == "Agent replied hello"

    h_dict_summary = [{"role": "agent", "content": {"summary": "Summary text"}}]
    assert SessionManager._last_agent_summary(h_dict_summary) == "Summary text"

    h_dict_content = [{"role": "agent", "content": {"content": "Content text"}}]
    assert SessionManager._last_agent_summary(h_dict_content) == "Content text"

    h_dict_msg = [{"role": "agent", "content": {"message": "Message text"}}]
    assert SessionManager._last_agent_summary(h_dict_msg) == "Message text"

    assert SessionManager._last_agent_summary([]) == ""
    assert SessionManager._last_agent_summary([{"role": "user", "content": "hi"}]) == ""

    assert session_summary_test() == "ok"


def session_summary_test():
    s = SessionManager("r1", {"id": "s1", "title": "t"})
    res = s._extract_agent_summary([{"role": "agent", "content": "ok"}])
    return res


def test_interpreter_event_bridge_exception():
    mock_bus = MagicMock()
    mock_bus.emit.side_effect = RuntimeError("Bus failure")

    bridge = _InterpreterEventBridge(mock_bus)
    bridge.emit("test_event", {"data": 123})
    assert bridge.emission_failures == 1


@pytest.mark.asyncio
async def test_session_oracle_evaluation_matrix_outcomes(tmp_path):
    run_id = "run-oracle-matrix"
    scenario = {"id": "s_oracles", "title": "Oracle Matrix", "nodes": []}
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")

    v_invalid = NodeVerdict(
        execution="success", verification="invalid", policy="pass", parity="pass"
    )
    assert v_invalid.overall == "evaluation_invalid"

    v_policy_denied = NodeVerdict(
        execution="success", verification="pass", policy="denied", parity="pass"
    )
    assert v_policy_denied.overall == "policy_denied"

    v_parity_fail = NodeVerdict(
        execution="success", verification="pass", policy="pass", parity="fail"
    )
    assert v_parity_fail.overall == "parity_failed"

    forked = session.fork(history=[{"role": "agent", "content": "hi"}], sandbox_state={"k": "v"})
    assert forked.run_id == run_id
    assert forked.turn_state_manager.history[0]["content"] == "hi"

    node_oracle_test = {
        "id": "node_oracle_test",
        "prompt": "Test Prompt",
        "expected_outcome": {"target": "state", "property": "k", "expected": "v"},
        "success_criteria": [{"metric": "exact_match", "expected": "test"}],
    }

    oracle_unseen = CompiledOracle(
        oracle_id="node_oracle_test:sc:unseen",
        scenario_node_id="node_oracle_test",
        source_type="success_criteria",
        resolver="metrics_calculator",
        evidence_source="metrics",
        required=True,
    )
    plan_with_missing_req = CompiledEvaluationPlan(
        oracles={"node_oracle_test:sc:unseen": oracle_unseen},
        node_oracles={"node_oracle_test": [oracle_unseen]},
    )

    mock_sandbox = MagicMock()
    mock_sandbox.get_full_state = AsyncMock(return_value={"k": "v"})
    mock_sandbox.policy_decisions = [{"decision": "DENY", "id": "pol_deny_1"}]

    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        new_callable=AsyncMock,
        return_value={"action": "completed"},
    ):
        res = await session._execute_node(
            node_oracle_test,
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={"evaluation_plan": plan_with_missing_req},
        )
        assert res is not None

    oracle_na_disallowed = CompiledOracle(
        oracle_id="node_oracle_test:sc:exact_match",
        scenario_node_id="node_oracle_test",
        source_type="success_criteria",
        resolver="metrics_calculator",
        evidence_source="metrics",
        required=True,
        definition={"allow_not_applicable": False},
    )
    plan_na_disallowed = CompiledEvaluationPlan(
        oracles={"node_oracle_test:sc:exact_match": oracle_na_disallowed},
        node_oracles={"node_oracle_test": [oracle_na_disallowed]},
    )

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "exact_match", "outcome": "NOT_APPLICABLE"}],
            },
        ),
    ):
        res_na_disallowed = await session._execute_node(
            node_oracle_test,
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={"evaluation_plan": plan_na_disallowed},
        )
        assert res_na_disallowed is not None

    oracle_na_allowed = CompiledOracle(
        oracle_id="node_oracle_test:sc:exact_match",
        scenario_node_id="node_oracle_test",
        source_type="success_criteria",
        resolver="metrics_calculator",
        evidence_source="metrics",
        required=True,
        definition={"allow_not_applicable": True},
    )
    plan_na_allowed = CompiledEvaluationPlan(
        oracles={"node_oracle_test:sc:exact_match": oracle_na_allowed},
        node_oracles={"node_oracle_test": [oracle_na_allowed]},
    )

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "exact_match", "outcome": "NOT_APPLICABLE"}],
            },
        ),
    ):
        res_na_ok = await session._execute_node(
            node_oracle_test,
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={"evaluation_plan": plan_na_allowed},
        )
        assert res_na_ok is not None

    mock_sandbox_policy_fail = MagicMock()
    mock_sandbox_policy_fail.get_full_state = AsyncMock(return_value={"k": "v"})
    mock_sandbox_policy_fail.policy_decisions = []

    async def _add_policy_denial(*args, **kwargs):
        mock_sandbox_policy_fail.policy_decisions.append({"decision": "denied", "id": "pol_deny_1"})
        return {"action": "completed"}

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            side_effect=_add_policy_denial,
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "exact_match", "outcome": "PASS"}],
            },
        ),
    ):
        res_pol_denied = await session._execute_node(
            node_oracle_test,
            1,
            0,
            mock_sandbox_policy_fail,
            [],
            {},
            execution_context={},
        )
        assert res_pol_denied.get("triage_tag") == "POLICY_DENIED"

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session,
            "_verify_state_parity",
            new_callable=AsyncMock,
            return_value=(False, [{"passed": False, "assertion": {"target": "state"}}]),
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "exact_match", "outcome": "PASS"}],
            },
        ),
    ):
        res_parity_fail = await session._execute_node(
            node_oracle_test,
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={},
        )
        assert res_parity_fail is not None

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [
                    {"metric": "exact_match", "outcome": "FAIL", "requiredness": "REQUIRED"},
                ],
            },
        ),
    ):
        res_fallback = await session._execute_node(
            {"id": "node_simple", "prompt": "Hi"},
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={},
        )
        assert res_fallback is not None

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [
                    {
                        "metric": "exact_match",
                        "outcome": "NOT_APPLICABLE",
                        "requiredness": "REQUIRED",
                    },
                ],
            },
        ),
    ):
        res_all_na = await session._execute_node(
            {"id": "node_simple", "prompt": "Hi"},
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={},
        )
        assert res_all_na is not None

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "exact_match", "outcome": "NOT_APPLICABLE"}],
            },
        ),
    ):
        res_plan_all_na = await session._execute_node(
            node_oracle_test,
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={"evaluation_plan": plan_na_allowed},
        )
        assert res_plan_all_na.get("node_verdict", {}).get("verification") == "not_applicable"

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [
                    {"metric": "exact_match", "outcome": "FAIL", "requiredness": "OPTIONAL"},
                ],
            },
        ),
    ):
        res_optional_fail = await session._execute_node(
            {"id": "node_simple", "prompt": "Hi"},
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={},
        )
        assert res_optional_fail.get("node_verdict", {}).get("verification") == "pass"

    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            session, "_verify_state_parity", new_callable=AsyncMock, return_value=(True, [])
        ),
        patch.object(
            session.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [],
            },
        ),
    ):
        res_empty = await session._execute_node(
            {"id": "node_simple", "prompt": "Hi"},
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={},
        )
        assert res_empty.get("node_verdict", {}).get("verification") == "not_applicable"


@pytest.mark.asyncio
async def test_session_executor_cancellation_and_empty_results(tmp_path):
    run_id = "run-cancel-executor"
    scenario = {
        "id": "s_cancel_exec",
        "title": "Cancel Exec",
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "prompt": "Test",
                    "success_criteria": [{"metric": "exact_match", "expected": "ok"}],
                }
            ]
        },
    }
    session = SessionManager(run_id, scenario, log_root=tmp_path / "runs")
    session.cancellation_event = threading.Event()
    session.cancellation_event.set()

    results = await session.execute_tasks(1)
    assert len(results) >= 1

    session2 = SessionManager("run-empty-results", scenario, log_root=tmp_path / "runs")

    mock_outcome = WorkflowOutcome(status=WorkflowStatus.COMPLETED, reason="ok")
    with patch(
        "eval_runner.workflow_interpreter.WorkflowInterpreter.run",
        new_callable=AsyncMock,
        return_value=([], mock_outcome),
    ):
        results_empty = await session2.execute_tasks(1)
        assert len(results_empty) >= 1
        assert any(r.get("task_id") == "workflow_verdict" for r in results_empty)


def test_session_psutil_import_error():
    import importlib
    import sys

    with patch.dict(sys.modules, {"psutil": None}):
        import eval_runner.session as sess_mod

        try:
            importlib.reload(sess_mod)
            assert sess_mod.psutil is None
        finally:
            importlib.reload(sess_mod)


def test_session_init_execution_mode_and_isolate_events(tmp_path):
    with pytest.raises(ValueError, match="Invalid execution_mode 'unsupported_mode'"):
        SessionManager(
            "run_inv", {}, metadata={"execution_mode": "unsupported_mode"}, log_root=tmp_path
        )

    sess_iso = SessionManager("run_iso", {}, metadata={"isolate_events": True}, log_root=tmp_path)
    assert sess_iso.metadata.get("isolate_events") is True

    chk = {"turn": 2, "metadata": {"resumed": True}}
    sess_chk = SessionManager("run_chk", {}, resumption_checkpoint=chk, log_root=tmp_path)
    assert sess_chk.turn_number == 2


def test_session_init_workflow_list_and_mutations(tmp_path):
    scen = {
        "id": "scen_wf_list",
        "workflow": [
            {
                "id": "node_mut",
                "mutations": [{"type": "prompt_injection"}],
            }
        ],
    }
    sess = SessionManager("run_mut_list", scen, log_root=tmp_path)
    assert hasattr(sess, "mutation_plugin")


def test_session_routing_capabilities_and_socket(tmp_path, monkeypatch):
    from eval_runner.routing import RoutingRegistry

    with patch.object(
        RoutingRegistry,
        "resolve",
        return_value={"protocol": "ws", "endpoint": "ws://resolved", "metadata": {"deep_sync": 1}},
    ):
        sess = SessionManager(
            "run_sticky",
            {"id": "scen_sticky", "capabilities": ["cap_test"]},
            metadata={"protocol": "grpc", "agent": "http://sticky.local"},
            log_root=tmp_path,
        )
        assert sess.session_metadata["protocol"] == "grpc"
        assert sess.session_metadata["agent"] == "http://sticky.local"
        assert sess.session_metadata["deep_sync"] == 1

    scen_non_sticky = {
        "id": "scen_non_sticky",
        "capabilities": ["cap_test"],
    }
    with patch.object(
        RoutingRegistry,
        "resolve",
        return_value={"protocol": "ws", "endpoint": "ws://resolved"},
    ):
        sess_dyn = SessionManager("run_dyn", scen_non_sticky, log_root=tmp_path)
        assert sess_dyn.session_metadata["protocol"] == "ws"
        assert sess_dyn.session_metadata["agent"] == "ws://resolved"
        assert "deep_sync" not in sess_dyn.session_metadata

    with patch.object(
        RoutingRegistry,
        "resolve",
        return_value=None,
    ):
        sess_none = SessionManager("run_none", scen_non_sticky, log_root=tmp_path)
        assert sess_none.session_metadata["protocol"] == "http"

    monkeypatch.setenv("AGENT_SOCKET_ADDR", "ipc:///tmp/agent.sock")
    scen_socket = {"id": "scen_socket", "metadata": {"agent": {"protocol": "socket"}}}
    sess_sock = SessionManager("run_sock", scen_socket, log_root=tmp_path)
    assert sess_sock.metadata["agent"] == "ipc:///tmp/agent.sock"

    monkeypatch.setenv("AGENT_LOCAL_CMD", "python -m agent")
    scen_local = {"id": "scen_local", "metadata": {"agent": {"protocol": "local"}}}
    sess_local = SessionManager("run_local", scen_local, log_root=tmp_path)
    assert sess_local.metadata["agent"] == "python -m agent"

    scen_non_str = {"id": "scen_proto"}
    sess_non_str = SessionManager(
        "run_non_str", scen_non_str, metadata={"protocol": 123}, log_root=tmp_path
    )
    assert sess_non_str.metadata["protocol"] == 123

    scen_custom = {"id": "scen_cust"}
    sess_custom = SessionManager(
        "run_cust", scen_custom, metadata={"protocol": "custom_proto"}, log_root=tmp_path
    )
    assert sess_custom.metadata["agent"] is None


@pytest.mark.asyncio
async def test_session_batch_complete_and_executor_cancellation(tmp_path):
    scen = {
        "id": "s_batch",
        "workflow": {
            "nodes": [
                {"id": "n1", "task_description": "task 1", "expected_outcome": []},
                {"id": "n2", "task_description": "task 2", "expected_outcome": []},
            ],
            "edges": [],
        },
    }
    sess = SessionManager("run_batch", scen, log_root=tmp_path)

    cancel_evt = threading.Event()
    sess.cancellation_event = cancel_evt
    cancel_evt.set()

    mock_sandbox = AsyncMock()
    mock_sandbox.setup = AsyncMock()
    mock_sandbox.teardown = AsyncMock()
    mock_sandbox.merge_branch_state = MagicMock()
    mock_sandbox.state = {"a": 1}

    with patch("eval_runner.session.ToolSandbox", return_value=mock_sandbox):
        results = await sess.execute_tasks(1)
        assert len(results) >= 1


@pytest.mark.asyncio
async def test_session_evaluate_consensus_comprehensive(tmp_path):
    sess = SessionManager("run_cons_comp", {"id": "s_c"}, log_root=tmp_path)

    sess._last_transition_expectations = []
    res_no_exp = await sess._evaluate_consensus({"consensus": {"judge_panel": ["j1"]}}, [])
    assert res_no_exp["evaluated"] is False
    assert "No expected outcome" in res_no_exp["reason"]

    sess._last_transition_expectations = None
    assert sess._primary_expected_message() == ""

    sess._last_transition_expectations = ["Expected Output"]

    panel_shorthand = [
        {"name": "valid_j", "provider": "mock", "model": "mock-model"},
        {"name": "uncreatable_j", "provider": "invalid_provider_xyz_123"},
    ]

    def _mock_provider_create(provider_name):
        if provider_name == "invalid_provider_xyz_123":
            raise RuntimeError("Provider uncreatable")
        return MagicMock()

    with (
        patch(
            "eval_runner.llm_providers.LLMProviderFactory.create", side_effect=_mock_provider_create
        ),
        patch(
            "eval_runner.metrics.MetricRegistry.get",
            return_value=AsyncMock(return_value=1.0),
        ),
    ):
        res_short = await sess._evaluate_consensus(
            {"consensus": {"judge_panel": panel_shorthand, "min_judges": 2}},
            [],
        )
        assert res_short["evaluated"] is False
        assert "Quorum not met" in res_short["reason"]

    panel_two = ["judge_a", "judge_b"]
    with (
        patch("eval_runner.llm_providers.LLMProviderFactory.create", return_value=MagicMock()),
        patch(
            "eval_runner.metrics.MetricRegistry.get",
            return_value=AsyncMock(return_value=0.9),
        ),
    ):
        res_unan_pass = await sess._evaluate_consensus(
            {
                "consensus": {
                    "judge_panel": panel_two,
                    "strategy": "Absolute_Unanimity",
                    "min_judges": 2,
                }
            },
            [],
        )
        assert res_unan_pass["evaluated"] is True
        assert res_unan_pass["verdict"] == "PASS"

    scores = iter([0.9, 0.4])
    with (
        patch("eval_runner.llm_providers.LLMProviderFactory.create", return_value=MagicMock()),
        patch(
            "eval_runner.metrics.MetricRegistry.get",
            return_value=AsyncMock(side_effect=lambda *a, **k: next(scores)),
        ),
    ):
        res_unan_fail = await sess._evaluate_consensus(
            {
                "consensus": {
                    "judge_panel": panel_two,
                    "strategy": "Absolute_Unanimity",
                    "min_judges": 2,
                }
            },
            [],
        )
        assert res_unan_fail["evaluated"] is True
        assert res_unan_fail["verdict"] == "INCONCLUSIVE"

    with (
        patch("eval_runner.llm_providers.LLMProviderFactory.create", return_value=MagicMock()),
        patch(
            "eval_runner.metrics.MetricRegistry.get",
            return_value=AsyncMock(return_value=0.8),
        ),
    ):
        res_wt_pass = await sess._evaluate_consensus(
            {
                "consensus": {
                    "judge_panel": panel_two,
                    "strategy": "Weighted_Average",
                    "min_judges": 2,
                }
            },
            [],
        )
        assert res_wt_pass["evaluated"] is True
        assert res_wt_pass["verdict"] == "PASS"

    with (
        patch("eval_runner.llm_providers.LLMProviderFactory.create", return_value=MagicMock()),
        patch(
            "eval_runner.metrics.MetricRegistry.get",
            return_value=AsyncMock(return_value=0.2),
        ),
    ):
        res_wt_fail = await sess._evaluate_consensus(
            {
                "consensus": {
                    "judge_panel": panel_two,
                    "strategy": "Weighted_Average",
                    "min_judges": 2,
                }
            },
            [],
        )
        assert res_wt_fail["evaluated"] is True
        assert res_wt_fail["verdict"] == "FAIL"

    with (
        patch("eval_runner.llm_providers.LLMProviderFactory.create", return_value=MagicMock()),
        patch(
            "eval_runner.metrics.MetricRegistry.get",
            return_value=AsyncMock(return_value=0.9),
        ),
    ):
        res_unknown = await sess._evaluate_consensus(
            {
                "consensus": {
                    "judge_panel": panel_two,
                    "strategy": "Super_Majority",
                    "min_judges": 2,
                }
            },
            [],
        )
        assert res_unknown["evaluated"] is False
        assert "Unknown consensus strategy" in res_unknown["reason"]

    scores_diff = iter([1.0, 0.0])
    with (
        patch("eval_runner.llm_providers.LLMProviderFactory.create", return_value=MagicMock()),
        patch(
            "eval_runner.metrics.MetricRegistry.get",
            return_value=AsyncMock(side_effect=lambda *a, **k: next(scores_diff)),
        ),
    ):
        res_ija = await sess._evaluate_consensus(
            {
                "consensus": {
                    "judge_panel": panel_two,
                    "strategy": "Majority_Vote",
                    "min_judges": 2,
                    "ija_threshold": 0.9,
                }
            },
            [],
        )
        assert res_ija["evaluated"] is True
        assert res_ija["status"] == "INCONCLUSIVE"
        assert "certification withheld pending human review" in res_ija["reason"]


def test_session_build_verification_decision_branches(tmp_path):
    sess = SessionManager("run_vd_branches", {"id": "s_vd"}, log_root=tmp_path)
    identity = ExecutionIdentity(
        evaluation_run_id="run_vd_branches",
        scenario_version_id="1.0.0",
        case_id="c1",
        attempt_id="att1",
        attempt_number=1,
    )

    outcome = WorkflowOutcome(status=WorkflowStatus.COMPLETED, reason="ok")
    task_res = [
        {"task_id": "n1", "metrics": [{"metric": "oracle_1", "success": True, "passed": True}]}
    ]
    dec_present = sess._build_verification_decision(
        outcome, task_res, identity, required_oracles=["oracle_1"]
    )
    assert dec_present["decision"] == "PASS"

    outcome_invalid = WorkflowOutcome(status=WorkflowStatus.COMPLETED, reason="corrupt state")
    outcome_invalid.evaluation_valid = False
    dec_invalid = sess._build_verification_decision(
        outcome_invalid, task_res, identity, required_oracles=["oracle_1"]
    )
    assert dec_invalid["decision"] == "EVALUATION_INVALID"
    assert any("Workflow execution invalid" in b for b in dec_invalid["because"])


@pytest.mark.asyncio
async def test_session_turn_loop_cancellation_and_hitl_unresolved(tmp_path):
    scen = {
        "id": "s_tl",
        "workflow": {
            "nodes": [
                {"id": "n1", "task_description": "task", "expected_outcome": []},
            ],
            "edges": [],
        },
    }
    sess = SessionManager("run_tl", scen, log_root=tmp_path)
    sess.max_turns = 3

    mock_sandbox = AsyncMock()
    mock_sandbox.state = {}
    mock_sandbox.get_full_state.return_value = {}

    async def _call_agent_cancel(*a, **k):
        sess.cancellation_event = threading.Event()
        sess.cancellation_event.set()
        return {"action": "processing"}

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent",
        new_callable=AsyncMock,
        side_effect=_call_agent_cancel,
    ):
        res_cancel = await sess._execute_node(
            scen["workflow"]["nodes"][0], 1, 0, mock_sandbox, [], {}
        )
        assert res_cancel is not None

    sess_zero = SessionManager("run_zero", scen, log_root=tmp_path)
    sess_zero.max_turns = 0
    res_zero = await sess_zero._execute_node(
        scen["workflow"]["nodes"][0], 1, 0, mock_sandbox, [], {}
    )
    assert res_zero["status"] == "failure"

    scen_hitl = {
        "id": "s_hitl",
        "workflow": {
            "nodes": [
                {
                    "id": "n1",
                    "task_description": "task",
                    "expected_outcome": [{"target": "state", "property": "k", "expected": "v"}],
                },
            ],
            "edges": [],
        },
    }
    sess_hitl = SessionManager("run_hitl_unres", scen_hitl, log_root=tmp_path)
    mock_sandbox_hitl = AsyncMock()
    mock_sandbox_hitl.state = {"k": "v"}
    mock_sandbox_hitl.get_full_state.return_value = {"k": "v"}
    mock_sandbox_hitl.policy_decisions = []

    async def _hitl_unres_handler(*a, **k):
        sess_hitl._hitl_unresolved = True
        return "unresolved"

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent",
        new_callable=AsyncMock,
        return_value={"action": "hitl_pause"},
    ):
        with patch.object(sess_hitl, "_handle_hitl", side_effect=_hitl_unres_handler):
            res_unres = await sess_hitl._execute_node(
                scen_hitl["workflow"]["nodes"][0], 1, 0, mock_sandbox_hitl, [], {}
            )
            assert res_unres["triage_tag"] == "HITL_UNRESOLVED"


@pytest.mark.asyncio
async def test_session_node_verdict_and_reporting_branches(tmp_path):
    sess = SessionManager("run_nv", {"id": "s_nv"}, log_root=tmp_path)
    mock_sandbox = MagicMock()
    mock_sandbox.get_full_state = AsyncMock(return_value={"k": "v"})
    mock_sandbox.policy_decisions = []

    oracle_unknown = CompiledOracle(
        oracle_id="node_nv:sc:unknown_out",
        scenario_node_id="node_nv",
        source_type="success_criteria",
        resolver="metrics_calculator",
        evidence_source="metrics",
        required=True,
    )
    plan_unknown = CompiledEvaluationPlan(
        oracles={"node_nv:sc:unknown_out": oracle_unknown},
        node_oracles={"node_nv": [oracle_unknown]},
    )

    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        new_callable=AsyncMock,
        return_value={"action": "completed"},
    ):
        with patch.object(
            sess.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "unknown_out", "outcome": "CUSTOM_OUTCOME"}],
            },
        ):
            res_unk = await sess._execute_node(
                {"id": "node_nv", "prompt": "test"},
                1,
                0,
                mock_sandbox,
                [],
                {},
                execution_context={"evaluation_plan": plan_unknown},
            )
            assert res_unk is not None

    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        new_callable=AsyncMock,
        return_value={"action": "completed"},
    ):
        with patch.object(
            sess.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [
                    {"metric": "m1", "outcome": "CUSTOM_OUTCOME", "requiredness": "REQUIRED"}
                ],
            },
        ):
            res_unk_fb = await sess._execute_node(
                {"id": "node_simple", "prompt": "test"},
                1,
                0,
                mock_sandbox,
                [],
                {},
                execution_context={},
            )
            assert res_unk_fb is not None

    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        new_callable=AsyncMock,
        return_value={"action": "completed"},
    ):
        with patch.object(
            sess.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [
                    {"metric": "m_na", "outcome": "NOT_APPLICABLE", "requiredness": "REQUIRED"}
                ],
            },
        ):
            res_all_na = await sess._execute_node(
                {"id": "node_simple", "prompt": "test"},
                1,
                0,
                mock_sandbox,
                [],
                {},
                execution_context={},
            )
            assert res_all_na.get("node_verdict", {}).get("verification") == "not_applicable"

    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        new_callable=AsyncMock,
        return_value={"action": "completed"},
    ):
        with patch.object(
            sess.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [
                    {"metric": "m_pass", "outcome": "PASS", "requiredness": "REQUIRED"},
                    {"metric": "m_cust", "outcome": "CUSTOM_OTHER", "requiredness": "REQUIRED"},
                ],
            },
        ):
            res_fail_branch = await sess._execute_node(
                {"id": "node_simple", "prompt": "test"},
                1,
                0,
                mock_sandbox,
                [],
                {},
                execution_context={},
            )
            assert res_fail_branch.get("node_verdict", {}).get("verification") == "fail"

    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        new_callable=AsyncMock,
        return_value={"action": "completed"},
    ):
        with patch.object(
            sess.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "m_no_out", "score": 0.5}],
            },
        ):
            res_no_out = await sess._execute_node(
                {"id": "node_simple", "prompt": "test"},
                1,
                0,
                mock_sandbox,
                [],
                {},
                execution_context={},
            )
            assert res_no_out is not None

    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        new_callable=AsyncMock,
        return_value={"action": "completed"},
    ):
        with patch.object(
            sess.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "m_pass", "outcome": "PASS", "requiredness": "REQUIRED"}],
                "triage_tag": "SUCCESS_TAG",
                "message": "Notice message",
            },
        ):
            node_def = {"id": "node_succ", "prompt": "test"}
            res_succ = await sess._execute_node(
                node_def,
                1,
                0,
                mock_sandbox,
                [],
                {},
                execution_context={},
            )
            assert res_succ["status"] == "success"

    node_parity_fail = {
        "id": "node_pf",
        "prompt": "Test Prompt",
        "success_criteria": [{"metric": "m1"}],
    }
    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            sess,
            "_verify_state_parity",
            new_callable=AsyncMock,
            return_value=(False, [{"passed": False, "assertion": {"target": "__state_parity__"}}]),
        ),
        patch.object(
            sess.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [{"metric": "m1", "outcome": "PASS", "requiredness": "REQUIRED"}],
            },
        ),
    ):
        res_parity_fail = await sess._execute_node(
            node_parity_fail,
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={},
        )
        assert res_parity_fail.get("node_verdict", {}).get("overall") == "parity_failed"
        assert "State parity verification failed" in res_parity_fail.get("message", "")

    oracle_req_pass1 = CompiledOracle(
        oracle_id="node_multi:sc:m1",
        scenario_node_id="node_multi",
        source_type="success_criteria",
        resolver="metrics_calculator",
        evidence_source="metrics",
        required=True,
    )
    oracle_req_pass2 = CompiledOracle(
        oracle_id="node_multi:sc:m2",
        scenario_node_id="node_multi",
        source_type="success_criteria",
        resolver="metrics_calculator",
        evidence_source="metrics",
        required=True,
    )
    plan_multi = CompiledEvaluationPlan(
        oracles={
            "node_multi:sc:m1": oracle_req_pass1,
            "node_multi:sc:m2": oracle_req_pass2,
        },
        node_oracles={"node_multi": [oracle_req_pass1, oracle_req_pass2]},
    )
    node_multi = {
        "id": "node_multi",
        "prompt": "Test Prompt",
        "expected_outcome": [{"target": "state", "property": "k", "expected": "v"}],
        "success_criteria": [
            {"metric": "m1", "expected": "a"},
            {"metric": "m2", "expected": "b"},
        ],
    }
    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            sess.metrics_calculator,
            "calculate_metrics",
            new_callable=AsyncMock,
            return_value={
                "evaluation_valid": True,
                "metrics": [
                    {"metric": "m1", "outcome": "PASS", "requiredness": "REQUIRED"},
                    {"metric": "m2", "outcome": "PASS", "requiredness": "REQUIRED"},
                ],
            },
        ),
    ):
        res_multi = await sess._execute_node(
            node_multi,
            1,
            0,
            mock_sandbox,
            [],
            {},
            execution_context={"evaluation_plan": plan_multi},
        )
        assert res_multi.get("node_verdict", {}).get("verification") == "pass"


@pytest.mark.asyncio
async def test_session_teardown_and_external_receipts_edge_cases(tmp_path):
    sess = SessionManager("run_td", {"id": "s_td"}, log_root=tmp_path)

    mock_sb = AsyncMock()
    jail_dir = tmp_path / "mock_jail"
    jail_dir.mkdir()
    mock_sb.terminal_jail = str(jail_dir)
    await sess.teardown(mock_sb)

    (jail_dir / "terminal.log").write_text("log content", encoding="utf-8")
    await sess.teardown(mock_sb)

    mock_sb_no_jail = AsyncMock()
    del mock_sb_no_jail.terminal_jail
    await sess.teardown(mock_sb_no_jail)

    node = {"id": "n1"}
    resp_raw_non_dict = {"metadata": {"raw_response": "not_a_dict"}}
    assert sess._ingest_external_tool_receipts(resp_raw_non_dict, 1, node, "http", None) == []

    resp_steps = {
        "metadata": {
            "raw_response": {"steps": ["non_dict_call", {"tool": "t_step", "arguments": {}}]}
        }
    }

    sess.forensics.record_external_receipts = MagicMock()
    rec_steps = sess._ingest_external_tool_receipts(resp_steps, 1, node, "http", None)
    assert len(rec_steps) == 1
    sess.forensics.record_external_receipts.assert_called_once()

    del sess.forensics.record_external_receipts
    rec_no_rec = sess._ingest_external_tool_receipts(resp_steps, 1, node, "http", None)
    assert len(rec_no_rec) == 1

    sess_no_forensics = SessionManager("run_nf", {"id": "s_nf"}, log_root=tmp_path)
    del sess_no_forensics.forensics
    rec_nf = sess_no_forensics._ingest_external_tool_receipts(resp_steps, 1, node, "http", None)
    assert len(rec_nf) == 1


@pytest.mark.asyncio
async def test_session_hitl_cli_suspension_and_empty_response(tmp_path, monkeypatch):
    sess = SessionManager("run_hitl_cli", {"id": "s_h"}, log_root=tmp_path)

    monkeypatch.setenv("FORCE_HITL_SUSPEND", "1")
    monkeypatch.delenv("CI", raising=False)
    turn_ctx = MagicMock(task_id="task_1")

    class MockApprove:
        def __init__(self):
            self.action = "approve"
            self.response = "OK"

        async def wait(self):
            pass

    with (
        patch("sys.stdin.isatty", return_value=False),
        patch.object(
            sess.approval_manager,
            "create_durable_request",
            return_value=MagicMock(approval_token="tok_1"),
        ),
        patch.object(sess.approval_manager, "resolve_durable_request") as mock_resolve,
        patch.object(sess.approval_manager, "request_approval", return_value=MockApprove()),
    ):
        res = await sess._handle_hitl(1, {}, [], {}, turn_ctx)
        assert res == "OK"
        mock_resolve.assert_called_once()

    monkeypatch.setenv("AGENTV_CLI_HITL_SUSPEND", "1")
    with patch.object(
        sess.approval_manager,
        "create_durable_request",
        return_value=MagicMock(approval_token="tok_suspend"),
    ):
        with pytest.raises(InterruptedError, match="paused for approval"):
            await sess._handle_hitl(1, {"action": "hitl_pause"}, [], {}, turn_ctx)


@pytest.mark.asyncio
async def test_session_executor_cancellation(tmp_path):
    scen = {
        "id": "s_ce",
        "workflow": {
            "nodes": [
                {
                    "id": "n1",
                    "task_description": "task 1",
                    "expected_outcome": [{"target": "state", "property": "k", "expected": "v"}],
                },
            ],
            "edges": [],
        },
    }
    sess = SessionManager("run_ce", scen, log_root=tmp_path)
    cancel_evt = threading.Event()
    sess.cancellation_event = cancel_evt

    from eval_runner.workflow_interpreter import WorkflowInterpreter

    captured_interpreter = []
    orig_init = WorkflowInterpreter.__init__

    def _mock_init(self, *a, **k):
        captured_interpreter.append(self)
        orig_init(self, *a, **k)

    async def _mock_run(executor):
        cancel_evt.set()
        node_ir = MagicMock()
        node_ir.node_id = "n1"
        node_ir.definition = scen["workflow"]["nodes"][0]
        res = await executor(node_ir, "exec_ce", None)
        assert res["status"] == "aborted"
        if captured_interpreter and getattr(captured_interpreter[0], "on_batch_complete", None):
            captured_interpreter[0].on_batch_complete(["unknown_eid"])
            captured_interpreter[0].on_batch_complete([])
        return [res], WorkflowOutcome(status=WorkflowStatus.ABORTED, reason="cancelled")

    with (
        patch.object(WorkflowInterpreter, "__init__", _mock_init),
        patch("eval_runner.workflow_interpreter.WorkflowInterpreter.run", side_effect=_mock_run),
    ):
        results = await sess.execute_tasks(1)
        assert any(r.get("status") == "aborted" for r in results)


@pytest.mark.asyncio
async def test_session_consensus_pass_and_model_only(tmp_path):
    scen = {
        "id": "s_cp",
        "evaluation": {"consensus": {"panel": ["j1"], "strategy": "Majority_Vote"}},
        "workflow": {
            "nodes": [
                {
                    "id": "n1",
                    "prompt": "hi",
                    "expected_outcome": [{"target": "state", "property": "k", "expected": "v"}],
                    "success_criteria": [{"metric": "exact_match", "expected": "ok"}],
                }
            ]
        },
    }
    sess = SessionManager("run_cp", scen, log_root=tmp_path)
    pass_consensus = {"status": "PASS", "evaluated": True, "agreement": 1.0}
    with (
        patch(
            "eval_runner.session.AgentAdapterRegistry.call_agent",
            new_callable=AsyncMock,
            return_value={"action": "completed"},
        ),
        patch.object(
            sess, "_evaluate_consensus", new_callable=AsyncMock, return_value=pass_consensus
        ),
        patch(
            "eval_runner.tool_sandbox.ToolSandbox.get_full_state",
            new_callable=AsyncMock,
            return_value={"k": "v"},
        ),
    ):
        results = await sess.execute_tasks(1)
        verdict_target = next(
            r for r in results if r.get("synthetic") or r.get("verification_decision")
        )
        assert verdict_target["verification_decision"]["consensus"]["status"] == "PASS"

    sess_model = SessionManager("run_ms", {"id": "s_ms"}, log_root=tmp_path)
    sess_model._last_transition_expectations = ["Expected Output"]
    with (
        patch("eval_runner.llm_providers.LLMProviderFactory.create", return_value=MagicMock()),
        patch("eval_runner.metrics.MetricRegistry.get", return_value=AsyncMock(return_value=1.0)),
    ):
        res_ms = await sess_model._evaluate_consensus(
            {"consensus": {"judge_panel": [{"name": "j_model_only", "model": "gemini-flash"}]}},
            [],
        )
        assert res_ms["evaluated"] is True
