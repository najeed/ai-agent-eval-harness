"""
tests/unit/handlers/test_evaluation_cli_handlers.py
Unit and behavioral contract tests for CLI evaluation, replay, gate, record,
playground, and certify handlers in eval_runner/handlers/evaluation.py.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.handlers import evaluation


@pytest.fixture
def mock_args():
    args = MagicMock()
    args.agent = "http://localhost:8080"
    args.protocol = "http"
    args.path = "scenarios"
    args.attempts = 1
    args.format = "json"
    args.plugin = []
    args.agent_name = "test_agent"
    args.run_id = "test_run_1"
    return args


# ---------------------------------------------------------------------------
# 1. Environment and Protocol Setup
# ---------------------------------------------------------------------------


def test_prepare_agent_env_socket_protocol():
    """Verify socket protocol environment configuration and address assignment."""
    args = MagicMock(protocol="socket", agent_socket="127.0.0.1:9000")
    evaluation.prepare_agent_env(args)
    assert os.environ.get("AGENT_SOCKET_ADDR") == "127.0.0.1:9000"


def test_resolve_replay_trace_security_jail(tmp_path):
    """Verify security rejection when trace resolution breaches jail boundary."""
    with patch("eval_runner.utils.is_path_safe", side_effect=[True, False]):
        res = evaluation._resolve_replay_trace("out_of_bounds_run")
        assert res is None


# ---------------------------------------------------------------------------
# 2. handle_evaluate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_evaluate_execution_flow(mock_args):
    """Verify standard batch evaluation invocation and exit status."""
    with (
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "s1"}]),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_run,
    ):
        mock_run.return_value = {"status": "completed", "passed": 1, "failed": 0}
        res = await evaluation.handle_evaluate(mock_args)
        assert res == 0
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_handle_evaluate_non_int_attempts(mock_args):
    """Verify graceful fallback for non-integer attempt count arguments."""
    mock_args.attempts = "invalid_attempts"
    with (
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "s1"}]),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock),
    ):
        res = await evaluation.handle_evaluate(mock_args)
        assert res == 0


@pytest.mark.asyncio
async def test_handle_evaluate_loop_exception_returns_failure(mock_args):
    """Verify evaluation handler returns exit code 1 when engine raises unhandled error."""
    with (
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "s1"}]),
        patch("eval_runner.engine.run_evaluation", side_effect=RuntimeError("Engine failure")),
    ):
        res = await evaluation.handle_evaluate(mock_args)
        assert res == 1


# ---------------------------------------------------------------------------
# 3. handle_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_run_environment_and_log_configuration():
    """Verify handle_run sets environment variables and overrides appropriately."""
    args = MagicMock(
        scenario="demo_scen",
        run_log_dir="custom_log_dir",
        per_run_logs=True,
        master_log=True,
        seed=100,
        plugin=[],
        attempts=1,
        agent="http://localhost:5000",
        agent_name="agent_alpha",
        run_id="run_100",
        format="json",
    )

    with (
        patch("eval_runner.loader.load_scenario", return_value={"id": "demo_scen"}),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_run,
    ):
        mock_run.return_value = {"status": "completed"}
        res = await evaluation.handle_run(args)
        assert res == 0
        assert os.environ["RUN_LOG_DIR"] == "custom_log_dir"
        assert os.environ["RUN_LOG_PER_RUN"] == "true"
        assert os.environ["RUN_LOG_MASTER"] == "true"


# ---------------------------------------------------------------------------
# 4. handle_record and handle_playground
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_record_and_playground_success(mock_args):
    """Verify successful execution flow for interaction recording and playground REPL."""
    with patch(
        "eval_runner.handlers.evaluation.trace_recorder.record_interaction",
        return_value=None,
    ):
        assert await evaluation.handle_record(mock_args) == 0

    with patch("eval_runner.handlers.evaluation.playground.run_playground", return_value=None):
        assert await evaluation.handle_playground(mock_args) == 0


@pytest.mark.asyncio
async def test_handle_record_and_playground_failure(mock_args):
    """Verify error propagation when recording or playground components fail."""
    with patch(
        "eval_runner.handlers.evaluation.trace_recorder.record_interaction",
        side_effect=RuntimeError("Recorder error"),
    ):
        assert await evaluation.handle_record(mock_args) == 1

    with patch(
        "eval_runner.handlers.evaluation.playground.run_playground",
        side_effect=RuntimeError("Playground error"),
    ):
        assert await evaluation.handle_playground(mock_args) == 1


# ---------------------------------------------------------------------------
# 5. handle_replay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_replay_missing_run_id_and_resolution_error():
    """Verify replay handler enforces run_id presence and handles trace resolution failures."""
    # Missing run_id
    assert await evaluation.handle_replay(MagicMock(run_id=None)) == 1

    # Exception during trace resolution
    with patch(
        "eval_runner.handlers.evaluation._resolve_replay_trace",
        side_effect=RuntimeError("Trace not found"),
    ):
        assert await evaluation.handle_replay(MagicMock(run_id="run_missing")) == 1


# ---------------------------------------------------------------------------
# 6. handle_verify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_verify_security_and_failure_cases():
    """Verify cryptographic trace verification handler failure branches."""
    # Missing run_id
    assert await evaluation.handle_verify(MagicMock(run_id=None)) == 1

    # Path safety rejection
    with patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=False):
        assert await evaluation.handle_verify(MagicMock(run_id="run_unsafe")) == 1

    # Missing manifest
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", side_effect=[True, False]),
    ):
        assert await evaluation.handle_verify(MagicMock(run_id="run_no_manifest")) == 1

    # Verification failure
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", return_value=True),
        patch("eval_runner.verifier.TraceVerifier.verify_trace_async", return_value=False),
    ):
        assert await evaluation.handle_verify(MagicMock(run_id="run_tampered")) == 1


# ---------------------------------------------------------------------------
# 7. handle_gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_gate_security_and_mismatch_branches():
    """Verify CI/CD gate handler validation and verification checks."""
    import pathlib

    orig_exists = pathlib.Path.exists

    def make_exists_mock(sequence):
        seq = list(sequence)

        def _mock(self):
            p_str = str(self)
            if any(k in p_str for k in ("_vc.json", "run_manifest.json", "t.json", "run.jsonl")):
                if seq:
                    return seq.pop(0)
            return orig_exists(self)

        return _mock

    # Missing run_id
    assert await evaluation.handle_gate(MagicMock(run_id=None)) == 1

    # Security fail
    with patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=False):
        assert await evaluation.handle_gate(MagicMock(run_id="run_gate")) == 1

    # Sidecar exists and verified successfully
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", make_exists_mock([False, True, True, True])),
        patch("builtins.open", MagicMock()),
        patch("json.load", return_value={"trace_file": "t.json"}),
        patch("eval_runner.verifier.TraceVerifier.verify_trace_async", return_value=True),
    ):
        assert await evaluation.handle_gate(MagicMock(run_id="run_gate", hash=None)) == 0


# ---------------------------------------------------------------------------
# 8. handle_quickstart and handle_certify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_quickstart_invocation():
    """Verify quickstart command delegates to run_quickstart."""
    with patch("eval_runner.quickstart.run_quickstart") as mock_q:
        await evaluation.handle_quickstart(None)
        mock_q.assert_called_once()


@pytest.mark.asyncio
async def test_handle_certify_provenance_and_error_handling():
    """Verify certify handler provenance chain generation and error handling."""
    # Missing run_id
    assert await evaluation.handle_certify(MagicMock(run_id=None)) == 1

    args = MagicMock(
        run_id="run_cert",
        identity="auditor-key",
        status="pass",
        score=1.0,
        ttl=30,
        fingerprint=None,
        policy_ref=None,
    )
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", return_value=True),
        patch("eval_runner.verifier.TraceVerifier.sign_trace") as mock_sign,
    ):
        mock_sign.return_value = {
            "provenance_chain": [{"identity": "auditor-key"}],
            "run_id": "run_cert",
        }
        assert await evaluation.handle_certify(args) == 0
