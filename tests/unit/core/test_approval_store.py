"""
tests/unit/core/test_approval_store.py
Comprehensive unit tests for ApprovalRequest, ApprovalStore implementations
(FileApprovalStore and SQLiteApprovalStore), SessionApprovalManager durable requests,
InProcessExecutionBackend resumption state guards, and the hitl-resume CLI command.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentv_runtime.interfaces import ApprovalRequest
from eval_runner.handlers.evaluation import handle_hitl_resume
from eval_runner.reference.approval_store import (
    FileApprovalStore,
    SQLiteApprovalStore,
    get_default_approval_store,
    reset_default_approval_store,
)
from eval_runner.reference.inprocess_backend import InProcessExecutionBackend
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.run_lifecycle import RunLifecycleState
from eval_runner.session_components.approval_manager import SessionApprovalManager


class TestApprovalRequest:
    def test_to_dict_and_from_dict(self):
        req = ApprovalRequest(
            approval_token="tok_12345",
            run_id="run_test_01",
            turn_index=2,
            outbound_payload_hash="sha3_abc123",
            required_role="compliance_officer",
            reviewer_credentials={"level": "admin"},
            status="PENDING",
            rule_id="RULE_WA_ESSB_5395",
            checkpoint_id="chk_999",
            action_payload={"tool": "submit_decision", "amount": 50000},
            prompt="Approval required for loan decision",
            metadata={"source": "test"},
        )

        d = req.to_dict()
        assert d["approval_token"] == "tok_12345"
        assert d["run_id"] == "run_test_01"
        assert d["turn_index"] == 2
        assert d["outbound_payload_hash"] == "sha3_abc123"
        assert d["required_role"] == "compliance_officer"
        assert d["status"] == "PENDING"
        assert d["rule_id"] == "RULE_WA_ESSB_5395"

        restored = ApprovalRequest.from_dict(d)
        assert restored.approval_token == req.approval_token
        assert restored.run_id == req.run_id
        assert restored.turn_index == req.turn_index
        assert restored.outbound_payload_hash == req.outbound_payload_hash
        assert restored.required_role == req.required_role
        assert restored.reviewer_credentials == req.reviewer_credentials
        assert restored.status == req.status
        assert restored.rule_id == req.rule_id
        assert restored.checkpoint_id == req.checkpoint_id
        assert restored.action_payload == req.action_payload


class TestFileApprovalStore:
    def test_lifecycle(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")

        req = ApprovalRequest(
            approval_token="token_alpha",
            run_id="run_file_01",
            turn_index=1,
            outbound_payload_hash="hash_alpha",
            required_role="auditor",
        )

        # Create
        created = store.create_request(req)
        assert created.approval_token == "token_alpha"

        # Lookup by token
        loaded = store.get_request("token_alpha")
        assert loaded is not None
        assert loaded.run_id == "run_file_01"
        assert loaded.status == "PENDING"

        # Lookup by run_id
        loaded_by_run = store.get_request_by_run_id("run_file_01")
        assert loaded_by_run is not None
        assert loaded_by_run.approval_token == "token_alpha"

        # List pending
        pending = store.list_pending()
        assert len(pending) == 1
        assert pending[0].approval_token == "token_alpha"

        pending_for_run = store.list_pending(run_id="run_file_01")
        assert len(pending_for_run) == 1

        pending_for_other = store.list_pending(run_id="run_other")
        assert len(pending_for_other) == 0

        # Resolve APPROVED
        resolved = store.resolve_request(
            approval_token="token_alpha",
            decision="APPROVED",
            decided_by="officer_alice",
            decision_reason="All statutory conditions satisfied",
        )
        assert resolved.status == "APPROVED"
        assert resolved.decision == "APPROVED"
        assert resolved.decided_by == "officer_alice"
        assert resolved.decided_at is not None

        # Verify list_pending now empty
        assert len(store.list_pending()) == 0

        # Verify get_request reflects updated status
        reloaded = store.get_request("token_alpha")
        assert reloaded is not None
        assert reloaded.status == "APPROVED"

        # Delete
        deleted = store.delete_request("token_alpha")
        assert deleted is True
        assert store.get_request("token_alpha") is None

    def test_empty_keys_and_edge_cases(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")
        assert store.get_request("") is None
        assert store.get_request_by_run_id("") is None
        assert store.delete_request("") is False
        assert store.delete_request("non_existent_token") is False

    def test_env_var_and_default_init(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        custom_dir = tmp_path / "custom_env_approvals"
        monkeypatch.setenv("AGENTV_APPROVALS_DIR", str(custom_dir))
        store = FileApprovalStore()
        assert store.base_dir == custom_dir.resolve()

        monkeypatch.delenv("AGENTV_APPROVALS_DIR", raising=False)
        store_default = FileApprovalStore()
        assert ".agentv" in str(store_default.base_dir)

    def test_resolve_errors(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")

        with pytest.raises(KeyError, match="not found"):
            store.resolve_request("non_existent_token", "APPROVED")

        req = ApprovalRequest(
            approval_token="token_beta",
            run_id="run_file_02",
            turn_index=1,
            outbound_payload_hash="hash_beta",
        )
        store.create_request(req)

        with pytest.raises(ValueError, match="Invalid approval decision"):
            store.resolve_request("token_beta", "MAYBE")

    def test_fallback_scan_when_token_file_missing_and_corruptions(self, tmp_path: Path):
        base_dir = tmp_path / "approvals"
        store = FileApprovalStore(base_dir=base_dir)

        req = ApprovalRequest(
            approval_token="token_gamma",
            run_id="run_file_03",
            turn_index=1,
            outbound_payload_hash="hash_gamma",
        )
        store.create_request(req)

        # 1. Corrupt token file: should log and fall back to scan
        token_file = base_dir / "token_token_gamma.json"
        token_file.write_text("NOT_VALID_JSON", encoding="utf-8")
        found = store.get_request("token_gamma")
        assert found is not None
        assert found.run_id == "run_file_03"

        # 2. Corrupted run file during scan: skipped gracefully
        corrupt_run = base_dir / "corrupted_run.json"
        corrupt_run.write_text("{bad_json", encoding="utf-8")
        found_again = store.get_request("token_gamma")
        assert found_again is not None

        # 3. Corrupted run file in get_request_by_run_id
        assert store.get_request_by_run_id("corrupted_run") is None

        # 4. Corrupted file during list_pending is skipped
        store.create_request(
            ApprovalRequest(
                approval_token="token_delta",
                run_id="run_file_04",
                turn_index=1,
                outbound_payload_hash="hash_delta",
            )
        )
        pending_list = store.list_pending()
        assert len(pending_list) == 1
        assert pending_list[0].approval_token == "token_delta"

        # 5. Unknown token returns None
        assert store.get_request("non_existent_anywhere") is None

    def test_directory_scan_exception_handling(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")
        with patch.object(Path, "glob", side_effect=OSError("Disk failure")):
            assert store.get_request("any_token") is None
            assert store.list_pending() == []

    def test_ensure_dir_oserror_handling(self, tmp_path: Path):
        with patch.object(Path, "mkdir", side_effect=OSError("Permission denied")):
            store = FileApprovalStore(base_dir=tmp_path / "protected")
            assert store.base_dir == (tmp_path / "protected").resolve()

    def test_delete_request_unlink_exceptions(self, tmp_path: Path):
        base_dir = tmp_path / "approvals_unlink"
        store = FileApprovalStore(base_dir=base_dir)
        req = ApprovalRequest(
            approval_token="token_unlink",
            run_id="run_unlink",
            turn_index=1,
            outbound_payload_hash="h1",
        )
        store.create_request(req)

        with patch.object(Path, "unlink", side_effect=OSError("Locked file")):
            # Should catch OSError and return False
            res = store.delete_request("token_unlink")
            assert res is False

    def test_delete_request_reports_and_removes_both_durable_records(self, tmp_path: Path):
        base_dir = tmp_path / "approvals_delete"
        store = FileApprovalStore(base_dir=base_dir)
        request = ApprovalRequest(
            approval_token="token_delete",
            run_id="run_delete",
            turn_index=1,
            outbound_payload_hash="hash_delete",
        )
        store.create_request(request)

        assert store.delete_request(request.approval_token) is True
        assert not (base_dir / "token_token_delete.json").exists()
        assert not (base_dir / "run_delete.json").exists()

    def test_delete_request_reports_token_deletion_when_run_record_is_missing(self, tmp_path: Path):
        base_dir = tmp_path / "approvals_token_only_delete"
        store = FileApprovalStore(base_dir=base_dir)
        request = ApprovalRequest(
            approval_token="token_only_delete",
            run_id="run_only_delete",
            turn_index=1,
            outbound_payload_hash="hash_only_delete",
        )
        store.create_request(request)
        (base_dir / "run_only_delete.json").unlink()

        assert store.delete_request(request.approval_token) is True
        assert not (base_dir / "token_token_only_delete.json").exists()

    def test_rejected_request_uses_rejected_default_audit_reason(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals_reason")
        request = ApprovalRequest(
            approval_token="token_file_reject",
            run_id="run_file_reject",
            turn_index=1,
            outbound_payload_hash="hash_file_reject",
        )
        store.create_request(request)

        resolved = store.resolve_request(request.approval_token, "REJECTED")

        assert resolved.decision_reason == "Rejected via review gate"

    def test_approved_request_uses_approved_default_audit_reason(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals_approved_reason")
        request = ApprovalRequest(
            approval_token="token_file_approve",
            run_id="run_file_approve",
            turn_index=1,
            outbound_payload_hash="hash_file_approve",
        )
        store.create_request(request)

        resolved = store.resolve_request(request.approval_token, "APPROVED")

        assert resolved.decision_reason == "Approved via review gate"


class TestSQLiteApprovalStore:
    def test_lifecycle(self, tmp_path: Path):
        db_path = tmp_path / "approvals.db"
        store = SQLiteApprovalStore(db_path=db_path)

        req = ApprovalRequest(
            approval_token="token_sql_01",
            run_id="run_sql_01",
            turn_index=3,
            outbound_payload_hash="hash_sql_01",
            required_role="physician",
            reviewer_credentials={"npi": "1234567890"},
        )

        # Create
        created = store.create_request(req)
        assert created.approval_token == "token_sql_01"

        # Lookup by token
        loaded = store.get_request("token_sql_01")
        assert loaded is not None
        assert loaded.run_id == "run_sql_01"
        assert loaded.required_role == "physician"
        assert loaded.reviewer_credentials == {"npi": "1234567890"}

        # Lookup by run_id
        loaded_by_run = store.get_request_by_run_id("run_sql_01")
        assert loaded_by_run is not None
        assert loaded_by_run.approval_token == "token_sql_01"

        # List pending
        pending = store.list_pending()
        assert len(pending) == 1
        assert pending[0].approval_token == "token_sql_01"

        pending_for_run = store.list_pending(run_id="run_sql_01")
        assert len(pending_for_run) == 1

        pending_other = store.list_pending(run_id="run_other_sql")
        assert len(pending_other) == 0

        # Resolve REJECTED
        resolved = store.resolve_request(
            approval_token="token_sql_01",
            decision="REJECTED",
            decided_by="dr_smith",
            decision_reason="Insufficient patient clinical notes",
        )
        assert resolved.status == "REJECTED"
        assert resolved.decision == "REJECTED"
        assert resolved.decided_by == "dr_smith"
        assert resolved.decision_reason == "Insufficient patient clinical notes"

        # Verify list_pending now empty
        assert len(store.list_pending()) == 0

        # Delete
        deleted = store.delete_request("token_sql_01")
        assert deleted is True
        assert store.get_request("token_sql_01") is None

    def test_empty_keys_and_edge_cases(self, tmp_path: Path):
        db_path = tmp_path / "approvals.db"
        store = SQLiteApprovalStore(db_path=db_path)
        assert store.get_request("") is None
        assert store.get_request_by_run_id("") is None
        assert store.delete_request("") is False
        assert store.delete_request("non_existent_token") is False

    def test_rejected_request_uses_rejected_default_audit_reason(self, tmp_path: Path):
        store = SQLiteApprovalStore(db_path=tmp_path / "approval_reason.db")
        request = ApprovalRequest(
            approval_token="token_sql_reject",
            run_id="run_sql_reject",
            turn_index=1,
            outbound_payload_hash="hash_sql_reject",
        )
        store.create_request(request)

        resolved = store.resolve_request(request.approval_token, "REJECTED")

        assert resolved.decision_reason == "Rejected via review gate"

    def test_approved_request_uses_approved_default_audit_reason(self, tmp_path: Path):
        store = SQLiteApprovalStore(db_path=tmp_path / "approval_approved_reason.db")
        request = ApprovalRequest(
            approval_token="token_sql_approve",
            run_id="run_sql_approve",
            turn_index=1,
            outbound_payload_hash="hash_sql_approve",
        )
        store.create_request(request)

        resolved = store.resolve_request(request.approval_token, "APPROVED")

        assert resolved.decision_reason == "Approved via review gate"

    def test_env_var_and_default_init(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        custom_db = tmp_path / "custom_env_approvals.db"
        monkeypatch.setenv("AGENTV_APPROVALS_DB", str(custom_db))
        store = SQLiteApprovalStore()
        assert store.db_path == custom_db.resolve()

        monkeypatch.delenv("AGENTV_APPROVALS_DB", raising=False)
        store_default = SQLiteApprovalStore()
        assert ".agentv" in str(store_default.db_path)

    def test_errors(self, tmp_path: Path):
        db_path = tmp_path / "approvals.db"
        store = SQLiteApprovalStore(db_path=db_path)

        with pytest.raises(KeyError, match="not found"):
            store.resolve_request("unknown_tok", "APPROVED")

        req = ApprovalRequest(
            approval_token="tok_sql_err",
            run_id="run_sql_err",
            turn_index=1,
            outbound_payload_hash="h1",
        )
        store.create_request(req)

        with pytest.raises(ValueError, match="Invalid approval decision"):
            store.resolve_request("tok_sql_err", "UNKNOWN_DECISION")

        # Test defensive branch where get_request returns None after update
        with patch.object(store, "get_request", return_value=None):
            with pytest.raises(KeyError, match="not found after update"):
                store.resolve_request("tok_sql_err", "APPROVED")

    def test_db_init_oserror_handling(self, tmp_path: Path):
        with patch.object(Path, "mkdir", side_effect=OSError("Database dir error")):
            with pytest.raises(OSError, match="Database dir error"):
                SQLiteApprovalStore(db_path=tmp_path / "db_err" / "store.db")


class TestApprovalStoreFactory:
    def test_factory_variants(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        reset_default_approval_store()

        # 1. Base dir sqlite override
        s1 = get_default_approval_store(store_type="sqlite", base_dir=tmp_path / "test.db")
        assert isinstance(s1, SQLiteApprovalStore)

        # 2. Base dir file override
        s2 = get_default_approval_store(store_type="file", base_dir=tmp_path / "test_dir")
        assert isinstance(s2, FileApprovalStore)

        # 3. Environment variable configured
        reset_default_approval_store()
        monkeypatch.setenv("AGENTV_APPROVAL_STORE", "sqlite")
        monkeypatch.setenv("AGENTV_APPROVALS_DB", str(tmp_path / "env.db"))
        s3 = get_default_approval_store()
        assert isinstance(s3, SQLiteApprovalStore)

        # 4. Default fallback to FileApprovalStore
        reset_default_approval_store()
        monkeypatch.setenv("AGENTV_APPROVAL_STORE", "file")
        monkeypatch.setenv("AGENTV_APPROVALS_DIR", str(tmp_path / "env_dir"))
        s4 = get_default_approval_store()
        assert isinstance(s4, FileApprovalStore)

        reset_default_approval_store()


class TestSessionApprovalManagerDurable:
    def test_durable_request_creation_and_resolution(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")
        mock_checkpoint_mgr = MagicMock()
        mock_checkpoint_mgr.create_checkpoint.return_value = "chk_mock_001"
        run_store = LocalFileRunStore(tmp_path / "runs")
        run_store.create_run("run_session_01", "scen_1")

        mgr = SessionApprovalManager(
            run_id="run_session_01",
            checkpoint_manager=mock_checkpoint_mgr,
            state_provider=lambda: {"scenario_data": {"id": "scen_1"}, "state": "test"},
            approval_store=store,
            run_store=run_store,
        )

        durable_req = mgr.create_durable_request(
            turn_index=2,
            action_payload={"tool": "prescribe_medication", "dose": "10mg"},
            required_role="licensed_pharmacist",
        )

        assert durable_req.approval_token is not None
        assert durable_req.run_id == "run_session_01"
        assert durable_req.turn_index == 2
        assert durable_req.checkpoint_id == "chk_mock_001"
        assert durable_req.status == "PENDING"
        assert durable_req.outbound_payload_hash != ""

        # Check that checkpoint_manager was called with PAUSED_FOR_APPROVAL
        mock_checkpoint_mgr.create_checkpoint.assert_called_once()
        call_args = mock_checkpoint_mgr.create_checkpoint.call_args
        assert call_args[0][0]["status"] == "PAUSED_FOR_APPROVAL"
        assert call_args[0][0]["approval_token"] == durable_req.approval_token

        # Check retrieval via mgr
        retrieved = mgr.get_durable_request(durable_req.approval_token)
        assert retrieved is not None
        assert retrieved.approval_token == durable_req.approval_token

        # Check pending list
        pending = mgr.list_durable_pending()
        assert len(pending) == 1

        # Resolve
        resolved = mgr.resolve_durable_request(
            approval_token=durable_req.approval_token,
            decision="APPROVED",
            decided_by="pharmacist_dave",
        )
        assert resolved.status == "APPROVED"
        assert len(mgr.list_durable_pending()) == 0

    def test_default_approval_store_property(self):
        mgr = SessionApprovalManager(run_id="run_default_store")
        assert mgr.approval_store is not None

    def test_state_provider_exception_resilience(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")
        mock_chk = MagicMock()
        run_store = LocalFileRunStore(tmp_path / "runs")
        run_store.create_run("run_failing_state", "scen_1")

        def failing_state():
            raise RuntimeError("Corrupted state")

        mgr = SessionApprovalManager(
            run_id="run_failing_state",
            checkpoint_manager=mock_chk,
            state_provider=failing_state,
            approval_store=store,
            run_store=run_store,
        )

        req = mgr.create_durable_request(turn_index=1, action_payload={"step": 1})
        assert req is not None
        mock_chk.create_checkpoint.assert_called_once()


class TestSessionApprovalManagerLegacyAndGates:
    def test_request_and_resolve_approval(self, tmp_path):
        unique_run_id = "run_isolated_leg_01"
        mock_checkpoint_mgr = MagicMock()
        mock_checkpoint_mgr.create_checkpoint.return_value = "chk_leg_01"
        store = FileApprovalStore(tmp_path / "approvals")
        run_store = LocalFileRunStore(tmp_path / "runs")
        context = {"tenant_id": "test", "workspace_id": "test", "active_environment": "test"}
        run_store.create_run(unique_run_id, "scenario", context=context)

        mgr = SessionApprovalManager(
            run_id=unique_run_id,
            approval_store=store,
            run_store=run_store,
            checkpoint_manager=mock_checkpoint_mgr,
            state_provider=lambda: {"counter": 42},
        )

        pending = mgr.create_durable_request(
            turn_index=1,
            metadata={"task_id": "task_audit", "runtime_context": context},
            action_payload={"user": "bob"},
            prompt="grant_access",
        )
        assert pending.run_id == unique_run_id
        assert pending.metadata["task_id"] == "task_audit"
        mock_checkpoint_mgr.create_checkpoint.assert_called_once()

        # List pending
        p_list = store.list_pending(run_id=unique_run_id)
        assert len(p_list) == 1
        assert p_list[0].metadata["task_id"] == "task_audit"

        # Resolve
        approved = mgr.resolve_durable_request(
            pending.approval_token,
            "APPROVED",
            decided_by="admin",
            decision_reason="Access granted",
        )
        assert approved.status == "APPROVED"

    def test_request_approval_state_provider_exception(self, tmp_path):
        mock_checkpoint_mgr = MagicMock()

        def bad_state():
            raise RuntimeError("State capture failed")

        mgr = SessionApprovalManager(
            run_id="run_bad_state",
            checkpoint_manager=mock_checkpoint_mgr,
            state_provider=bad_state,
            approval_store=FileApprovalStore(tmp_path / "approvals"),
            run_store=LocalFileRunStore(tmp_path / "runs"),
        )
        mgr.run_store.create_run("run_bad_state", "scenario")
        pending = mgr.create_durable_request(turn_index=1, metadata={"task_id": "t_err"})
        assert pending is not None
        mock_checkpoint_mgr.create_checkpoint.assert_called_once()

    def test_plugin_interceptor_rejection(self, tmp_path):
        mock_plugin_mgr = MagicMock()
        mock_plugin_mgr.trigger_interceptor.return_value = False
        mock_plugin_mgr.last_rejection_reason = "Forbidden tool call"

        mgr = SessionApprovalManager(
            run_id="run_intercept_01",
            plugin_manager=mock_plugin_mgr,
            approval_store=FileApprovalStore(tmp_path / "approvals"),
            run_store=LocalFileRunStore(tmp_path / "runs"),
        )
        mgr.run_store.create_run("run_intercept_01", "scenario")

        with pytest.raises(PermissionError, match="Forbidden tool call"):
            mgr.create_durable_request(1, metadata={"task_id": "t1"})

        # Dictionary rejection format
        mock_plugin_mgr.trigger_interceptor.return_value = {
            "allowed": False,
            "error": "Blocked by security rule",
        }
        mock_plugin_mgr.last_rejection_reason = None
        with pytest.raises(PermissionError, match="Blocked by security rule"):
            mgr.create_durable_request(1, metadata={"task_id": "t2"})

    def test_durable_approval_uses_interceptor_before_persistence(self):
        plugin_manager = MagicMock()
        plugin_manager.trigger_interceptor.return_value = {
            "allowed": False,
            "error": "Approval token revoked",
        }
        manager = SessionApprovalManager(
            run_id="run_durable_intercept",
            plugin_manager=plugin_manager,
            approval_store=MagicMock(),
        )

        with pytest.raises(PermissionError, match="Approval token revoked"):
            manager.create_durable_request(
                turn_index=1,
                metadata={"task_id": "approval_gate"},
            )

        plugin_manager.trigger_interceptor.assert_called_once()
        assert plugin_manager.trigger_interceptor.call_args.args[0] == "on_approval_request"
        manager.approval_store.create_request.assert_not_called()

    def test_durable_approval_resolution_uses_interceptor_before_persistence(self):
        store = MagicMock()
        store.get_request.return_value = MagicMock(
            metadata={"task_id": "approval_gate"},
            required_role="reviewer",
            action_payload={"action": "release"},
        )
        plugin_manager = MagicMock()
        plugin_manager.trigger_interceptor.return_value = {
            "allowed": False,
            "error": "Approval token revoked",
        }
        manager = SessionApprovalManager(
            run_id="run_durable_resolution_intercept",
            plugin_manager=plugin_manager,
            approval_store=store,
        )

        with pytest.raises(PermissionError, match="Approval token revoked"):
            manager.resolve_durable_request("approval-token", "APPROVED")

        assert plugin_manager.trigger_interceptor.call_args.args[0] == "on_approval_resolution"
        assert plugin_manager.trigger_interceptor.call_args.args[2]["phase"] == "resolution"
        store.resolve_request.assert_not_called()


class TestInProcessBackendResumptionGuard:
    def test_resume_accepts_paused_for_approval(self):
        run_store = MagicMock()
        backend = InProcessExecutionBackend(run_store=run_store)
        run_id = "run_paused_hitl_01"
        approved = ApprovalRequest(
            approval_token="tok_test_resume",
            run_id=run_id,
            turn_index=1,
            outbound_payload_hash="",
            status="APPROVED",
        )

        # 1. Active run in PAUSED_FOR_APPROVAL transitions to RUNNING
        with backend._lock:
            backend._active_runs[run_id] = {
                "status": "PAUSED_FOR_APPROVAL",
                "scenario_data": {"id": "test_scenario", "metadata": {"name": "Test"}},
                "resumption_checkpoint": {"session_state": {"approval_token": "tok_test_resume"}},
            }

        approval_store = MagicMock()
        approval_store.get_request.side_effect = lambda token: (
            approved
            if token == "tok_test_resume"
            else ApprovalRequest(
                approval_token=token,
                run_id="run_cold_restart",
                turn_index=1,
                outbound_payload_hash="",
                status="APPROVED",
            )
        )
        with (
            patch(
                "eval_runner.reference.approval_store.get_default_approval_store",
                return_value=approval_store,
            ),
            patch("eval_runner.reference.inprocess_backend.transition_run_lifecycle") as reopen,
            patch.object(
                backend, "submit", return_value={"status": "resumed_from_checkpoint"}
            ) as submit,
        ):
            res = backend.resume(run_id=run_id, resumption_token="tok_test_resume")
        assert res == {"status": "resumed_from_checkpoint"}
        assert submit.call_args.kwargs["resumption_token"] == "tok_test_resume"
        reopen.assert_called_once_with(
            run_id, RunLifecycleState.OPEN, run_store=run_store, context=None
        )

        # 2. Resuming with checkpoint invokes submit
        mock_checkpoint_store = MagicMock()
        mock_checkpoint_store.load.return_value = {
            "status": "PAUSED_FOR_APPROVAL",
            "scenario_data": {"id": "scen_chk", "metadata": {"name": "Test Checkpoint"}},
            "session_state": {"approval_token": "tok_chk_123"},
        }
        backend_chk = InProcessExecutionBackend(
            checkpoint_store=mock_checkpoint_store, run_store=run_store
        )
        with (
            patch(
                "eval_runner.reference.approval_store.get_default_approval_store",
                return_value=approval_store,
            ),
            patch(
                "eval_runner.reference.inprocess_backend.transition_run_lifecycle"
            ) as reopen_checkpoint,
        ):
            with patch.object(backend_chk, "submit") as mock_submit:
                mock_submit.return_value = {"status": "resumed_from_checkpoint"}
                res_chk = backend_chk.resume(
                    run_id="run_cold_restart", resumption_token="tok_chk_123"
                )
                assert res_chk == {"status": "resumed_from_checkpoint"}
                mock_submit.assert_called_once()
                assert mock_submit.call_args[1]["resumption_token"] == "tok_chk_123"
                reopen_checkpoint.assert_called_once_with(
                    "run_cold_restart", RunLifecycleState.OPEN, run_store=run_store, context=None
                )


@pytest.mark.asyncio
class TestHitlResumeCliHandler:
    async def test_hitl_resume_validation_errors(self):
        # Missing run_id
        args = argparse.Namespace(run_id=None, approval_token="tok", decision="APPROVED")
        assert await handle_hitl_resume(args) == 1

        # Missing approval_token
        args = argparse.Namespace(run_id="run_1", approval_token=None, decision="APPROVED")
        assert await handle_hitl_resume(args) == 1

        # Invalid decision
        args = argparse.Namespace(run_id="run_1", approval_token="tok", decision="INVALID")
        assert await handle_hitl_resume(args) == 1

    async def test_hitl_resume_request_not_found(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")
        with patch(
            "eval_runner.reference.approval_store.get_default_approval_store",
            return_value=store,
        ):
            args = argparse.Namespace(
                run_id="run_1",
                approval_token="tok_missing",
                decision="APPROVED",
                reviewer="tester",
                reason=None,
                store=None,
            )
            assert await handle_hitl_resume(args) == 1

    async def test_hitl_resume_run_id_mismatch(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")
        store.create_request(
            ApprovalRequest(
                approval_token="tok_match_fail",
                run_id="run_original",
                turn_index=1,
                outbound_payload_hash="h1",
            )
        )
        with patch(
            "eval_runner.reference.approval_store.get_default_approval_store",
            return_value=store,
        ):
            args = argparse.Namespace(
                run_id="run_different",
                approval_token="tok_match_fail",
                decision="APPROVED",
                reviewer="tester",
                reason=None,
                store=None,
            )
            assert await handle_hitl_resume(args) == 1

    async def test_hitl_resume_rejected(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")
        store.create_request(
            ApprovalRequest(
                approval_token="tok_rej",
                run_id="run_rej",
                turn_index=1,
                outbound_payload_hash="h_rej",
            )
        )
        with patch(
            "eval_runner.reference.approval_store.get_default_approval_store",
            return_value=store,
        ):
            args = argparse.Namespace(
                run_id="run_rej",
                approval_token="tok_rej",
                decision="REJECTED",
                reviewer="dr_bob",
                reason="Denied due to clinical contraindication",
                store=None,
            )
            code = await handle_hitl_resume(args)
            assert code == 0

            # Verify persisted state is REJECTED
            req = store.get_request("tok_rej")
            assert req is not None
            assert req.status == "REJECTED"
            assert req.decided_by == "dr_bob"
            assert req.decision_reason == "Denied due to clinical contraindication"

    async def test_hitl_resume_already_resolved(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")
        req = ApprovalRequest(
            approval_token="tok_done",
            run_id="run_done",
            turn_index=1,
            outbound_payload_hash="h1",
            status="REJECTED",
            decided_by="admin",
        )
        store.create_request(req)

        with patch(
            "eval_runner.reference.approval_store.get_default_approval_store",
            return_value=store,
        ):
            args = argparse.Namespace(
                run_id="run_done",
                approval_token="tok_done",
                decision="REJECTED",
                reviewer="admin",
                reason=None,
                store=None,
            )
            assert await handle_hitl_resume(args) == 0

    async def test_hitl_resume_already_approved_skips_resolution_hooks(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")
        store.create_request(
            ApprovalRequest(
                approval_token="tok_already_approved",
                run_id="run_already_approved",
                turn_index=1,
                outbound_payload_hash="h_approved",
                status="APPROVED",
                decided_by="system-administrator",
            )
        )
        backend = MagicMock()

        with (
            patch(
                "eval_runner.reference.approval_store.get_default_approval_store",
                return_value=store,
            ),
            patch(
                "eval_runner.session_components.approval_manager.SessionApprovalManager",
                side_effect=AssertionError("resolution hooks must not be replayed"),
            ),
            patch("eval_runner.runtime_services.resolve_execution_backend", return_value=backend),
        ):
            args = argparse.Namespace(
                run_id="run_already_approved",
                approval_token="tok_already_approved",
                decision="APPROVED",
                reviewer="cli_reviewer",
                reason=None,
                store=None,
            )
            assert await handle_hitl_resume(args) == 0

        backend.resume.assert_called_once_with(
            run_id="run_already_approved",
            resumption_token="tok_already_approved",
            background=False,
        )

    async def test_hitl_resume_store_overrides(self, tmp_path: Path):
        db_path = tmp_path / "override.db"
        sql_store = SQLiteApprovalStore(db_path=db_path)
        sql_store.create_request(
            ApprovalRequest(
                approval_token="tok_sql_override",
                run_id="run_sql_override",
                turn_index=1,
                outbound_payload_hash="h1",
            )
        )

        file_dir = tmp_path / "override_file"
        file_store = FileApprovalStore(base_dir=file_dir)
        file_store.create_request(
            ApprovalRequest(
                approval_token="tok_file_override",
                run_id="run_file_override",
                turn_index=1,
                outbound_payload_hash="h1",
            )
        )

        with (
            patch(
                "eval_runner.reference.approval_store.SQLiteApprovalStore", return_value=sql_store
            ),
            patch(
                "eval_runner.reference.approval_store.FileApprovalStore", return_value=file_store
            ),
        ):
            # Sqlite override
            args_sql = argparse.Namespace(
                run_id="run_sql_override",
                approval_token="tok_sql_override",
                decision="REJECTED",
                reviewer="dr_sql",
                reason="Sqlite rejected",
                store="sqlite",
            )
            assert await handle_hitl_resume(args_sql) == 0

            # File override
            args_file = argparse.Namespace(
                run_id="run_file_override",
                approval_token="tok_file_override",
                decision="REJECTED",
                reviewer="dr_file",
                reason="File rejected",
                store="file",
            )
            assert await handle_hitl_resume(args_file) == 0

    async def test_hitl_resume_approved_and_resumed(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")
        store.create_request(
            ApprovalRequest(
                approval_token="tok_appr",
                run_id="run_appr",
                turn_index=1,
                outbound_payload_hash="h_appr",
            )
        )

        mock_backend = MagicMock()
        mock_backend.resume.return_value = {"status": "SUCCESS"}

        with (
            patch(
                "eval_runner.reference.approval_store.get_default_approval_store",
                return_value=store,
            ),
            patch(
                "eval_runner.runtime_services.resolve_execution_backend",
                return_value=mock_backend,
            ),
        ):
            args = argparse.Namespace(
                run_id="run_appr",
                approval_token="tok_appr",
                decision="APPROVED",
                reviewer="dr_alice",
                reason="Approved following clinical chart audit",
                store=None,
            )
            code = await handle_hitl_resume(args)
            assert code == 0

            # Verify backend.resume called with run_id and approval token
            mock_backend.resume.assert_called_once_with(
                run_id="run_appr",
                resumption_token="tok_appr",
                background=False,
            )

            # Verify store record resolved
            req = store.get_request("tok_appr")
            assert req is not None
            assert req.status == "APPROVED"
            assert req.decided_by == "dr_alice"

    async def test_hitl_resume_exception_during_execution(self, tmp_path: Path):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")
        store.create_request(
            ApprovalRequest(
                approval_token="tok_err",
                run_id="run_err",
                turn_index=1,
                outbound_payload_hash="h1",
            )
        )
        mock_backend = MagicMock()
        mock_backend.resume.side_effect = RuntimeError("Crash on resume")

        with (
            patch(
                "eval_runner.reference.approval_store.get_default_approval_store",
                return_value=store,
            ),
            patch(
                "eval_runner.reference.inprocess_backend.get_execution_backend",
                return_value=mock_backend,
            ),
        ):
            args = argparse.Namespace(
                run_id="run_err",
                approval_token="tok_err",
                decision="APPROVED",
                reviewer="tester",
                reason=None,
                store=None,
            )
            assert await handle_hitl_resume(args) == 1
