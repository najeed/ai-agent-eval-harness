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


@pytest.mark.asyncio
async def test_prepare_agent_env_endpoint_and_model():
    """Verify prepare_agent_env populates environment for local and socket protocols."""
    args_local = MagicMock(
        protocol="local", agent_cmd="python my_agent.py", agent_name="local_agent", agent="local"
    )
    meta_local = evaluation.prepare_agent_env(args_local)
    assert meta_local["protocol"] == "local"
    assert os.environ.get("AGENT_LOCAL_CMD") == "python my_agent.py"

    args_sock = MagicMock(
        protocol="socket", agent_socket="127.0.0.1:9999", agent_name="sock_agent", agent="sock"
    )
    meta_sock = evaluation.prepare_agent_env(args_sock)
    assert meta_sock["protocol"] == "socket"
    assert os.environ.get("AGENT_SOCKET_ADDR") == "127.0.0.1:9999"


@pytest.mark.asyncio
async def test_handle_run_and_batch_non_dict_vars_and_non_int_attempts():
    """Verify handle_run and handle_evaluate handle non-vars args and string attempts gracefully."""

    class NoVarsArgs:
        scenario = "test_scen"
        scenarios = ["test_scen"]
        path = "test_scen"
        pattern = "*.json"
        attempts = "invalid_non_int"
        seed = None
        run_log_dir = None
        per_run_logs = None
        master_log = None
        protocol = "http"
        agent = None
        agent_name = None
        plugins = None
        plugin = []
        format = "json"

    with (
        patch("eval_runner.loader.load_scenario", return_value={"id": "test_scen"}),
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "test_scen"}]),
        patch("eval_runner.engine.run_evaluation", return_value=None),
    ):
        assert await evaluation.handle_run(NoVarsArgs()) == 0
        assert await evaluation.handle_evaluate(NoVarsArgs()) == 0


@pytest.mark.asyncio
async def test_handle_gate_trace_missing_and_exception_handling():
    """
    Verify handle_gate handles missing trace file, vc_path not exists, and unexpected exceptions.
    """

    # 1. vc_path does not exist
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", return_value=False),
    ):
        assert await evaluation.handle_gate(MagicMock(run_id="run_missing_vc")) == 1

    # 2. trace file does not exist
    def exists_vc_only(self):
        p_str = str(self)
        if "_vc.json" in p_str or "run_manifest.json" in p_str:
            return True
        return False

    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", exists_vc_only),
        patch("builtins.open", MagicMock()),
        patch("json.load", return_value={"trace_file": "missing_run.jsonl"}),
    ):
        assert await evaluation.handle_gate(MagicMock(run_id="run_missing_trace")) == 1

    # 3. unexpected exception during gating
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", exists_vc_only),
        patch("builtins.open", side_effect=RuntimeError("unexpected read error")),
    ):
        assert await evaluation.handle_gate(MagicMock(run_id="run_err")) == 1


@pytest.mark.asyncio
async def test_handle_verify_package_branches(tmp_path):
    """Verify handle_verify_package CLI handler across success, failure, and security branches."""
    import json

    # 1. Unsafe path
    with patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=False):
        res = await evaluation.handle_verify_package(MagicMock(package_path="unsafe.json"))
        assert res == 1

    # 2. Missing file
    pkg_missing = tmp_path / "missing.json"
    res_missing = await evaluation.handle_verify_package(MagicMock(package_path=str(pkg_missing)))
    assert res_missing == 1

    # 3. Success verification
    pkg_file = tmp_path / "valid.agentv-package.json"
    pkg_data = {
        "scenario_id": "scen-01",
        "scenario_version": "1.0.0",
        "scenario_hash": "sha3_256:scen",
        "manifest_id": "man-01",
        "manifest_hash": "sha3_256:man",
        "execution_identity": {},
        "trace_hash": "sha3_256:112233",
        "trace_seal": {},
        "evidence_root_hash": "sha3_256:evroot",
        "required_oracle_ids": [],
        "executed_oracle_results": [],
        "decision": {"decision": "PASS"},
    }
    pkg_file.write_text(json.dumps(pkg_data), encoding="utf-8")

    args_valid = MagicMock(
        package_path=str(pkg_file),
        raw_trace_path=None,
        public_key_pem=None,
        require_signature=False,
    )
    assert await evaluation.handle_verify_package(args_valid) == 0

    # 4. Failed verification
    pkg_failed_data = dict(pkg_data, decision={"decision": "FAIL"})
    pkg_failed_file = tmp_path / "failed.agentv-package.json"
    pkg_failed_file.write_text(json.dumps(pkg_failed_data), encoding="utf-8")

    args_fail = MagicMock(
        package_path=str(pkg_failed_file),
        raw_trace_path=None,
        public_key_pem=None,
        require_signature=False,
    )
    assert await evaluation.handle_verify_package(args_fail) == 1
