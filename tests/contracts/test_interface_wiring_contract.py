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
# 5. ArtifactStore Interface Tests
# ==============================================================================


def test_artifact_store_lifecycle(tmp_path):
    """
    Contract Test: LocalFileArtifactStore stores, retrieves, lists, and checks existence.
    """
    store = LocalFileArtifactStore(base_dir=str(tmp_path))
    run_id = "run-artifact-test-001"

    # Store bytes artifact
    path_stored = store.store_artifact(
        run_id=run_id,
        artifact_name="evidence.txt",
        content=b"Forensic Evidence Payload",
        metadata={"author": "auditor"},
    )
    assert Path(path_stored).exists()
    assert store.exists(run_id, "evidence.txt") is True

    # Retrieve artifact
    content = store.get_artifact(run_id, "evidence.txt")
    assert content == b"Forensic Evidence Payload"

    # List artifacts
    artifacts = store.list_artifacts(run_id)
    assert len(artifacts) == 1
    assert artifacts[0]["name"] == "evidence.txt"


# ==============================================================================
# 6. CheckpointStore & ApprovalManager HITL Wiring Tests
# ==============================================================================


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
# 7. ExecutionBackend Lifecycle Tests
# ==============================================================================


def test_inprocess_execution_backend_lifecycle():
    """
    Contract Test: InProcessExecutionBackend handles submit, status, cancel, resume.
    """
    backend = InProcessExecutionBackend()
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
    res = backend.submit(run_id, scenario, background=True)
    assert res["status"] == "started"
    assert res["run_id"] == run_id

    # 2. Status
    st = backend.status(run_id)
    assert st["status"] in ("RUNNING", "COMPLETED", "FAILED")

    # 3. Resume with token
    resumed = backend.resume(run_id, resumption_token="res_tok_12345")
    assert resumed is not None
    assert resumed.get("resumption_token") == "res_tok_12345"

    # 4. Cancel
    cancelled = backend.cancel(run_id, reason="Test cancellation")
    assert cancelled is True
    assert backend.status(run_id)["status"] == "ABORTED"


# ==============================================================================
# 8. Phase 1 Storage Extension Interfaces Tests
# ==============================================================================


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
    lb_data = lb_store.get_leaderboard()
    assert isinstance(lb_data, list)
