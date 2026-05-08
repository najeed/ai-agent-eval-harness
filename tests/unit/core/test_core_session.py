from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.session import SessionManager


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

    mock_agent_response = {"action": "completed", "tool_name": None}

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
        {"from": "node_2", "to": "node_1"},  # cycle
    ]

    session = SessionManager("test_run_456", base_scenario, log_root=tmp_path)

    results = await session.execute_tasks(1)
    assert len(results) > 0
    assert results[-1]["status"] == "failure"
    assert "Cyclic dependencies detected" in results[-1]["message"]


@pytest.mark.asyncio
async def test_session_execute_tasks_empty_topology(base_scenario, tmp_path):
    base_scenario["workflow"]["nodes"] = []
    session = SessionManager("test_run_456", base_scenario, log_root=tmp_path)

    results = await session.execute_tasks(1)
    assert len(results) > 0
    assert results[-1]["status"] == "failure"
    assert "Empty Topology" in results[-1]["message"]


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

    result = await session._verify_state_parity(node, mock_sandbox, history)
    assert result is True


@pytest.mark.asyncio
async def test_verify_state_parity_timeout(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {"expected_outcome": [{"target": "message", "expected": "ok"}], "timeout": 0.1}
    mock_sandbox = AsyncMock()
    mock_sandbox.get_active_simulators = MagicMock(return_value={})
    history = [{"role": "agent", "content": "wrong"}]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await session._verify_state_parity(node, mock_sandbox, history)

    assert result is False


@pytest.mark.asyncio
async def test_verify_state_parity_unsupported_target(base_scenario, tmp_path):
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)
    node = {"expected_outcome": [{"target": "weird", "expected": "ok"}], "timeout": 0.1}
    mock_sandbox = AsyncMock()
    mock_sandbox.get_active_simulators = MagicMock(return_value={})

    result = await session._verify_state_parity(node, mock_sandbox, [])
    assert result is False


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

    result = await session._verify_state_parity(node, mock_sandbox, history)
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
    session = SessionManager("test_run", base_scenario, log_root=tmp_path)

    agent_resp = {"prompt": "Confirm action"}
    history = []
    actions = {}
    turn_ctx = MagicMock()

    monkeypatch.setenv("CI", "true")
    res = await session._handle_hitl(1, agent_resp, history, actions, turn_ctx)
    assert "Auto-approved" in res


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
        assert len(res["metrics"]) == 0


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
