from unittest.mock import MagicMock, patch

import pytest

from eval_runner.session import SessionManager


@pytest.fixture
def session():
    scenario = {
        "id": "test_session",
        "task_description": "Do something",
        "max_turns": 5,
        "workflow": {"nodes": [], "edges": []},
        "aes_version": 1.4,
    }
    return SessionManager("run_123", scenario)


@pytest.mark.asyncio
async def test_session_verify_state_parity_branches(session):
    """Verify all branches of the state parity verification logic."""
    node = {
        "expected_outcome": [
            {"target": "shim:db", "property": "$.status", "expected": "active"},
            {"target": "message", "expected": "regex:success"},  # Regex mode
            {
                "target": "shim:counter",
                "mode": "numerical_tolerance",
                "expected": 10.0,
            },  # Numerical
            {"target": "unsupported", "expected": "ignored"},  # Unsupported target
        ]
    }

    # Mock sandbox and extraction
    sandbox = MagicMock()
    # shim snapshots
    with patch.object(
        session,
        "_get_shim_snapshots",
        return_value={"db": {"status": "active"}, "counter": 10.00000000001},
    ):
        with patch.object(session, "_extract_agent_summary", return_value="The task was a success"):
            res = await session._verify_state_parity(node, sandbox, [])
            assert res is False  # Because of 'unsupported' target failing


@pytest.mark.asyncio
async def test_session_verify_state_parity_regex_and_numeric(session):
    """Deep dive into regex and numeric tolerance parity checks."""
    node = {
        "expected_outcome": [
            {"target": "message", "mode": "regex", "expected": "done|finished"},
            {"target": "shim:val", "mode": "numerical_tolerance", "expected": 5.0},
        ]
    }

    with patch.object(session, "_get_shim_snapshots", return_value={"val": 5.00000000001}):
        with patch.object(session, "_extract_agent_summary", return_value="I am done"):
            res = await session._verify_state_parity(node, MagicMock(), [])
            assert res is True


def test_get_last_env_message_list_handling(session):
    """Verify that _get_last_env_message handles list results correctly."""
    history = [{"role": "environment", "content": ["result_a", "result_b"]}]
    msg = session._get_last_env_message(history)
    assert "result_a" in msg
    assert "result_b" in msg


@pytest.mark.asyncio
async def test_session_calculate_metrics_hygiene(session):
    """Verify that _calculate_metrics processes state_hygiene rules."""
    node = {
        "id": "node_1",
        "state_hygiene": {
            "rules": [
                {"path": "user.authenticated", "expected": True, "op": "eq"},
                {"path": "db.connection", "op": "exists"},
                {"path": "logs", "expected": "ERROR", "op": "contains"},
                {"path": "not_here", "op": "not_exists"},
            ]
        },
    }

    sandbox = MagicMock()
    sandbox.state = {
        "user": {"authenticated": True},
        "db": {"connection": "active"},
        "logs": ["INFO", "ERROR", "DETAIL"],
        "not_here": None,
    }

    with patch.object(session, "_extract_tool_registry", return_value={}):
        res = await session._calculate_metrics(node, 1, 0, [], sandbox, {})

        hygiene = res["state_hygiene"]
        assert all(r["success"] for r in hygiene)


def test_session_fork_depth_limit(session, monkeypatch):
    """Verify fork bomb prevention."""
    with patch("eval_runner.session.MAX_FORK_DEPTH", 1):
        session.fork_depth = 1
        with pytest.raises(RuntimeError) as exc:
            session.fork([], {})
        assert "Fork Bomb Prevention" in str(exc.value)


@pytest.mark.asyncio
async def test_session_telemetry_failure(session):
    """Verify that telemetry capture is silent on failure."""
    with patch("psutil.Process") as mock_proc:
        mock_proc.side_effect = Exception("System Busy")
        # Should not raise
        session._capture_telemetry()
        assert len(session.resource_telemetry) == 0


@pytest.mark.asyncio
async def test_session_verify_state_parity_invalid_format(session):
    """Verify that invalid assertions format is handled gracefully."""
    node = {"expected_outcome": "not_a_list"}
    res = await session._verify_state_parity(node, MagicMock(), [])
    assert res is True  # Fallback to True for safety
