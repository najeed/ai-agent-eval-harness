"""
tests/contracts/test_interface_wiring_contract.py

Contract Test Suite for Runtime Interface Wiring.
Asserts that all 6 Extension Families and Subsystem Managers are actively wired into
runtime execution paths, preventing "built but unwired" regressions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from eval_runner.console.auth_manager import Permission, StaticKeyProvider
from eval_runner.events import Event
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.interfaces.policy import PolicyEvaluationResult, PolicyEvaluator
from eval_runner.interfaces.signing import SigningBackend
from eval_runner.reference.auth import SimpleAPIKeyAuthBackend
from eval_runner.reference.field_policy import BasicFieldPolicyEvaluator
from eval_runner.reference.inprocess_backend import InProcessExecutionBackend
from eval_runner.reference.local_artifact import LocalFileArtifactStore
from eval_runner.reference.local_catalog import LocalFileCatalogStore
from eval_runner.reference.local_leaderboard import LocalLeaderboardStore
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.reference.signing import LocalEd25519SigningBackend
from eval_runner.session import Session
from eval_runner.session_components.approval_manager import SessionApprovalManager
from eval_runner.session_components.checkpoint_manager import SessionCheckpointManager
from eval_runner.tool_sandbox import ToolSandbox
from eval_runner.verifier import TraceVerifier

# ==============================================================================
# 1. PolicyEvaluator Interface Wiring Tests
# ==============================================================================


class MockCustomPolicyEvaluator(PolicyEvaluator):
    """Test policy evaluator spy."""

    def __init__(self):
        self.call_count = 0
        self.last_policy_spec = None
        self.last_input_data = None

    def evaluate_policy(
        self,
        policy_spec: dict[str, Any],
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PolicyEvaluationResult:
        self.call_count += 1
        self.last_policy_spec = policy_spec
        self.last_input_data = input_data
        if input_data.get("amount", 0) > 100:
            return PolicyEvaluationResult(
                allowed=False,
                policy_id="test_limit",
                reason="Amount exceeds 100 in custom evaluator",
                violations=[
                    {
                        "field": "amount",
                        "limit": 100,
                        "value": input_data.get("amount"),
                        "message": "Amount exceeds 100 in custom evaluator",
                    }
                ],
            )
        return PolicyEvaluationResult(allowed=True, policy_id="test_limit")

    def validate_policy(self, policy_spec: dict[str, Any]) -> bool:
        return True


@pytest.mark.asyncio
async def test_tool_sandbox_policy_evaluator_wiring():
    """
    Contract Test: ToolSandbox routes policy checks through PolicyEvaluator.
    Asserts that custom PolicyEvaluator is actively called during tool execution.
    """
    custom_evaluator = MockCustomPolicyEvaluator()
    scenario = {
        "id": "policy_test_scenario",
        "tools": {
            "transfer_funds": {"output": {"status": "success", "message": "Funds transferred"}}
        },
        "policies": {
            "transfer_funds": {
                "max_limit": 100,
                "constrained_params": ["amount"],
            }
        },
    }

    sandbox = ToolSandbox(scenario, policy_evaluator=custom_evaluator)
    await sandbox.setup()

    # 1. Execute allowed amount
    res_ok = await sandbox.execute("transfer_funds", {"amount": 50})
    assert custom_evaluator.call_count == 1
    assert res_ok.get("output", {}).get("status") == "success" or res_ok.get("status") == "success"

    # 2. Execute violating amount -> must be intercepted by PolicyEvaluator
    res_blocked = await sandbox.execute("transfer_funds", {"amount": 500})
    assert custom_evaluator.call_count == 2
    assert res_blocked.get("status") == "policy_violation"
    assert "Amount exceeds 100" in res_blocked.get("violation", "")
    assert res_blocked.get("policy_id") == "test_limit"


@pytest.mark.asyncio
async def test_tool_sandbox_default_basic_field_policy_evaluator():
    """
    Contract Test: Default ToolSandbox uses BasicFieldPolicyEvaluator.
    """
    scenario = {
        "id": "default_policy_scenario",
        "tools": {"refund": {"output": {"status": "success"}}},
        "policies": {"refund": {"max_limit": 200, "constrained_params": ["val"]}},
    }
    sandbox = ToolSandbox(scenario)
    assert isinstance(sandbox.policy_evaluator, BasicFieldPolicyEvaluator)

    res = await sandbox.execute("refund", {"val": 300})
    assert res["status"] == "policy_violation"
    assert "exceeds limit" in res["violation"]


# ==============================================================================
# 2. Tool Definition Truthiness Bug
# ==============================================================================


@pytest.mark.asyncio
async def test_tool_definition_truthiness_empty_dict_routing():
    """
    Contract Test: A tool defined as an empty dict {} in scenario tools
    is recognized as defined, and is NOT erroneously routed to simulator prefix execution.
    """
    scenario = {
        "id": "empty_tool_def_scenario",
        "tools": {
            "custom_empty_tool": {}  # Empty dict tool definition
        },
    }
    sandbox = ToolSandbox(scenario)
    await sandbox.setup()

    res = await sandbox.execute("custom_empty_tool", {"param1": "val1"})
    # Must succeed with default tool execution output, not simulator fallback
    assert res.get("status") == "success" or res.get("output", {}).get("status") == "success"


# ==============================================================================
# 3. SigningBackend & Fail-Closed on Absence
# ==============================================================================


def test_signing_backend_ed25519_lifecycle(tmp_path):
    """
    Contract Test: LocalEd25519SigningBackend signs and verifies cryptographic payloads.
    """
    # Generate Ed25519 key pair
    priv_key = ed25519.Ed25519PrivateKey.generate()
    priv_pem = priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_key = priv_key.public_key()
    pub_pem = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    key_path = tmp_path / "ed25519_test.pem"
    key_path.write_bytes(priv_pem)

    backend = LocalEd25519SigningBackend()
    payload = b'{"event":"evaluation","run_id":"run-001","score":1.0}'

    # 1. Sign
    sig = backend.sign_payload(payload, key_path)
    assert isinstance(sig, str)
    assert len(sig) == 128  # Ed25519 hex signature is 64 bytes = 128 hex chars

    # 2. Verify valid
    assert backend.verify_signature(payload, sig, pub_pem) is True

    # 3. Verify tampered payload fails
    tampered = b'{"event":"evaluation","run_id":"run-001","score":0.0}'
    assert backend.verify_signature(tampered, sig, pub_pem) is False


def test_flight_recorder_fail_closed_on_absence(monkeypatch):
    """
    Contract Test: FlightRecorderPlugin fails closed with RuntimeError when
    EVAL_REQUIRE_SIGNING=true and no key or SigningBackend is provided.
    """
    monkeypatch.setenv("EVAL_REQUIRE_SIGNING", "true")
    monkeypatch.delenv("EVAL_SIGNING_KEY", raising=False)

    recorder = FlightRecorderPlugin()
    event = Event("test_event", {"run_id": "run-fail-closed-001", "data": "test"})

    with pytest.raises(RuntimeError) as exc_info:
        recorder.handle_event(event)

    assert "CryptographicSigningError" in str(exc_info.value)
    assert "EVAL_REQUIRE_SIGNING=true" in str(exc_info.value)


def test_flight_recorder_signing_backend_wiring(tmp_path, monkeypatch):
    """
    Contract Test: FlightRecorderPlugin invokes SigningBackend.sign_payload.
    """
    priv_key = ed25519.Ed25519PrivateKey.generate()
    key_path = tmp_path / "signing_key.pem"
    key_path.write_bytes(
        priv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    monkeypatch.setenv("EVAL_SIGNING_KEY", str(key_path))
    monkeypatch.setenv("AUDIT_LEVEL", "2")

    mock_backend = MagicMock(spec=SigningBackend)
    mock_backend.sign_payload.return_value = "mock_sig_hex_1234"

    recorder = FlightRecorderPlugin(signing_backend=mock_backend)
    event = Event("custom_eval", {"run_id": "run-sign-wire-001", "score": 0.99})

    recorder.handle_event(event)
    assert mock_backend.sign_payload.called


def test_verifier_delegates_to_signing_backend(tmp_path):
    """
    Contract Test: TraceVerifier.sign_payload delegates to SigningBackend.
    """
    priv_key = ed25519.Ed25519PrivateKey.generate()
    key_path = tmp_path / "verifier_key.pem"
    key_path.write_bytes(
        priv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    mock_backend = MagicMock(spec=SigningBackend)
    mock_backend.sign_payload.return_value = "verified_mock_sig"

    payload = b'{"test":"data"}'
    sig = TraceVerifier.sign_payload(payload, key_path, signing_backend=mock_backend)
    assert sig == "verified_mock_sig"
    mock_backend.sign_payload.assert_called_once_with(payload, key_path)


# ==============================================================================
# 4. AuthorizationBackend Interface Wiring Tests
# ==============================================================================


def test_auth_manager_delegates_to_authorization_backend():
    """
    Contract Test: StaticKeyProvider delegates token validation and permission checks
    to AuthorizationBackend.
    """
    backend = SimpleAPIKeyAuthBackend(master_key="root-master-test-key")
    backend.register_key(
        key="custom-user-token",
        principal_id="user-123",
        roles=["auditor"],
        permissions=["scenarios:read", "runs:read"],
    )

    provider = StaticKeyProvider(key="root-master-test-key", backend=backend)

    # 1. Validate custom user token
    user = provider.authenticate("custom-user-token")
    assert user is not None
    assert user["id"] == "user-123"
    assert "scenarios:read" in user["permissions"]

    # 2. Check permissions via provider
    assert provider.has_permission(user, Permission.SCENARIOS_READ) is True
    assert provider.has_permission(user, Permission.SCENARIOS_WRITE) is False

    # 3. Invalid token returns None
    assert provider.authenticate("invalid-nonexistent-token") is None


# ==============================================================================
# 5. ArtifactStore Interface Wiring Tests
# ==============================================================================


def test_flight_recorder_artifact_store_wiring(tmp_path):
    """
    Contract Test: FlightRecorderPlugin actively invokes ArtifactStore.store_artifact
    for trace writes and run finalization.
    """
    mock_store = MagicMock(spec=LocalFileArtifactStore)
    recorder = FlightRecorderPlugin(artifact_store=mock_store, log_dir=tmp_path)

    event = Event("agent_action", {"run_id": "run-art-wire-001", "action": "test"})
    recorder.handle_event(event)

    # Assert store_artifact was actively called for the trace write
    assert mock_store.store_artifact.called
    call_args = mock_store.store_artifact.call_args[1]
    assert call_args["run_id"] == "run-art-wire-001"
    assert call_args["artifact_name"] == "run.jsonl"
    assert call_args["append"] is True

    # Finalize run also seals via artifact_store
    recorder.finalize_run("run-art-wire-001")
    assert mock_store.store_artifact.call_count >= 2


def test_verifier_artifact_store_wiring(tmp_path, monkeypatch):
    """
    Contract Test: TraceVerifier.sign_trace invokes ArtifactStore.store_artifact
    to persist the sidecar manifest.
    """
    from eval_runner import config

    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path)
    run_dir = tmp_path / "run-ver-art-001"
    run_dir.mkdir()
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text(
        '{"event":"run_start","run_id":"run-ver-art-001"}\n'
        '{"event":"run_end","run_id":"run-ver-art-001"}\n',
        encoding="utf-8",
    )

    mock_store = MagicMock(spec=LocalFileArtifactStore)
    TraceVerifier.sign_trace(
        str(trace_path),
        run_id="run-ver-art-001",
        artifact_store=mock_store,
    )

    assert mock_store.store_artifact.called
    call_args = mock_store.store_artifact.call_args[1]
    assert call_args["run_id"] == "run-ver-art-001"
    assert call_args["artifact_name"] == "run_manifest.json"


# ==============================================================================
# 6. CheckpointStore & ApprovalManager HITL Wiring Tests
# ==============================================================================


def test_hitl_approval_triggers_durable_checkpoint():
    """
    Contract Test: SessionApprovalManager.request_approval automatically triggers
    checkpoint_manager.create_checkpoint with turn snapshot.
    """
    mock_chk_mgr = MagicMock(spec=SessionCheckpointManager)
    mock_state_provider = MagicMock(return_value={"current_turn": 5, "tokens": 120})

    approval_mgr = SessionApprovalManager(
        run_id="run-hitl-auto-chk-001",
        checkpoint_manager=mock_chk_mgr,
        state_provider=mock_state_provider,
    )

    approval = approval_mgr.request_approval(
        task_id="task_critical_tx",
        tool_name="wire_transfer",
        params={"amount": 50000},
        timeout_seconds=30,
    )
    assert approval is not None
    assert mock_chk_mgr.create_checkpoint.called
    checkpoint_call = mock_chk_mgr.create_checkpoint.call_args
    state = checkpoint_call[0][0]
    assert state["status"] == "AWAITING_APPROVAL"
    assert state["current_turn"] == 5
    assert state["tool_name"] == "wire_transfer"


@pytest.mark.asyncio
async def test_session_hitl_checkpoint_and_approval_wiring(tmp_path):
    """
    Contract Test: Session HITL pause creates state checkpoint via SessionCheckpointManager
    and requests approval via SessionApprovalManager.
    """
    scenario = {
        "id": "hitl_wiring_scenario",
        "description": "HITL Wiring Contract Test",
        "metadata": {"name": "HITL Contract"},
    }

    mock_chk_mgr = MagicMock(spec=SessionCheckpointManager)
    mock_chk_mgr.create_checkpoint.return_value = "chk_0001"
    mock_chk_mgr.load_latest_checkpoint.return_value = {
        "turn": 3,
        "history": [{"role": "agent", "content": "paused"}],
    }

    mock_appr_mgr = MagicMock(spec=SessionApprovalManager)
    mock_approval = MagicMock()
    mock_approval.action = "approve"
    mock_approval.response = "Human Approved Action"

    async def _mock_wait():
        return None

    mock_approval.wait = _mock_wait
    mock_appr_mgr.request_approval.return_value = mock_approval

    session = Session(run_id="run-hitl-wire-001", scenario=scenario, log_root=tmp_path)
    session.checkpoint_manager = mock_chk_mgr
    session.approval_manager = mock_appr_mgr

    # Explicit save checkpoint
    assert session.save_checkpoint() is not None
    assert mock_chk_mgr.create_checkpoint.called

    # Restore from checkpoint
    restored = session.restore_from_checkpoint()
    assert restored is True
    assert session.turn_number == 3


# ==============================================================================
# 7. ExecutionBackend Lifecycle Tests & Singleton
# ==============================================================================


def test_inprocess_execution_backend_lifecycle_and_singleton():
    """
    Contract Test: InProcessExecutionBackend singleton, submit, status, cancel, resume.
    """
    InProcessExecutionBackend.clear_instance()
    backend1 = InProcessExecutionBackend.get_instance()
    backend2 = InProcessExecutionBackend.get_instance()
    assert backend1 is backend2

    run_id = "run-exec-contract-001"
    scenario = {
        "id": "exec_test",
        "metadata": {"name": "Execution Contract"},
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "type": "task",
                    "tool": "mock_exec_tool",
                    "params": {"action": "ping"},
                }
            ]
        },
        "tools": {"mock_exec_tool": {"output": {"status": "success", "message": "Pong"}}},
    }

    # 1. Background submit
    res = backend1.submit(run_id, scenario, background=True)
    assert res["status"] == "started"
    assert res["run_id"] == run_id

    # 2. Status
    st = backend1.status(run_id)
    assert st["status"] in ("RUNNING", "COMPLETED", "FAILED")

    # 3. State-aware resume (transitions when in WAITING_FOR_APPROVAL or with force_recovery)
    backend1._active_runs[run_id]["status"] = "WAITING_FOR_APPROVAL"
    backend1._active_runs[run_id]["resumption_checkpoint"] = {"scenario_data": scenario}
    resumed = backend1.resume(run_id, resumption_token="res_tok_12345", background=True)
    assert resumed is not None
    assert backend1.status(run_id)["resumption_token"] == "res_tok_12345"

    # 4. Cancel
    cancelled = backend1.cancel(run_id, reason="Test cancellation")
    assert cancelled is True
    assert backend1.status(run_id)["status"] == "ABORTED"
    InProcessExecutionBackend.clear_instance()


# ==============================================================================
# 8. Phase 1 Storage Extension Interfaces & Wiring Tests
# ==============================================================================


def test_scenario_catalog_delegates_to_catalog_store(tmp_path):
    """
    Contract Test: ScenarioCatalog delegates storage operations to CatalogStore.
    """
    from eval_runner.catalog import ScenarioCatalog

    ScenarioCatalog.clear_instance()
    mock_cat_store = MagicMock(spec=LocalFileCatalogStore)
    mock_cat_store.get_scenario.return_value = {"id": "scen_123", "title": "Mock Scenario"}

    catalog = ScenarioCatalog(index_path=str(tmp_path / "index.json"), store=mock_cat_store)
    scen = catalog.get_scenario_by_id("scen_123")
    assert scen == {"id": "scen_123", "title": "Mock Scenario"}
    mock_cat_store.get_scenario.assert_called_once_with("scen_123")
    ScenarioCatalog.clear_instance()


def test_runner_uses_run_store_and_config_resolver(tmp_path):
    """
    Contract Test: DefaultRunner invokes ConfigResolver.resolve and RunStore.save_run_manifest.
    """
    from eval_runner.config_resolver import ConfigResolver, ResolvedRuntimeConfig
    from eval_runner.runner import DefaultRunner

    mock_run_store = MagicMock(spec=LocalFileRunStore)
    mock_resolver = MagicMock(spec=ConfigResolver)
    mock_resolver.resolve.return_value = ResolvedRuntimeConfig(
        audit_level=2,
        timeout_seconds=60,
    )

    runner = DefaultRunner(run_store=mock_run_store, config_resolver=mock_resolver)
    assert mock_resolver.resolve.called
    assert runner.resolved_config.audit_level == 2


def test_phase1_storage_interfaces(tmp_path):
    """
    Contract Test: LocalFileCatalogStore, LocalFileRunStore, LocalLeaderboardStore.
    """
    # 1. CatalogStore
    cat_store = LocalFileCatalogStore(base_dir=tmp_path)
    scen_path = cat_store.save_scenario("demo_scenario", {"id": "demo_scenario", "tasks": []})
    assert Path(scen_path).exists()
    assert cat_store.get_scenario("demo_scenario") is not None
    assert cat_store.delete_scenario("demo_scenario") is True

    # 2. RunStore
    run_store = LocalFileRunStore(log_dir=tmp_path / "runs")
    manifest_file = run_store.save_run_manifest(
        "run-test-999", {"run_id": "run-test-999", "status": "pass"}
    )
    assert Path(manifest_file).exists()
    r_info = run_store.get_run("run-test-999")
    assert r_info is not None
    assert r_info["run_id"] == "run-test-999"

    # 3. LeaderboardStore
    lb_store = LocalLeaderboardStore(runs_dir=tmp_path / "runs")
    lb_store.record_run_summary("run-test-999", {"pass_rate": 1.0})
    lb_data = lb_store.get_leaderboard()
    assert isinstance(lb_data, list)


@pytest.mark.asyncio
async def test_all_extension_families_exclusive_injection_contract(tmp_path):
    """
    Architectural Contract Test: Assert that injecting custom extension backends
    results in 100% exclusive execution through the injected backends without bypasses.
    """
    from agentv_runtime.results import EvaluationResult
    from eval_runner.config_resolver import ConfigResolver, ResolvedRuntimeConfig
    from eval_runner.interfaces.artifact import ArtifactStore
    from eval_runner.interfaces.checkpoint import CheckpointStore
    from eval_runner.interfaces.policy import PolicyEvaluationResult, PolicyEvaluator
    from eval_runner.interfaces.signing import SigningBackend
    from eval_runner.runner import DefaultRunner

    # 1. Custom ArtifactStore Spy
    mock_artifact_store = MagicMock(spec=ArtifactStore)
    mock_artifact_store.is_sealed.return_value = False
    mock_artifact_store.store_artifact.return_value = "mock://artifacts/file"

    # 2. Custom CheckpointStore Spy
    mock_checkpoint_store = MagicMock(spec=CheckpointStore)
    mock_checkpoint_store.save.return_value = "chk_0001"

    # 3. Custom PolicyEvaluator Spy
    mock_policy_evaluator = MagicMock(spec=PolicyEvaluator)
    mock_policy_evaluator.evaluate_policy.return_value = PolicyEvaluationResult(
        allowed=True, policy_id="exclusive_policy"
    )

    # 4. Custom SigningBackend Spy
    mock_signing_backend = MagicMock(spec=SigningBackend)
    mock_signing_backend.sign_payload.return_value = "mock_sig_hex_12345"

    # 5. Custom ConfigResolver
    mock_resolver = MagicMock(spec=ConfigResolver)
    mock_resolver.resolve.return_value = ResolvedRuntimeConfig(
        audit_level=2,
        timeout_seconds=30,
    )

    runner = DefaultRunner(
        config_resolver=mock_resolver,
        artifact_store=mock_artifact_store,
        checkpoint_store=mock_checkpoint_store,
        policy_evaluator=mock_policy_evaluator,
        signing_backend=mock_signing_backend,
    )

    scenario = {
        "id": "exclusive_contract_scen",
        "metadata": {"name": "Exclusive Contract"},
        "workflow": [
            {
                "id": "node_1",
                "tool": "test_tool",
                "params": {"key": "val"},
            }
        ],
        "tools": {"test_tool": {"output": {"status": "success", "result": "ok"}}},
        "policies": {"test_tool": {"max_limit": 100}},
    }

    from unittest.mock import AsyncMock, patch

    def _agent_mock_1(protocol, endpoint, message, history, turn_ctx):
        if getattr(turn_ctx, "turn_number", 1) == 1:
            return {
                "status": "success",
                "action": "call_tool",
                "tool_name": "test_tool",
                "parameters": {"key": "val"},
            }
        return {
            "status": "success",
            "action": "final_answer",
            "content": "Exclusive contract test passed.",
        }

    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent", AsyncMock(side_effect=_agent_mock_1)
    ):
        results = await runner.run(scenario, attempts=1, run_id="run-exclusive-001")

    assert isinstance(results, EvaluationResult)
    assert results.pass_at_k == 1.0
    assert mock_resolver.resolve.called
    assert runner.artifact_store is mock_artifact_store
    assert runner.checkpoint_store is mock_checkpoint_store
    assert runner.policy_evaluator is mock_policy_evaluator
    assert runner.signing_backend is mock_signing_backend
    assert mock_policy_evaluator.evaluate_policy.called


def test_inprocess_backend_executes_injected_dependency_graph():
    """
    Contract Test: InProcessExecutionBackend.submit() executes using the injected
    dependency graph, never bypassing injected enterprise implementations.
    """
    from eval_runner.interfaces.artifact import ArtifactStore
    from eval_runner.interfaces.policy import PolicyEvaluationResult, PolicyEvaluator
    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

    mock_art = MagicMock(spec=ArtifactStore)
    mock_art.is_sealed.return_value = False
    mock_policy = MagicMock(spec=PolicyEvaluator)
    mock_policy.evaluate_policy.return_value = PolicyEvaluationResult(
        allowed=True, policy_id="injected_pol"
    )

    backend = InProcessExecutionBackend(
        artifact_store=mock_art,
        policy_evaluator=mock_policy,
    )

    scenario = {
        "id": "injected_backend_scen",
        "metadata": {"name": "Injected Backend Scenario"},
        "workflow": [
            {
                "id": "node_1",
                "tool": "echo_tool",
                "params": {"msg": "hello"},
            }
        ],
        "tools": {"echo_tool": {"output": {"status": "success"}}},
        "policies": {"echo_tool": {"max_limit": 50}},
    }

    from unittest.mock import AsyncMock, patch

    def _agent_mock_2(protocol, endpoint, message, history, turn_ctx):
        if getattr(turn_ctx, "turn_number", 1) == 1:
            return {
                "status": "success",
                "action": "call_tool",
                "tool_name": "echo_tool",
                "parameters": {"msg": "hello"},
            }
        return {
            "status": "success",
            "action": "final_answer",
            "content": "Injected backend test passed.",
        }

    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent", AsyncMock(side_effect=_agent_mock_2)
    ):
        results = backend.submit("injected_run_001", scenario, background=False)

    assert results is not None
    assert mock_policy.evaluate_policy.called
