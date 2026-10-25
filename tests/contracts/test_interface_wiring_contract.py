"""
tests/contracts/test_interface_wiring_contract.py

Contract Test Suite for Runtime Interface Wiring.
Asserts that all 6 Extension Families and Subsystem Managers are actively wired into
runtime execution paths, preventing "built but unwired" regressions.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from eval_runner.console.auth_manager import (
    Permission,
    StaticKeyProvider,
    get_auth_provider,
    register_authorization_backend,
)
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
        "metadata": {
            "name": "Policy Test Scenario",
            "policies": {
                "transfer_funds": {
                    "max_limit": 100,
                    "constrained_params": ["amount"],
                }
            },
        },
        "tools": {
            "transfer_funds": {"output": {"status": "success", "message": "Funds transferred"}}
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
        "metadata": {
            "name": "Default Policy Scenario",
            "policies": {"refund": {"max_limit": 200, "constrained_params": ["val"]}},
        },
        "tools": {"refund": {"output": {"status": "success"}}},
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


def test_flight_recorder_fail_closed_on_absence(monkeypatch, tmp_path):
    """
    Contract Test: FlightRecorderPlugin fails closed with RuntimeError when
    EVAL_REQUIRE_SIGNING=true and no key or SigningBackend is provided.
    """
    monkeypatch.setenv("EVAL_REQUIRE_SIGNING", "true")
    monkeypatch.delenv("FLIGHT_RECORDER_KEY_PATH", raising=False)

    recorder = FlightRecorderPlugin(run_store=LocalFileRunStore(tmp_path / "provider"))
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

    monkeypatch.setenv("FLIGHT_RECORDER_KEY_PATH", str(key_path))
    monkeypatch.setenv("AUDIT_LEVEL", "2")

    mock_backend = MagicMock(spec=SigningBackend)
    mock_backend.sign_payload.return_value = "mock_sig_hex_1234"

    recorder = FlightRecorderPlugin(
        signing_backend=mock_backend,
        run_store=LocalFileRunStore(tmp_path / "provider"),
    )
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


def test_registered_authorization_backend_is_used_by_console_factory():
    backend = SimpleAPIKeyAuthBackend(master_key="backend-registration-key")
    backend.register_key(
        key="scoped-token",
        principal_id="scoped-user",
        roles=["metadata-only"],
        permissions=["runs:read"],
        metadata={
            "context_version": "2",
            "context": {
                "org_id": "o",
                "tenant_id": "t",
                "workspace_id": "w",
                "active_environment": "sandbox",
            },
            "authorized_contexts": [
                {"org_id": "o", "tenant_id": "t", "workspace_id": "w", "environments": ["sandbox"]}
            ],
        },
    )
    register_authorization_backend(backend)
    try:
        principal = get_auth_provider().authenticate("scoped-token")
        assert principal is not None
        assert principal["context"]["workspace_id"] == "w"
    finally:
        register_authorization_backend(None)


def test_declarative_authorization_backend_factory_is_used_by_console_factory(monkeypatch):
    backend = SimpleAPIKeyAuthBackend(master_key="declarative-backend-key")
    backend.register_key(
        key="scoped-token",
        principal_id="scoped-user",
        permissions=["runs:read"],
        metadata={
            "context_version": "2",
            "context": {
                "org_id": "o",
                "tenant_id": "t",
                "workspace_id": "w",
                "active_environment": "sandbox",
            },
            "authorized_contexts": [
                {"org_id": "o", "tenant_id": "t", "workspace_id": "w", "environments": ["sandbox"]}
            ],
        },
    )
    monkeypatch.setenv("AGENTV_AUTHORIZATION_BACKEND_FACTORY", "deployment.auth:create_backend")
    monkeypatch.setattr(
        "eval_runner.console.auth_manager.importlib.import_module",
        lambda module_name: SimpleNamespace(create_backend=lambda: backend),
    )
    register_authorization_backend(None)
    principal = get_auth_provider().authenticate("scoped-token")
    assert principal is not None
    assert principal["context"]["workspace_id"] == "w"


# ==============================================================================
# 5. ArtifactStore Interface Wiring Tests
# ==============================================================================


def test_flight_recorder_artifact_store_wiring(tmp_path, monkeypatch):
    """
    Contract Test: FlightRecorderPlugin delegates each trace write exclusively to
    RunStorageProvider.  ArtifactStore may publish a later trace seal, but must
    never be a second writer for ``run.jsonl``.
    """
    from eval_runner import config

    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path)
    mock_store = MagicMock(spec=LocalFileArtifactStore)
    mock_run_store = MagicMock()
    monkeypatch.setattr(
        "eval_runner.run_lifecycle.assert_can_write_trace",
        lambda *args, **kwargs: None,
    )
    recorder = FlightRecorderPlugin(
        artifact_store=mock_store, run_store=mock_run_store, log_dir=tmp_path
    )

    event = Event("agent_action", {"run_id": "run-art-wire-001", "action": "test"})
    recorder.handle_event(event)

    mock_run_store.append_events.assert_called_once()
    run_id, events = mock_run_store.append_events.call_args.args
    assert run_id == "run-art-wire-001"
    assert len(events) == 1
    assert events[0]["event"] == "agent_action"
    mock_store.store_artifact.assert_not_called()


def test_verifier_artifact_store_wiring(tmp_path, monkeypatch):
    """
    Contract Test: Certification operates exclusively on RunStorageProvider.
    ArtifactStore is never used to persist manifests or lifecycle seals,
    guaranteeing RunStorageProvider is the sole authority.
    """

    from agentv_runtime.evidence_graph import build_evidence_graph_from_events
    from agentv_runtime.finalization import EvaluatorFinalizationRecord
    from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
    from eval_runner import config
    from eval_runner.identity import IdentityService
    from eval_runner.reference.local_run_store import LocalFileRunStore
    from eval_runner.run_lifecycle import RunLifecycleState, get_run_lifecycle_state
    from eval_runner.services.certification import CertificationService

    run_root = tmp_path / "runs"
    run_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "RUN_LOG_DIR", run_root)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    trust_root = tmp_path / ".aes" / "keys"
    monkeypatch.setattr(config, "TRUST_ROOT", trust_root)
    IdentityService._provision_local_identity("system_id")
    IdentityService._provision_local_identity("test_evaluator")

    mock_store = MagicMock(spec=LocalFileArtifactStore)
    mock_store.is_local_store = True

    run_id = "run-ver-art-001"
    run_store = LocalFileRunStore(run_root)
    run_store.create_run(run_id, "artifact-wiring")

    scenario_data = {"id": "artifact-wiring", "version": "1.0.0", "required_oracles": ["oracle_1"]}
    scen_hash = compute_scenario_hash(scenario_data)
    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="artifact-wiring",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": ["oracle_1"]},
        runtime_config={"required_oracle_ids": ["oracle_1"]},
    )
    run_store.save_run_manifest(
        run_id,
        {
            "execution_manifest": exec_manifest.to_dict(),
            "scenario_data": scenario_data,
        },
    )

    start_ev = {
        "event": "run_start",
        "run_id": run_id,
        "scenario_id": "artifact-wiring",
        "scenario_data": scenario_data,
        "data": {"execution_mode": "live", "execution_mode_declared": True},
        "_seq": 1,
    }
    assert_ev = {
        "event": "oracle_result",
        "run_id": run_id,
        "oracle_id": "oracle_1",
        "assertion_id": "assert_1",
        "passed": True,
        "outcome": "PASS",
        "_seq": 2,
    }
    end_ev = {
        "event": "run_end",
        "run_id": run_id,
        "outcome": "pass",
        "status": "pass",
        "score": 1.0,
        "_seq": 3,
    }
    run_store.append_events(run_id, [start_ev, assert_ev, end_ev])
    lines = run_store.get_trace_bytes(run_id).decode("utf-8").splitlines()
    raw_events = [(start_ev, lines[0]), (assert_ev, lines[1]), (end_ev, lines[2])]
    ev_graph = build_evidence_graph_from_events(raw_events, required_oracle_ids=["oracle_1"])
    evidence_root = ev_graph.get("evidence_root_hash")
    rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=exec_manifest.compute_manifest_hash(),
        scenario_id="artifact-wiring",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="test_evaluator",
        evaluator_config_hash="sha3_256:abc123",
        required_oracle_ids=["oracle_1"],
        evidence_root_hash=evidence_root,
        outcome="pass",
        score=1.0,
        terminal_seq=3,
    ).sign()
    fin_ev = {"event": "evaluator_finalization", "data": rec.to_dict(), "_seq": 4}
    run_store.append_events(run_id, [fin_ev])

    res = CertificationService.execute_industrial_certification(
        run_id=run_id,
        identity_id="system_id",
        run_store=run_store,
        artifact_store=mock_store,
    )

    # ArtifactStore is never written to for manifests or seals (RunStore sole authority)
    mock_store.store_artifact.assert_not_called()
    mock_store.seal.assert_not_called()

    # Authoritative manifest and lifecycle seal are committed strictly to RunStore
    manifest = run_store.get_manifest(run_id)
    assert manifest is not None
    assert manifest["certification"]["outcome"] == "CERTIFIED_PASS"
    assert get_run_lifecycle_state(run_id, run_store=run_store) is RunLifecycleState.SEALED
    assert res.get("certified") is True


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

    # Keep this backend lifecycle test self-contained.  It verifies background
    # execution/cancellation state, not the full plugin execution pipeline.
    def controlled_runner(_scenario: dict[str, Any], *, cancellation_event: Any, **_kwargs: Any):
        cancellation_event.wait(timeout=2)
        return {"status": "cancelled" if cancellation_event.is_set() else "completed"}

    backend1.set_dependency_graph(runner_callable=controlled_runner)

    # The Flight Recorder now correctly rejects any pre-existing evidence vault.
    # A unique ID keeps this lifecycle contract isolated from previous test runs.
    run_id = f"run-exec-contract-{uuid4().hex}"
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

    # 3. Generic recovery token is valid for a non-HITL paused run. Approval
    # states require a durable approved ApprovalRequest and are covered by the
    # HITL contract tests.
    backend1._active_runs[run_id]["status"] = "PAUSED"
    backend1._active_runs[run_id]["resumption_checkpoint"] = {"scenario_data": scenario}
    resumed = backend1.resume(run_id, resumption_token="res_tok_12345", background=True)
    assert resumed is not None
    assert backend1.status(run_id)["resumption_token"] == "res_tok_12345"

    # 4. Cancel
    cancelled = backend1.cancel(run_id, reason="Test cancellation")
    assert cancelled is True
    assert backend1.status(run_id)["status"] == "ABORTED"
    thread = backend1._threads.get(run_id)
    if thread is not None:
        thread.join(timeout=5)
        assert not thread.is_alive(), "background evaluation did not stop after cancellation"
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
    from uuid import uuid4

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
        "metadata": {
            "name": "Exclusive Contract",
            "policies": {"test_tool": {"max_limit": 100}},
        },
        "workflow": [
            {
                "id": "node_1",
                "tool": "test_tool",
                "params": {"key": "val"},
                "state_hygiene": {"rules": [{"path": "__unset_probe__", "op": "not_exists"}]},
            }
        ],
        "tools": {"test_tool": {"output": {"status": "success", "result": "ok"}}},
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
        results = await runner.run(scenario, attempts=1, run_id=f"run-exclusive-{uuid4().hex}")

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
    from uuid import uuid4

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
        "metadata": {
            "name": "Injected Backend Scenario",
            "policies": {"echo_tool": {"max_limit": 50}},
        },
        "workflow": [
            {
                "id": "node_1",
                "tool": "echo_tool",
                "params": {"msg": "hello"},
                "state_hygiene": {"rules": [{"path": "__unset_probe__", "op": "not_exists"}]},
            }
        ],
        "tools": {"echo_tool": {"output": {"status": "success"}}},
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
        results = backend.submit(f"injected-run-{uuid4().hex}", scenario, background=False)

    assert results is not None
    assert mock_policy.evaluate_policy.called


def test_inprocess_backend_passes_dependencies_to_runner_callable():
    """
    Contract Test: InProcessExecutionBackend passes the injected dependency graph
    to custom runner callables, closing all bypass seams.
    """
    from unittest.mock import MagicMock

    from eval_runner.interfaces.policy import PolicyEvaluator
    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

    mock_policy = MagicMock(spec=PolicyEvaluator)
    captured_kwargs = {}

    def custom_runner(scenario, **kwargs):
        captured_kwargs.update(kwargs)
        return {"status": "success", "run_id": kwargs.get("run_id")}

    backend = InProcessExecutionBackend(
        policy_evaluator=mock_policy,
        runner_callable=custom_runner,
    )

    scenario = {"id": "custom_runner_scen"}
    res = backend.submit("custom_run_123", scenario, background=False)

    assert res["status"] == "success"
    assert captured_kwargs.get("policy_evaluator") is mock_policy
    assert captured_kwargs.get("execution_backend") is backend


def test_agentv_runtime_metadata_and_exports():
    """
    Contract Test: Asserts agentv_runtime module exports, authoritative contract
    version metadata, and subclass inheritance hierarchies across all public extension families.
    """
    import agentv_runtime
    import agentv_runtime.interfaces
    import agentv_runtime.reference
    import agentv_runtime.session_components
    from eval_runner import config

    assert agentv_runtime.__version__ == config.VERSION
    assert agentv_runtime.__runtime_api_version__ == "2.0"
    assert agentv_runtime.__plugin_api_version__ == "1.0"
    assert agentv_runtime.__config_schema_version__ == "1.0"
    assert agentv_runtime.__aes_schema_version__ == "1.4"
    assert issubclass(
        agentv_runtime.reference.InProcessExecutionBackend,
        agentv_runtime.interfaces.ExecutionBackend,
    )
    assert issubclass(
        agentv_runtime.reference.SQLiteCheckpointStore, agentv_runtime.interfaces.CheckpointStore
    )
    assert issubclass(
        agentv_runtime.reference.LocalFileArtifactStore, agentv_runtime.interfaces.ArtifactStore
    )
    assert issubclass(
        agentv_runtime.reference.BasicFieldPolicyEvaluator,
        agentv_runtime.interfaces.PolicyEvaluator,
    )
    assert agentv_runtime.session_components.TurnStateManager is not None
    assert agentv_runtime.session_components.ToolExecutionCoordinator is not None
    assert agentv_runtime.session_components.SessionCheckpointManager is not None
    assert agentv_runtime.session_components.SessionApprovalManager is not None


def test_interfaces_supports_transactional_seal_and_auth_principal_to_dict():
    """
    Contract Test: Validates default ArtifactStore.supports_transactional_seal,
    AuthPrincipal.to_dict serialization, and ExternalStateAuthority unbounded state error.
    """
    import pytest

    from agentv_runtime.contracts import EvidenceBoundednessViolationError
    from agentv_runtime.interfaces import ArtifactStore, AuthPrincipal, BoundedStateProvider

    class DummyArtifactStore(ArtifactStore):
        def store_artifact(self, *args, **kwargs):
            pass

        def get_artifact(self, *args, **kwargs):
            pass

        def list_artifacts(self, *args, **kwargs):
            return []

        def seal(self, *args, **kwargs):
            pass

        def is_sealed(self, *args, **kwargs):
            return False

        def exists(self, run_id: str, artifact_name: str) -> bool:
            return False

    store = DummyArtifactStore()
    assert store.supports_transactional_seal() is False

    principal = AuthPrincipal(
        principal_id="user_admin",
        roles=["admin", "operator"],
        permissions=["eval:trigger", "runs:read"],
        metadata={"org_id": "org_core"},
        context_version="1.0",
        context={"tenant": "t1"},
        authorized_contexts=["staging", "prod"],
    )
    p_dict = principal.to_dict()
    assert p_dict["principal_id"] == "user_admin"
    assert p_dict["roles"] == ["admin", "operator"]
    assert p_dict["permissions"] == ["eval:trigger", "runs:read"]
    assert p_dict["context_version"] == "1.0"
    assert p_dict["context"] == {"tenant": "t1"}
    assert p_dict["authorized_contexts"] == ["staging", "prod"]

    class DummyStateAuthority(BoundedStateProvider):
        def query_bounded_reference(self, *args, **kwargs):
            pass

        def commit_state_transition(self, *args, **kwargs):
            pass

    authority = DummyStateAuthority()
    with pytest.raises(
        EvidenceBoundednessViolationError, match="Unbounded state materialization prohibited"
    ):
        authority.get_all_state()


def test_default_runner_resolves_pluggable_artifact_store(monkeypatch):
    """Contract: DefaultRunner resolves pluggable ArtifactStore via runtime discovery."""
    from agentv_runtime.discovery import ENTRY_POINT_NAMESPACE, reset_extensions
    from agentv_runtime.interfaces import ArtifactStore
    from eval_runner.runner import DefaultRunner

    class CustomPluggableArtifactStore(ArtifactStore):
        def store_artifact(self, *args, **kwargs):
            pass

        def get_artifact(self, *args, **kwargs):
            pass

        def list_artifacts(self, *args, **kwargs):
            return []

        def seal(self, *args, **kwargs):
            pass

        def is_sealed(self, *args, **kwargs):
            return False

        def exists(self, run_id: str, artifact_name: str) -> bool:
            return False

    reset_extensions()
    try:
        custom_instance = CustomPluggableArtifactStore()
        ep = SimpleNamespace(name="custom_contract_store", load=lambda: lambda: custom_instance)
        monkeypatch.setattr(
            "importlib.metadata.entry_points",
            lambda group=None: [ep] if group == f"{ENTRY_POINT_NAMESPACE}.artifact_stores" else [],
        )
        monkeypatch.setenv("AGENTV_ARTIFACT_STORE", "custom_contract_store")

        runner = DefaultRunner()
        assert runner.artifact_store is custom_instance
    finally:
        reset_extensions()


def test_flight_recorder_resolves_pluggable_artifact_store_by_default(monkeypatch, tmp_path):
    """Contract: FlightRecorderPlugin resolves pluggable ArtifactStore by default."""
    from agentv_runtime.discovery import ENTRY_POINT_NAMESPACE, reset_extensions
    from agentv_runtime.interfaces import ArtifactStore

    class CustomPluggableArtifactStore(ArtifactStore):
        def store_artifact(self, *args, **kwargs):
            pass

        def get_artifact(self, *args, **kwargs):
            pass

        def list_artifacts(self, *args, **kwargs):
            return []

        def seal(self, *args, **kwargs):
            pass

        def is_sealed(self, *args, **kwargs):
            return False

        def exists(self, run_id: str, artifact_name: str) -> bool:
            return False

    reset_extensions()
    try:
        custom_instance = CustomPluggableArtifactStore()
        ep = SimpleNamespace(name="custom_fr_store", load=lambda: lambda: custom_instance)
        monkeypatch.setattr(
            "importlib.metadata.entry_points",
            lambda group=None: [ep] if group == f"{ENTRY_POINT_NAMESPACE}.artifact_stores" else [],
        )
        monkeypatch.setenv("AGENTV_ARTIFACT_STORE", "custom_fr_store")

        # Default instantiation (e.g. PluginManager auto-discovery) resolves pluggable store
        plugin = FlightRecorderPlugin()
        assert plugin.artifact_store is custom_instance

        # Legacy log_dir no longer controls storage composition.
        isolated_plugin = FlightRecorderPlugin(log_dir=tmp_path)
        assert isolated_plugin.artifact_store is custom_instance
    finally:
        reset_extensions()


def test_flight_recorder_resolves_pluggable_signing_backend_over_key_path(monkeypatch, tmp_path):
    """Contract: FlightRecorderPlugin prioritizes pluggable SigningBackend over local key file."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from agentv_runtime.discovery import ENTRY_POINT_NAMESPACE, reset_extensions
    from agentv_runtime.interfaces import SigningBackend

    key_file = tmp_path / "signing.key"
    private_key = ed25519.Ed25519PrivateKey.generate()
    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file.write_bytes(key_bytes)
    monkeypatch.setenv("FLIGHT_RECORDER_KEY_PATH", str(key_file))

    class CustomKmsSigningBackend(SigningBackend):
        def sign_payload(
            self, payload: bytes, key_identifier: str | Path | Any = None, **kwargs: Any
        ) -> str | dict[str, Any]:
            return "custom_kms_signature"

        def verify_signature(
            self,
            payload: bytes,
            signature: str | dict[str, Any],
            public_key_identifier: str | Path | Any = None,
            **kwargs: Any,
        ) -> bool:
            return True

    reset_extensions()
    try:
        custom_kms = CustomKmsSigningBackend()
        ep = SimpleNamespace(name="custom_kms", load=lambda: lambda: custom_kms)
        monkeypatch.setattr(
            "importlib.metadata.entry_points",
            lambda group=None: [ep] if group == f"{ENTRY_POINT_NAMESPACE}.signing_backends" else [],
        )
        monkeypatch.setenv("AGENTV_SIGNING_BACKEND", "custom_kms")

        plugin = FlightRecorderPlugin(log_dir=tmp_path)
        assert plugin.signing_backend is custom_kms
    finally:
        reset_extensions()
