"""
tests/unit/handlers/test_evaluation_cli_handlers.py
Unit and behavioral contract tests for CLI evaluation, replay, gate, record,
playground, and certify handlers in eval_runner/handlers/evaluation.py.
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.handlers import evaluation
from eval_runner.run_lifecycle import RunSuspendedForApproval


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


@pytest.mark.asyncio
async def test_replay_requires_provider_owned_events():
    """Replay has no path-jail branch because it does not resolve paths."""
    provider = MagicMock()
    provider.get_events.return_value = []
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=provider):
        assert await evaluation.handle_replay(MagicMock(run_id="out_of_bounds_run")) == 1


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
        "eval_runner.runtime_services.resolve_run_store",
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
    # Missing run_id
    assert await evaluation.handle_gate(MagicMock(run_id=None)) == 1

    mock_store = MagicMock()
    mock_store.get_manifest.return_value = {"metadata": {"git_hash": "commit_123"}}

    with (
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_store),
        patch(
            "eval_runner.verifier.TraceVerifier.verify_run",
            return_value={"is_valid": True, "verification_status": "VERIFIED"},
        ),
    ):
        assert await evaluation.handle_gate(MagicMock(run_id="run_gate", hash=None)) == 0
        assert await evaluation.handle_gate(MagicMock(run_id="run_gate", hash="commit_123")) == 0
        assert await evaluation.handle_gate(MagicMock(run_id="run_gate", hash="wrong_hash")) == 1


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
        patch("eval_runner.services.certification.execute_industrial_certification") as mock_cert,
    ):
        mock_cert.return_value = {
            "status": "certified",
            "run_id": "run_cert",
            "manifest": {
                "trace_hash": "sha3_256:12345",
                "manifest_path": "/path/run_manifest.json",
                "certified_at": "2026-08-31T00:00:00",
            },
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


@pytest.mark.asyncio
async def test_handler_replay_uses_provider_events_only():
    provider = MagicMock()
    provider.get_events.return_value = [{"event": "run_start", "run_id": "provider-run"}]
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=provider):
        assert await evaluation.handle_replay(MagicMock(run_id="provider-run")) == 0
    provider.get_events.assert_called_once_with("provider-run", offset=0, limit=10_000_000)


def test_load_plugins_from_args_exception():
    """Plugin load error."""
    args = MagicMock(plugin=["nonexistent_plugin_xyz"])
    with patch("eval_runner.plugins.manager.load", side_effect=RuntimeError("Plugin load error")):
        evaluation.load_plugins_from_args(args)


@pytest.mark.asyncio
async def test_handler_evaluate_branches(tmp_path):
    """Dataset loading exception and empty scenarios."""
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps({"id": "s1", "title": "Scen 1", "turns": []}))

    # 1. Dataset loading exception
    args_bad_load = MagicMock(
        path=str(scenario_path),
        format="json",
        protocol="http",
        agent="http://localhost:8000",
        run_log_dir=str(tmp_path),
        per_run_logs=True,
        master_log=True,
        seed=123,
    )
    with patch("eval_runner.loader.load_dataset", side_effect=RuntimeError("Corrupt dataset")):
        assert await evaluation.handle_evaluate(args_bad_load) == 1

    # 2. Empty scenarios
    with patch("eval_runner.loader.load_dataset", return_value=[]):
        assert await evaluation.handle_evaluate(args_bad_load) == 1

    # 3. TypeError on vars(args)
    class TypeErrArgs:
        def __init__(self):
            self.path = str(scenario_path)
            self.format = "json"
            self.attempts = "invalid_int"
            self.protocol = "local"
            self.agent = "http://localhost:8000"
            self.agent_name = "test"
            self.agent_cmd = "python test.py"
            self.seed = "seed_str"

    obj = TypeErrArgs()
    with (
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "s1", "title": "Scen 1"}]),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock),
        patch("builtins.vars", side_effect=TypeError("vars() error")),
    ):
        assert await evaluation.handle_evaluate(obj) == 0


@pytest.mark.asyncio
async def test_handler_run_branches(tmp_path):
    """Evaluation exception in handle_run."""
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps({"id": "s1", "title": "Scen 1", "turns": []}))

    # 1. Evaluation exception in handle_run
    args_err = MagicMock(
        scenario=str(scenario_path),
        attempts=1,
        protocol="socket",
        agent="s",
        agent_socket="127.0.0.1:9000",
    )
    with (
        patch("eval_runner.loader.load_scenario", return_value={"id": "s1", "title": "Scen 1"}),
        patch(
            "eval_runner.engine.run_evaluation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Run eval crash"),
        ),
    ):
        assert await evaluation.handle_run(args_err) == 1

    # 2. TypeError on vars(args) in handle_run
    class TypeErrRunArgs:
        def __init__(self):
            self.scenario = str(scenario_path)
            self.attempts = "invalid_int"
            self.protocol = "http"
            self.agent = "http://localhost:8000"

    with (
        patch("eval_runner.loader.load_scenario", return_value={"id": "s1", "title": "Scen 1"}),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock),
        patch("builtins.vars", side_effect=TypeError("vars() error")),
    ):
        assert await evaluation.handle_run(TypeErrRunArgs()) == 0


@pytest.mark.asyncio
async def test_handler_replay_all_events(tmp_path):
    """Replay exception and missing trace."""
    # 1. No run_id
    assert await evaluation.handle_replay(MagicMock(run_id=None)) == 1

    # 2. Missing trace / no events
    mock_empty_store = MagicMock()
    mock_empty_store.get_events.return_value = []
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_empty_store):
        assert await evaluation.handle_replay(MagicMock(run_id="nonexistent-run")) == 1

    # 3. Successful event replay printing all event types
    events = [
        {"event": "run_start", "run_id": "r1", "scenario": "scen_1"},
        {"event": "prompt", "role": "user", "content": "Hello!"},
        {"event": "agent_response", "content": "Hi there!"},
        {"event": "custom_audit_marker", "content": "Ignored in standard replay"},
        {"event": "run_end", "status": "COMPLETED"},
    ]
    mock_store = MagicMock()
    mock_store.get_events.return_value = events
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_store):
        assert await evaluation.handle_replay(MagicMock(run_id="r1")) == 0

    # Unsafe replay path
    with patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=False):
        assert await evaluation.handle_replay(MagicMock(run_id="r1")) == 1

    # Exception during event retrieval
    mock_err_store = MagicMock()
    mock_err_store.get_events.side_effect = RuntimeError("Store retrieval error")
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_err_store):
        assert await evaluation.handle_replay(MagicMock(run_id="r1")) == 1


@pytest.mark.asyncio
async def test_handler_verify_branches(tmp_path):
    run_id = "run-verify-branches"
    args = MagicMock(run_id=run_id, verify_ledger=False)
    mock_store = MagicMock()
    mock_store.get_run.return_value = {"run_id": run_id}
    mock_store.get_trace_bytes.return_value = b'{"event":"run_start"}\n'

    # Missing run id
    assert await evaluation.handle_verify(MagicMock(run_id="")) == 1

    # Unsafe path rejection
    with patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=False):
        assert await evaluation.handle_verify(args) == 1

    # Run and trace missing from storage provider
    mock_missing_store = MagicMock()
    mock_missing_store.get_run.return_value = None
    mock_missing_store.get_trace_bytes.return_value = None
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_missing_store):
        assert await evaluation.handle_verify(args) == 1

    # Verification failed
    with (
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_store),
        patch(
            "eval_runner.verifier.TraceVerifier.verify_run",
            return_value={"is_valid": False, "verification_status": "FAILED_VERIFICATION"},
        ),
    ):
        assert await evaluation.handle_verify(args) == 1

    # TraceVerifier returns True (verified)
    with (
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_store),
        patch(
            "eval_runner.verifier.TraceVerifier.verify_run",
            return_value={"is_valid": True, "verification_status": "VERIFIED"},
        ),
    ):
        assert await evaluation.handle_verify(args) == 0

    # TraceVerifier exception
    with (
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_store),
        patch(
            "eval_runner.verifier.TraceVerifier.verify_run",
            side_effect=RuntimeError("Verification error"),
        ),
    ):
        assert await evaluation.handle_verify(args) == 1


@pytest.mark.asyncio
async def test_handler_verify_package_all_branches(tmp_path):
    pkg_file = tmp_path / "valid.agentv-package.json"
    pkg_file.write_text(json.dumps({"package_id": "p1"}), encoding="utf-8")

    pub_pem_file = tmp_path / "pub.pem"
    pub_pem_file.write_text(
        "-----BEGIN PUBLIC KEY-----\n"
        "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE\n"
        "-----END PUBLIC KEY-----",
        encoding="utf-8",
    )

    # 1. raw_trace_path does not exist
    args_bad_trace = MagicMock(
        package_path=str(pkg_file),
        raw_trace_path=str(tmp_path / "nonexistent_trace.jsonl"),
        public_key_pem=None,
        require_signature=False,
    )
    assert await evaluation.handle_verify_package(args_bad_trace) == 1

    # 2. raw_trace_path unsafe jail escape
    with patch("eval_runner.handlers.evaluation._ensure_path_safe", side_effect=[True, False]):
        args_unsafe_trace = MagicMock(
            package_path=str(pkg_file),
            raw_trace_path=str(tmp_path / "trace.jsonl"),
            public_key_pem=None,
            require_signature=False,
        )
        assert await evaluation.handle_verify_package(args_unsafe_trace) == 1

    # 3. public_key_pem file exists + successful verification
    trace_file = tmp_path / "trace.jsonl"
    trace_file.write_bytes(b'{"event": "start"}\n')
    args_good = MagicMock(
        package_path=str(pkg_file),
        raw_trace_path=str(trace_file),
        public_key_pem=str(pub_pem_file),
        require_signature=False,
    )
    with patch(
        "eval_runner.verifier.VerificationAuthority.verify_package",
        return_value={"verified": True, "package_id": "p1"},
    ):
        assert await evaluation.handle_verify_package(args_good) == 0

    # 4. Exception in verify_package
    with patch(
        "eval_runner.verifier.VerificationAuthority.verify_package",
        side_effect=RuntimeError("Fatal verifier crash"),
    ):
        assert await evaluation.handle_verify_package(args_good) == 1

    # 5. public_key_pem as non-file string, scenario path resolution, and failure list reporting
    scen_file = tmp_path / "scenario.json"
    scen_file.write_text(json.dumps({"id": "scen-bound"}), encoding="utf-8")
    args_custom = MagicMock(
        package_path=str(pkg_file),
        raw_trace_path=str(trace_file),
        public_key_pem="raw-inline-pem-key-not-on-disk",
        scenario_path=str(scen_file),
        require_signature=False,
    )
    with patch(
        "eval_runner.verifier.VerificationAuthority.verify_package",
        return_value={
            "verified": False,
            "status": "ATTESTED_FAIL",
            "failures": ["Mismatched signature"],
        },
    ):
        assert await evaluation.handle_verify_package(args_custom) == 1

    # 6. public_key_pem non-string / integer fallback and non-existent scenario path
    args_non_str_key = MagicMock(
        package_path=str(pkg_file),
        raw_trace_path=str(trace_file),
        public_key_pem=12345,
        scenario_path=str(tmp_path / "nonexistent_scenario.json"),
        require_signature=False,
    )
    with patch(
        "eval_runner.verifier.VerificationAuthority.verify_package",
        return_value={"verified": True, "package_id": "p1"},
    ):
        assert await evaluation.handle_verify_package(args_non_str_key) == 0


@pytest.mark.asyncio
async def test_handler_gate_branches(tmp_path):
    run_id = "run-gate-test"
    args = MagicMock(run_id=run_id, hash="commit_123", verify_ledger=False)

    # 1. Missing manifest
    mock_empty_store = MagicMock()
    mock_empty_store.get_manifest.return_value = None
    with (
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_empty_store),
        patch(
            "eval_runner.verifier.TraceVerifier.verify_run",
            return_value={"is_valid": False, "verification_status": "NOT_FOUND"},
        ),
    ):
        assert await evaluation.handle_gate(args) == 1

    # 2. Verification failure (manifest found but invalid)
    mock_store = MagicMock()
    mock_store.get_manifest.return_value = {"metadata": {"git_hash": "commit_123"}}
    with (
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_store),
        patch(
            "eval_runner.verifier.TraceVerifier.verify_run",
            return_value={"is_valid": False, "verification_status": "FAILED_VERIFICATION"},
        ),
    ):
        assert await evaluation.handle_gate(args) == 1

    # 3. Verification exception
    with (
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_store),
        patch(
            "eval_runner.verifier.TraceVerifier.verify_run",
            side_effect=RuntimeError("Gating crash"),
        ),
    ):
        assert await evaluation.handle_gate(args) == 1

    # 4. Successful gate verification
    with (
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_store),
        patch(
            "eval_runner.verifier.TraceVerifier.verify_run",
            return_value={"is_valid": True, "verification_status": "VERIFIED"},
        ),
    ):
        assert await evaluation.handle_gate(args) == 0


@pytest.mark.asyncio
async def test_handler_certify_unsafe_and_exception(tmp_path):
    run_id = "run-cert-test"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text("{}", encoding="utf-8")

    args = MagicMock(
        run_id=run_id,
        identity="sys",
        status="PASS",
        score=1.0,
        policy_ref=None,
        ttl=30,
        fingerprint=None,
    )

    # Unsafe path check
    with patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=False):
        res = await evaluation.handle_certify(args)
        assert res == 1

    # Certification exception
    with (
        patch("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs"),
        patch(
            "eval_runner.services.certification.execute_industrial_certification",
            side_effect=RuntimeError("Cert failure"),
        ),
    ):
        res_exc = await evaluation.handle_certify(args)
        assert res_exc == 1

    # Certification outcome with empty manifest
    with (
        patch("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs"),
        patch(
            "eval_runner.services.certification.execute_industrial_certification",
            return_value={"status": "certified", "manifest": {}},
        ),
    ):
        res_no_man = await evaluation.handle_certify(args)
        assert res_no_man == 0

    # Certification outcome with manifest export failure
    with (
        patch("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs"),
        patch(
            "eval_runner.services.certification.execute_industrial_certification",
            return_value={"status": "certified", "manifest": {"trace_hash": "sha3_256:abc"}},
        ),
        patch("pathlib.Path.write_text", side_effect=OSError("Disk full")),
    ):
        res_exp_err = await evaluation.handle_certify(args)
        assert res_exp_err == 0


@pytest.mark.asyncio
async def test_handle_evaluate_filters_callable_args():
    """Verify that handle_evaluate removes dispatch functions and other callables from args."""

    def dummy_dispatch(a):
        return a

    args = MagicMock()
    args.path = "scenarios/test"
    args.format = "json"
    args.attempts = 1
    args.func = dummy_dispatch
    args.other_callback = lambda x: x
    args.clean_value = "hello"

    with (
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "scen_1"}]),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_run,
    ):
        mock_run.return_value = {"status": "completed"}
        res = await evaluation.handle_evaluate(args)
        assert res == 0
        mock_run.assert_called_once()
        passed_metadata = mock_run.call_args[1]["metadata"]
        passed_args = passed_metadata["args"]
        assert "func" not in passed_args
        assert "other_callback" not in passed_args
        assert passed_args.get("clean_value") == "hello"


@pytest.mark.asyncio
async def test_replay_does_not_use_a_vault_path(tmp_path):
    run_id = "run-vault-present"
    vault_dir = tmp_path / "runs" / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    vault_file = vault_dir / "run.jsonl"
    vault_file.write_text("{}", encoding="utf-8")

    provider = MagicMock()
    provider.get_events.return_value = []
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=provider):
        assert await evaluation.handle_replay(MagicMock(run_id=run_id)) == 1


def test_prepare_agent_env_empty_cmd_and_socket():
    args_local_empty = MagicMock(protocol="local", agent_cmd=None)
    env_local = evaluation.prepare_agent_env(args_local_empty)
    assert env_local["protocol"] == "local"

    args_socket_empty = MagicMock(protocol="socket", agent_socket=None)
    env_socket = evaluation.prepare_agent_env(args_socket_empty)
    assert env_socket["protocol"] == "socket"


def test_load_plugins_from_args_whitespace_entries():
    args = MagicMock(plugin=["", "   ", "plugin_valid"])
    mock_reg = MagicMock()
    with patch("eval_runner.runtime_services.resolve_plugin_registry", return_value=mock_reg):
        evaluation.load_plugins_from_args(args)
        mock_reg.load.assert_called_once_with("plugin_valid")


@pytest.mark.asyncio
async def test_handle_evaluate_adapter_close_exception():
    args = MagicMock(path="scenarios/test", format="json", attempts=1)
    with (
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "s1"}]),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_run,
        patch(
            "eval_runner.adapters.common.SessionManager.close_all",
            side_effect=RuntimeError("Session close fail"),
        ),
    ):
        mock_run.return_value = {"status": "completed"}
        res = await evaluation.handle_evaluate(args)
        assert res == 0


@pytest.mark.asyncio
async def test_handle_run_suspended_for_approval_and_adapter_close_exception():
    args = MagicMock(
        scenario="scen_hitl",
        run_log_dir=None,
        per_run_logs=None,
        master_log=None,
        runs=1,
    )
    susp_exc = RunSuspendedForApproval("run-susp-1", "task-1", "tok-abc")

    # Interrupted by approval suspension
    with (
        patch("eval_runner.loader.load_scenario", return_value={"id": "scen_hitl"}),
        patch("eval_runner.handlers.evaluation.prepare_agent_env"),
        patch("eval_runner.handlers.evaluation.load_plugins_from_args"),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock, side_effect=susp_exc),
    ):
        res_susp = await evaluation.handle_run(args)
        assert res_susp == 0

    # Finally block with close_all exception
    with (
        patch("eval_runner.loader.load_scenario", return_value={"id": "scen_hitl"}),
        patch("eval_runner.handlers.evaluation.prepare_agent_env"),
        patch("eval_runner.handlers.evaluation.load_plugins_from_args"),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock, return_value={}),
        patch(
            "eval_runner.adapters.common.SessionManager.close_all",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Adapter cleanup failure"),
        ),
    ):
        res_cleanup = await evaluation.handle_run(args)
        assert res_cleanup == 0


@pytest.mark.asyncio
async def test_handle_hitl_resume_all_branches():
    # 1. Missing run_id
    assert await evaluation.handle_hitl_resume(MagicMock(run_id=None)) == 1

    # 2. Missing approval_token
    assert await evaluation.handle_hitl_resume(MagicMock(run_id="r1", approval_token=None)) == 1

    # 3. Invalid decision
    assert (
        await evaluation.handle_hitl_resume(
            MagicMock(run_id="r1", approval_token="tok1", decision="MAYBE")
        )
        == 1
    )

    # 4. Request not found in store
    mock_store = MagicMock()
    mock_store.get_request.return_value = None
    with patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_store):
        assert (
            await evaluation.handle_hitl_resume(
                MagicMock(run_id="r1", approval_token="tok1", decision="APPROVED")
            )
            == 1
        )

    # 5. Request run_id mismatch
    mismatched_req = MagicMock(run_id="different_run")
    mock_store.get_request.return_value = mismatched_req
    with patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_store):
        assert (
            await evaluation.handle_hitl_resume(
                MagicMock(run_id="r1", approval_token="tok1", decision="APPROVED")
            )
            == 1
        )

    # 6. Provider scope mismatch
    scoped_req = MagicMock(run_id="r1", scope={"tenant": "t1"}, status="PENDING")
    mock_store.get_request.return_value = scoped_req
    mock_run_store = MagicMock()
    mock_run_store.get_run.side_effect = lambda run_id, context=None: (
        {"run_id": run_id} if context is None else None
    )
    with (
        patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_store),
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_run_store),
    ):
        assert (
            await evaluation.handle_hitl_resume(
                MagicMock(run_id="r1", approval_token="tok1", decision="APPROVED")
            )
            == 1
        )

    # 7. Already resolved as REJECTED
    rejected_req = MagicMock(run_id="r1", scope={}, status="REJECTED", decided_by="auditor")
    mock_store.get_request.return_value = rejected_req
    mock_run_store_ok = MagicMock()
    mock_run_store_ok.get_run.return_value = {"run_id": "r1"}
    with (
        patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_store),
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_run_store_ok),
    ):
        assert (
            await evaluation.handle_hitl_resume(
                MagicMock(run_id="r1", approval_token="tok1", decision="APPROVED")
            )
            == 0
        )

    # 8. Pending request resolved as REJECTED with reason
    pending_req = MagicMock(run_id="r1", scope={}, status="PENDING")
    mock_store.get_request.return_value = pending_req
    mock_mgr = MagicMock()
    with (
        patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_store),
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_run_store_ok),
        patch(
            "eval_runner.session_components.approval_manager.SessionApprovalManager",
            return_value=mock_mgr,
        ),
    ):
        args_reject = MagicMock(
            run_id="r1",
            approval_token="tok1",
            decision="REJECTED",
            reviewer="auditor",
            reason="Security denial",
        )
        assert await evaluation.handle_hitl_resume(args_reject) == 0
        mock_mgr.resolve_durable_request.assert_called_once()

    # Pending request resolved as REJECTED without reason
    with (
        patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_store),
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_run_store_ok),
        patch(
            "eval_runner.session_components.approval_manager.SessionApprovalManager",
            return_value=mock_mgr,
        ),
    ):
        args_reject_no_reason = MagicMock(
            run_id="r1",
            approval_token="tok1",
            decision="REJECTED",
            reviewer="auditor",
            reason=None,
        )
        assert await evaluation.handle_hitl_resume(args_reject_no_reason) == 0

    # Already resolved as APPROVED
    approved_req = MagicMock(run_id="r1", scope={}, status="APPROVED", decided_by="auditor")
    mock_store.get_request.return_value = approved_req
    mock_backend_res = MagicMock()
    with (
        patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_store),
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_run_store_ok),
        patch(
            "eval_runner.runtime_services.resolve_execution_backend", return_value=mock_backend_res
        ),
    ):
        assert (
            await evaluation.handle_hitl_resume(
                MagicMock(run_id="r1", approval_token="tok1", decision="APPROVED")
            )
            == 0
        )
        mock_backend_res.resume.assert_called_once()

    # 9. Pending request resolved as APPROVED with context and backend resume
    pending_scoped_req = MagicMock(run_id="r1", scope={"tenant": "t1"}, status="PENDING")
    mock_store.get_request.return_value = pending_scoped_req
    mock_backend = MagicMock()
    with (
        patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_store),
        patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_run_store_ok),
        patch(
            "eval_runner.session_components.approval_manager.SessionApprovalManager",
            return_value=mock_mgr,
        ),
        patch("eval_runner.runtime_services.resolve_execution_backend", return_value=mock_backend),
    ):
        args_approve = MagicMock(
            run_id="r1", approval_token="tok1", decision="APPROVED", reviewer="auditor", reason=None
        )
        assert await evaluation.handle_hitl_resume(args_approve) == 0
        mock_backend.resume.assert_called_once()

    # 10. General exception handling
    mock_err_store = MagicMock()
    mock_err_store.get_request.side_effect = RuntimeError("Fatal store error")
    with patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_err_store):
        assert (
            await evaluation.handle_hitl_resume(
                MagicMock(run_id="r1", approval_token="tok1", decision="APPROVED")
            )
            == 1
        )
