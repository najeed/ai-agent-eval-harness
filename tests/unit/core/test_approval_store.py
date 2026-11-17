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


@pytest.mark.parametrize("kind", ["file", "sqlite"])
@pytest.mark.parametrize(
    "violation,code",
    [
        ("pending", "ApprovalNotGranted"),
        ("revoked", "ApprovalNotGranted"),
        ("expired", "ApprovalExpired"),
        ("invalid_expiry", "ApprovalExpiryInvalid"),
        ("nonfinite_expiry", "ApprovalExpiryInvalid"),
        ("wrong_run", "ApprovalRunMismatch"),
        ("wrong_payload", "ApprovalPayloadMismatch"),
        ("empty_payload", "ApprovalPayloadMismatch"),
        ("spent", "ApprovalReplayBlocked"),
    ],
)
def test_approval_consumption_validates_every_authorization_binding(
    tmp_path, kind, violation, code
):
    from eval_runner.approval_validation import ApprovalValidationError
    from eval_runner.mutation_evidence import evidence_hash

    store = (
        FileApprovalStore(tmp_path / "approvals")
        if kind == "file"
        else SQLiteApprovalStore(tmp_path / "approvals.db")
    )
    metadata = {"expires_at": 9999999999}
    if violation == "expired":
        metadata["expires_at"] = 0
    elif violation == "invalid_expiry":
        metadata["expires_at"] = "tomorrow"
    elif violation == "nonfinite_expiry":
        metadata["expires_at"] = float("inf")
    elif violation == "revoked":
        metadata["revocation"] = {"revoked_by": "reviewer"}
    elif violation == "spent":
        metadata["consumption"] = {"authorization_id": "previous-authorization"}
    payload_hash = evidence_hash({"amount": 100})
    request = ApprovalRequest(
        approval_token="authorize",
        run_id="run-authorize",
        outbound_payload_hash="" if violation == "empty_payload" else payload_hash,
        status="PENDING" if violation == "pending" else "APPROVED",
        metadata=metadata,
    )
    store.create_request(request)
    with pytest.raises(ApprovalValidationError) as error:
        store.consume_request(
            "authorize",
            run_id="other-run" if violation == "wrong_run" else request.run_id,
            payload_hash=evidence_hash({"amount": 200})
            if violation == "wrong_payload"
            else payload_hash,
        )
    assert error.value.code == code
    assert store.get_request("authorize").metadata == metadata


@pytest.mark.parametrize("kind", ["file", "sqlite"])
def test_approval_consumption_success_and_replay(tmp_path, kind):
    from eval_runner.approval_validation import ApprovalValidationError
    from eval_runner.mutation_evidence import evidence_hash

    store = (
        FileApprovalStore(tmp_path / "approvals")
        if kind == "file"
        else SQLiteApprovalStore(tmp_path / "approvals.db")
    )
    payload_hash = evidence_hash({"amount": 500})
    req = ApprovalRequest(
        approval_token="tok_valid",
        run_id="run_valid",
        outbound_payload_hash=payload_hash,
        status="APPROVED",
        metadata={"expires_at": 9999999999},
    )
    store.create_request(req)
    consumed = store.consume_request("tok_valid", run_id="run_valid", payload_hash=payload_hash)
    assert consumed.approval_token == "tok_valid"
    assert "consumption" in consumed.metadata
    assert consumed.metadata["consumption"]["run_id"] == "run_valid"
    assert consumed.metadata["consumption"]["payload_hash"] == payload_hash

    persisted = store.get_request("tok_valid")
    assert persisted.metadata["consumption"] == consumed.metadata["consumption"]

    # Replay attempt fails closed
    with pytest.raises(ApprovalValidationError) as err:
        store.consume_request("tok_valid", run_id="run_valid", payload_hash=payload_hash)
    assert err.value.code == "ApprovalReplayBlocked"


@pytest.mark.parametrize("kind", ["file", "sqlite"])
def test_approval_consumption_missing_and_scope_mismatch(tmp_path, kind):
    from agentv_runtime.interfaces import ScopeMismatchError
    from agentv_runtime.scope import ScopeToken
    from eval_runner.mutation_evidence import evidence_hash

    store = (
        FileApprovalStore(tmp_path / "approvals")
        if kind == "file"
        else SQLiteApprovalStore(tmp_path / "approvals.db")
    )
    with pytest.raises(KeyError, match="nonexistent_token"):
        store.consume_request("nonexistent_token", run_id="run_1", payload_hash="hash")

    payload_hash = evidence_hash({"amount": 10})
    req = ApprovalRequest(
        approval_token="tok_scoped",
        run_id="run_scoped",
        outbound_payload_hash=payload_hash,
        status="APPROVED",
        metadata={"expires_at": 9999999999},
        scope={"tenant": "tenant_a"},
        scope_digest="sha3_256:scope_a",
    )
    store.create_request(req)
    with pytest.raises(ScopeMismatchError, match="Scope mismatch consuming authorization"):
        store.consume_request(
            "tok_scoped",
            run_id="run_scoped",
            payload_hash=payload_hash,
            scope=ScopeToken.from_tags({"tenant": "tenant_b"}),
        )


def test_file_approval_store_consume_degraded_record(tmp_path):
    from agentv_runtime.interfaces import ApprovalStorageDegradedError

    store = FileApprovalStore(tmp_path / "approvals")
    store.base_dir.mkdir(parents=True, exist_ok=True)
    corrupt_token_file = store.base_dir / "token_corrupt_tok.json"
    corrupt_token_file.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ApprovalStorageDegradedError, match="Cannot verify authorization record"):
        store.consume_request("corrupt_tok", run_id="run_1", payload_hash="hash")


@pytest.mark.parametrize("kind", ["file", "sqlite"])
def test_expiry_guard_is_shared_by_decision_and_action_consumption(tmp_path, kind):
    from eval_runner.approval_validation import ApprovalValidationError

    store = (
        FileApprovalStore(tmp_path / "approvals")
        if kind == "file"
        else SQLiteApprovalStore(tmp_path / "approvals.db")
    )
    store.create_request(
        ApprovalRequest(approval_token="expired", run_id="expired-run", metadata={"expires_at": 0})
    )
    with pytest.raises(ApprovalValidationError, match="ApprovalExpired"):
        store.resolve_request("expired", "APPROVED")
    assert store.get_request("expired").status == "PENDING"
    assert store.resolve_request("expired", "REJECTED").status == "REJECTED"


def test_approval_expiry_rejects_exact_deadline(monkeypatch):
    from eval_runner.approval_validation import ApprovalValidationError, validate_expiry

    monkeypatch.setattr("eval_runner.approval_validation.time.time", lambda: 100)
    with pytest.raises(ApprovalValidationError, match="ApprovalExpired"):
        validate_expiry(
            ApprovalRequest(
                approval_token="boundary", run_id="boundary-run", metadata={"expires_at": 100}
            )
        )
    validate_expiry(
        ApprovalRequest(
            approval_token="future", run_id="boundary-run", metadata={"expires_at": 101}
        )
    )
    validate_expiry(ApprovalRequest(approval_token="unbounded", run_id="boundary-run"))


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
        import hashlib

        from agentv_runtime.canonical import canonical_json_encode

        run_store = MagicMock()
        run_store.get_lifecycle.return_value = "PAUSED_FOR_APPROVAL"
        backend = InProcessExecutionBackend(run_store=run_store)
        run_id = "run_paused_hitl_01"
        empty_payload_hash = "sha3_256:" + hashlib.sha3_256(canonical_json_encode({})).hexdigest()
        approved = ApprovalRequest(
            approval_token="tok_test_resume",
            run_id=run_id,
            turn_index=1,
            outbound_payload_hash=empty_payload_hash,
            status="APPROVED",
        )

        # 1. Active run in PAUSED_FOR_APPROVAL transitions to RUNNING
        with backend._lock:
            backend._active_runs[run_id] = {
                "status": "PAUSED_FOR_APPROVAL",
                "scenario_data": {"id": "test_scenario", "metadata": {"name": "Test"}},
                "resumption_checkpoint": {
                    "session_state": {
                        "approval_token": "tok_test_resume",
                        "action_payload": {},
                    }
                },
            }

        approval_store = MagicMock()
        approval_store.get_request.side_effect = lambda token: (
            approved
            if token == "tok_test_resume"
            else ApprovalRequest(
                approval_token=token,
                run_id="run_cold_restart",
                turn_index=1,
                outbound_payload_hash=empty_payload_hash,
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
            "session_state": {
                "approval_token": "tok_chk_123",
                "action_payload": {},
            },
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

    def test_resume_rejects_payload_digest_mismatch_even_for_empty_payload(self):
        import hashlib

        run_store = MagicMock()
        run_store.get_lifecycle.return_value = "PAUSED_FOR_APPROVAL"
        backend = InProcessExecutionBackend(run_store=run_store)
        run_id = "run_payload_tamper"
        # Approved record expects payload hash for {"action": "approved_val"}
        expected_hash = hashlib.sha3_256(
            str(sorted({"action": "approved_val"}.items())).encode()
        ).hexdigest()
        approved = ApprovalRequest(
            approval_token="tok_payload_check",
            run_id=run_id,
            turn_index=1,
            outbound_payload_hash=expected_hash,
            status="APPROVED",
        )
        # Checkpoint contains empty payload {} (or tampered payload)
        with backend._lock:
            backend._active_runs[run_id] = {
                "status": "PAUSED_FOR_APPROVAL",
                "scenario_data": {"id": "test_scenario"},
                "resumption_checkpoint": {
                    "session_state": {
                        "approval_token": "tok_payload_check",
                        "action_payload": {},  # empty payload must not bypass verification!
                    }
                },
            }
        approval_store = MagicMock()
        approval_store.get_request.return_value = approved
        with patch(
            "eval_runner.reference.approval_store.get_default_approval_store",
            return_value=approval_store,
        ):
            with pytest.raises(PermissionError, match="approval payload binding is invalid"):
                backend.resume(run_id=run_id, resumption_token="tok_payload_check")

    def test_resume_rejects_checkpoint_manifest_and_scope_mismatch(self):
        import hashlib

        run_store = MagicMock()
        run_store.get_lifecycle.return_value = "PAUSED_FOR_APPROVAL"
        backend = InProcessExecutionBackend(run_store=run_store)
        run_id = "run_scope_tamper"
        approved = ApprovalRequest(
            approval_token="tok_scope_check",
            run_id=run_id,
            turn_index=1,
            outbound_payload_hash=hashlib.sha3_256(b"{}").hexdigest(),
            manifest_id="manifest_orig",
            scope_digest="sha3:scope_orig",
            status="APPROVED",
        )
        # 1. Manifest mismatch
        with backend._lock:
            backend._active_runs[run_id] = {
                "status": "PAUSED_FOR_APPROVAL",
                "scenario_data": {"id": "test_scenario"},
                "resumption_checkpoint": {
                    "session_state": {
                        "approval_token": "tok_scope_check",
                        "action_payload": {},
                        "manifest_id": "manifest_tampered",
                        "scope_digest": "sha3:scope_orig",
                    }
                },
            }
        approval_store = MagicMock()
        approval_store.get_request.return_value = approved
        with patch(
            "eval_runner.reference.approval_store.get_default_approval_store",
            return_value=approval_store,
        ):
            with pytest.raises(PermissionError, match="approval manifest binding mismatch"):
                backend.resume(run_id=run_id, resumption_token="tok_scope_check")

        # 2. Scope digest mismatch
        with backend._lock:
            backend._active_runs[run_id]["resumption_checkpoint"]["session_state"][
                "manifest_id"
            ] = "manifest_orig"
            backend._active_runs[run_id]["resumption_checkpoint"]["session_state"][
                "scope_digest"
            ] = "sha3:scope_tampered"
        with patch(
            "eval_runner.reference.approval_store.get_default_approval_store",
            return_value=approval_store,
        ):
            with pytest.raises(PermissionError, match="approval scope binding mismatch"):
                backend.resume(run_id=run_id, resumption_token="tok_scope_check")

    def test_resume_enforces_authoritative_provider_approval_gating(self):
        # Provider lifecycle is PAUSED_FOR_APPROVAL, even if checkpoint status claims "PAUSED"
        run_store = MagicMock()
        run_store.get_lifecycle.return_value = "PAUSED_FOR_APPROVAL"
        mock_checkpoint_store = MagicMock()
        mock_checkpoint_store.load.return_value = {
            "status": "PAUSED",  # Crafty checkpoint claims ordinary non-HITL PAUSED
            "session_state": {"status": "PAUSED"},
        }
        backend = InProcessExecutionBackend(
            checkpoint_store=mock_checkpoint_store, run_store=run_store
        )
        run_id = "run_auth_provider_gate"

        # Must reject resumption without token because provider lifecycle
        # is authoritatively PAUSED_FOR_APPROVAL
        with pytest.raises(PermissionError, match="approval-gated checkpoint requires a token"):
            backend.resume(run_id=run_id, resumption_token=None)


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


def test_get_request_skips_orphan_token_files_during_fallback(tmp_path: Path):
    import json

    store = FileApprovalStore(base_dir=tmp_path)
    # Fast path looks for token_target_tok.json, which does not exist.
    # Write a token file that has approval_token 'target_tok', but named 'token_other.json'
    orphan = tmp_path / "token_other.json"
    orphan.write_text(
        json.dumps(
            {
                "approval_token": "target_tok",
                "run_id": "orphan_run",
                "turn_index": 1,
                "status": "PENDING",
                "prompt": "Orphan action",
            }
        )
    )
    # Fallback scan must skip token_other.json because it starts with token_!
    assert store.get_request("target_tok") is None


@pytest.mark.parametrize("store_cls", [FileApprovalStore, SQLiteApprovalStore])
def test_system_scope_can_resolve_legacy_unscoped_request(tmp_path: Path, store_cls):
    from agentv_runtime.scope import ScopeToken

    store = (
        FileApprovalStore(base_dir=tmp_path / "file_store")
        if store_cls is FileApprovalStore
        else SQLiteApprovalStore(db_path=str(tmp_path / "test.db"))
    )
    req = ApprovalRequest(
        approval_token="tok_legacy_sys",
        run_id="run_leg",
        turn_index=1,
        status="PENDING",
        prompt="Legacy prompt",
        scope={},
        scope_digest="",
    )
    store.create_request(req)
    system_scope = ScopeToken(tags={}, digest="", is_system=True)
    resolved = store.resolve_request(
        approval_token="tok_legacy_sys",
        decision="APPROVED",
        decided_by="admin@system",
        scope=system_scope,
    )
    assert resolved.status == "APPROVED"


def test_matches_scope_from_tags_fallback():
    from agentv_runtime.scope import ScopeToken
    from eval_runner.reference.approval_store import _matches_scope

    scope = ScopeToken.from_tags({"tenant": "tenant_a"})
    req_match = ApprovalRequest(
        approval_token="tok_1",
        run_id="run_1",
        turn_index=1,
        scope={"tenant": "tenant_a"},
        scope_digest="",  # forces tag matching fallback
    )
    assert _matches_scope(req_match, scope) is True

    req_mismatch = ApprovalRequest(
        approval_token="tok_2",
        run_id="run_2",
        turn_index=1,
        scope={"tenant": "tenant_b"},
        scope_digest="",
    )
    assert _matches_scope(req_mismatch, scope) is False


def test_file_approval_store_degraded_and_corrupt_branches(tmp_path: Path, monkeypatch):
    from agentv_runtime.interfaces import ApprovalStorageDegradedError, ScopeMismatchError
    from agentv_runtime.scope import ScopeToken

    store = FileApprovalStore(base_dir=tmp_path / "degraded_file_store")
    tenant_scope = ScopeToken.from_tags({"tenant": "acme"})

    # 1. Atomic write error
    monkeypatch.setattr("os.replace", MagicMock(side_effect=OSError("disk failure")))
    with pytest.raises(ApprovalStorageDegradedError, match="Failed writing approval record"):
        store._atomic_write(tmp_path / "test.json", {"a": 1})
    monkeypatch.undo()

    # 2. Scanning OSError with scope
    monkeypatch.setattr(Path, "glob", MagicMock(side_effect=OSError("glob failure")))
    with pytest.raises(ApprovalStorageDegradedError, match="Error scanning approval directory"):
        store.get_request("nonexistent", scope=tenant_scope)
    monkeypatch.undo()

    # 3. Corrupt run_file with scope
    corrupt_run_file = store.base_dir / "corrupt_run.json"
    corrupt_run_file.write_text("{bad-json", encoding="utf-8")
    with pytest.raises(
        ApprovalStorageDegradedError, match="Corrupt or unreadable run approval file"
    ):
        store.get_request_by_run_id("corrupt_run", scope=tenant_scope)

    # 4. Corrupt token file
    corrupt_token_file = store.base_dir / "token_corrupt_tok.json"
    corrupt_token_file.write_text("{bad-json", encoding="utf-8")
    with pytest.raises(ApprovalStorageDegradedError, match="Corrupt or unreadable token file"):
        store.resolve_request("corrupt_tok", "APPROVED")

    # 5. Resolve already resolved request & legacy unscoped by tenant
    req = ApprovalRequest(
        approval_token="tok_leg_unscoped",
        run_id="run_leg_unscoped",
        turn_index=1,
        status="PENDING",
        scope={},
        scope_digest="",
    )
    store.create_request(req)
    with pytest.raises(ScopeMismatchError, match="UNSCOPED_LEGACY and cannot be resolved"):
        store.resolve_request("tok_leg_unscoped", "APPROVED", scope=tenant_scope)

    # Resolve to APPROVED, then re-resolve raises ValueError
    store.resolve_request("tok_leg_unscoped", "APPROVED")
    with pytest.raises(ValueError, match="is already resolved"):
        store.resolve_request("tok_leg_unscoped", "APPROVED")

    # 6. List pending with corrupt file and scope
    corrupt_pending = store.base_dir / "token_bad_pending.json"
    corrupt_pending.write_text("{bad-json", encoding="utf-8")
    with pytest.raises(ApprovalStorageDegradedError, match="Failed parsing pending approval file"):
        store.list_pending(scope=tenant_scope)
    corrupt_pending.unlink()

    # 7. Delete request partial existence
    req_del = ApprovalRequest(
        approval_token="tok_del_partial",
        run_id="run_del_partial",
        turn_index=1,
        status="PENDING",
    )
    store.create_request(req_del)
    token_file = store.base_dir / "token_tok_del_partial.json"
    token_file.unlink()  # remove token file so only run file exists
    assert store.delete_request("tok_del_partial") is True
    # Delete non-existent
    assert store.delete_request("nonexistent_token") is False

    # 8. Stream pending on FileApprovalStore
    req_stream = ApprovalRequest(
        approval_token="tok_stream_f", run_id="r_str", turn_index=1, status="PENDING"
    )
    store.create_request(req_stream)
    stream_events = list(store.stream_pending())
    assert any(e.request.approval_token == "tok_stream_f" for e in stream_events)


def test_sqlite_approval_store_degraded_and_stream_branches(tmp_path: Path, monkeypatch):
    import sqlite3

    from agentv_runtime.interfaces import ApprovalStorageDegradedError, ScopeMismatchError
    from agentv_runtime.scope import ScopeToken

    db_path = str(tmp_path / "sqlite_degraded.db")
    store = SQLiteApprovalStore(db_path=db_path)
    tenant_scope = ScopeToken.from_tags({"tenant": "acme"})

    # 1. Stream pending
    req1 = ApprovalRequest(approval_token="tok_sq1", run_id="r1", turn_index=1, status="PENDING")
    store.create_request(req1)
    events = list(store.stream_pending())
    assert len(events) == 1
    assert events[0].event_type == "PENDING"
    assert events[0].request.approval_token == "tok_sq1"

    # 2. SQLite error on operations via mocked connection
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.execute.side_effect = sqlite3.OperationalError("db locked")
    monkeypatch.setattr(store, "_get_connection", lambda: mock_conn)

    with pytest.raises(
        ApprovalStorageDegradedError, match="SQLite database error writing approval request"
    ):
        store.create_request(req1)
    with pytest.raises(
        ApprovalStorageDegradedError, match="SQLite database error getting approval request"
    ):
        store.get_request("tok_sq1")
    with pytest.raises(
        ApprovalStorageDegradedError, match="SQLite database error getting approval by run_id"
    ):
        store.get_request_by_run_id("r1")
    with pytest.raises(
        ApprovalStorageDegradedError, match="SQLite database error resolving approval request"
    ):
        store.resolve_request("tok_sq1", "APPROVED")
    with pytest.raises(
        ApprovalStorageDegradedError, match="SQLite database error listing pending approvals"
    ):
        store.list_pending(scope=tenant_scope)

    monkeypatch.setattr(store, "get_request", lambda *args, **kwargs: req1)
    with pytest.raises(
        ApprovalStorageDegradedError, match="SQLite database error deleting approval request"
    ):
        store.delete_request("tok_sq1")
    monkeypatch.undo()

    # 3. Resolve legacy unscoped by tenant scope in SQLite
    req_leg = ApprovalRequest(
        approval_token="tok_sq_leg",
        run_id="r_leg",
        turn_index=1,
        status="PENDING",
        scope={},
        scope_digest="",
    )
    store.create_request(req_leg)
    with pytest.raises(ScopeMismatchError, match="UNSCOPED_LEGACY and cannot be resolved"):
        store.resolve_request("tok_sq_leg", "APPROVED", scope=tenant_scope)

    # 4. Resolve already resolved in SQLite
    store.resolve_request("tok_sq_leg", "APPROVED")
    with pytest.raises(ValueError, match="is already resolved"):
        store.resolve_request("tok_sq_leg", "APPROVED")

    # 5. SQLite row with fewer than 21 items in _row_to_request
    row_short = (
        "tok_short",
        "r_s",
        0,
        "hash",
        "role",
        "{}",
        "PENDING",
        "rule",
        "chk",
        "{}",
        "prompt",
        123.0,
        None,
        None,
        None,
        None,
        "{}",
    )
    req_short = store._row_to_request(row_short)
    assert req_short.approval_token == "tok_short"
    assert req_short.scope == {}

    # 6. SQLite revoke request
    req_to_revoke = ApprovalRequest(
        approval_token="tok_rev_sq", run_id="r_rev", turn_index=1, status="PENDING"
    )
    store.create_request(req_to_revoke)
    rev_sq = store.revoke_request("tok_rev_sq", decided_by="admin", decision_reason="compromised")
    assert rev_sq.status == "REJECTED"
    assert "revocation" in rev_sq.metadata
    with pytest.raises(ValueError, match="A revoked approval token cannot be republished"):
        store.create_request(
            ApprovalRequest(
                approval_token="tok_rev_sq", run_id="r_rev", turn_index=2, status="PENDING"
            )
        )

    # 7. Scope mismatch on SQLite resolve
    other_scope = ScopeToken.from_tags({"tenant": "other"})
    req_other = ApprovalRequest(
        approval_token="tok_sq_other",
        run_id="r_other",
        turn_index=1,
        status="PENDING",
        scope=other_scope.tags,
        scope_digest=other_scope.digest,
    )
    store.create_request(req_other)
    with pytest.raises(ScopeMismatchError, match="Scope mismatch: active scope cannot resolve"):
        store.resolve_request("tok_sq_other", "APPROVED", scope=tenant_scope)

    # 8. get_request_by_run_id when rows exist but none match scope
    assert store.get_request_by_run_id("r_other", scope=tenant_scope) is None
    # 8b. list_pending when pending rows exist but none match scope
    assert store.list_pending(scope=tenant_scope) == []

    # 9. Concurrently resolved in SQLite (rowcount != 1)
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (
        "tok_c",
        "rc",
        0,
        "h",
        "role",
        "{}",
        "PENDING",
        "rule",
        "chk",
        "{}",
        "prompt",
        123.0,
        None,
        None,
        None,
        None,
        "{}",
        "{}",
        "",
        None,
        None,
    )
    mock_cursor.rowcount = 0
    mock_c = MagicMock()
    mock_c.cursor.return_value = mock_cursor
    monkeypatch.setattr(store, "_get_connection", lambda: mock_c)
    with pytest.raises(ValueError, match="Approval request was concurrently resolved"):
        store.resolve_request("tok_c", "APPROVED")
    monkeypatch.undo()


def test_file_approval_store_extra_branches(tmp_path: Path, monkeypatch):
    from agentv_runtime.interfaces import ApprovalStorageDegradedError, ScopeMismatchError
    from agentv_runtime.scope import ScopeToken

    base_dir = tmp_path / "file_extra"
    store = FileApprovalStore(base_dir=base_dir)
    tenant_scope = ScopeToken.from_tags({"tenant": "acme"})
    other_scope = ScopeToken.from_tags({"tenant": "other"})

    # Non-existent run_id
    assert store.get_request_by_run_id("missing_run") is None

    # Revoke request in FileApprovalStore
    req = ApprovalRequest(
        approval_token="tok_f_rev", run_id="r_f_rev", turn_index=1, status="PENDING"
    )
    store.create_request(req)
    rev = store.revoke_request("tok_f_rev", decided_by="admin", decision_reason="withdrawn")
    assert rev.status == "REJECTED"
    assert "revocation" in rev.metadata
    with pytest.raises(ValueError, match="A revoked approval token cannot be republished"):
        store.create_request(
            ApprovalRequest(
                approval_token="tok_f_rev", run_id="r_f_rev", turn_index=2, status="PENDING"
            )
        )

    # Scope mismatch on resolve in FileApprovalStore
    req_other = ApprovalRequest(
        approval_token="tok_f_other",
        run_id="r_f_other",
        turn_index=1,
        status="PENDING",
        scope=other_scope.tags,
        scope_digest=other_scope.digest,
    )
    store.create_request(req_other)
    with pytest.raises(ScopeMismatchError, match="Scope mismatch: active scope cannot resolve"):
        store.resolve_request("tok_f_other", "APPROVED", scope=tenant_scope)

    # list_pending with scope filters out req_other
    assert store.list_pending(scope=tenant_scope) == []

    # Glob failure in list_pending
    monkeypatch.setattr(Path, "glob", MagicMock(side_effect=OSError("disk error")))
    with pytest.raises(ApprovalStorageDegradedError, match="Error scanning approval directory"):
        store.list_pending(scope=tenant_scope)
    assert store.list_pending() == []
    monkeypatch.undo()


def test_matches_scope_edge_branches():
    from agentv_runtime.scope import ScopeToken
    from eval_runner.reference.approval_store import _matches_scope

    tenant_scope = ScopeToken.from_tags({"tenant": "acme"})
    # Legacy unscoped request with tenant scope
    req_leg = ApprovalRequest(
        approval_token="t_leg", run_id="r", turn_index=0, scope={}, scope_digest=""
    )
    assert not _matches_scope(req_leg, tenant_scope)

    # Request is scoped, but scope has no digest: falls back to req_token.matches(scope)
    req_with_dig = ApprovalRequest(
        approval_token="t_wd",
        run_id="r",
        turn_index=0,
        scope={"tenant": "acme"},
        scope_digest="some_digest",
    )
    scope_no_dig = ScopeToken(tags={"tenant": "acme"}, digest="", is_system=False)
    assert not _matches_scope(req_with_dig, scope_no_dig)


def test_migrate_unscoped_approval_branches(tmp_path: Path, monkeypatch):
    from eval_runner.reference.approval_store import migrate_unscoped_approval

    store = FileApprovalStore(base_dir=tmp_path / "mig_approvals")

    # 1. Not found -> KeyError
    with pytest.raises(KeyError, match="not found"):
        migrate_unscoped_approval("missing_token", store=store)

    # 2. Already scoped -> return as is
    req_scoped = ApprovalRequest(
        approval_token="tok_already_scoped",
        run_id="run_scoped",
        turn_index=1,
        scope={"tenant": "t1"},
        scope_digest="sha3_digest1",
    )
    store.create_request(req_scoped)
    mig_res = migrate_unscoped_approval("tok_already_scoped", store=store)
    assert mig_res.approval_token == req_scoped.approval_token
    assert mig_res.run_id == req_scoped.run_id

    # 3. Run ID mismatch
    req_unscoped = ApprovalRequest(
        approval_token="tok_mig",
        run_id="run_orig",
        turn_index=1,
        scope={},
        scope_digest="",
    )
    store.create_request(req_unscoped)
    with pytest.raises(ValueError, match="Run ID mismatch"):
        migrate_unscoped_approval("tok_mig", run_id="run_mismatch", store=store)

    # 4. Fallback to manifest when submission has no scope
    mock_run_store = MagicMock()
    mock_run_store.get_submission.return_value = None
    mock_run_store.get_run_manifest.return_value = {
        "manifest_id": "man_mig_01",
        "scope": {"tenant": "mig_tenant"},
        "scope_digest": "",
    }
    migrated = migrate_unscoped_approval(
        "tok_mig", run_id="run_orig", store=store, run_store=mock_run_store
    )
    assert migrated.scope == {"tenant": "mig_tenant"}
    assert migrated.manifest_id == "man_mig_01"
    assert "migration" in migrated.metadata
    assert "migrated_at" in migrated.metadata["migration"]

    # 4b. run_store is None (falls back to resolve_run_store)
    req_unscoped_rs_none = ApprovalRequest(
        approval_token="tok_mig_rs_none",
        run_id="run_orig_rs_none",
        turn_index=1,
        scope={},
        scope_digest="",
    )
    store.create_request(req_unscoped_rs_none)
    monkeypatch.setattr("eval_runner.runtime_services.resolve_run_store", lambda: mock_run_store)
    migrated_rs_none = migrate_unscoped_approval(
        "tok_mig_rs_none", run_id="run_orig_rs_none", store=store, run_store=None
    )
    assert migrated_rs_none.scope == {"tenant": "mig_tenant"}

    # 5. Migration directly from submission
    req_unscoped2 = ApprovalRequest(
        approval_token="tok_mig_sub",
        run_id="run_sub_orig",
        turn_index=1,
        scope={},
        scope_digest="",
    )
    store.create_request(req_unscoped2)
    mock_run_store.get_submission.return_value = {"context": {"tenant": "sub_tenant"}}
    migrated_sub = migrate_unscoped_approval(
        "tok_mig_sub", run_id="run_sub_orig", store=store, run_store=mock_run_store
    )
    assert migrated_sub.scope == {"tenant": "sub_tenant"}

    # 6. Cannot migrate when no scope exists
    req_unscoped3 = ApprovalRequest(
        approval_token="tok_mig_noscope",
        run_id="run_noscope",
        turn_index=1,
        scope={},
        scope_digest="",
    )
    store.create_request(req_unscoped3)
    mock_run_store.get_submission.return_value = None
    mock_run_store.get_run_manifest.return_value = None
    with pytest.raises(ValueError, match="no verified run or unambiguous scope"):
        migrate_unscoped_approval(
            "tok_mig_noscope", run_id="run_noscope", store=store, run_store=mock_run_store
        )

    # 6b. Cannot migrate when manifest has non-mapping context/scope
    req_unscoped3b = ApprovalRequest(
        approval_token="tok_mig_nomap",
        run_id="run_nomap",
        turn_index=1,
        scope={},
        scope_digest="",
    )
    store.create_request(req_unscoped3b)
    mock_run_store.get_run_manifest.return_value = {
        "manifest_id": "m_nomap",
        "context": "not_a_mapping",
    }
    with pytest.raises(ValueError, match="no verified run or unambiguous scope"):
        migrate_unscoped_approval(
            "tok_mig_nomap", run_id="run_nomap", store=store, run_store=mock_run_store
        )
        migrate_unscoped_approval(
            "tok_mig_noscope", run_id="run_noscope", store=store, run_store=mock_run_store
        )

    # 7. Scope digest mismatch in provenance
    req_unscoped4 = ApprovalRequest(
        approval_token="tok_mig_mismatch",
        run_id="run_mismatch_digest",
        turn_index=1,
        scope={},
        scope_digest="",
    )
    store.create_request(req_unscoped4)
    mock_run_store.get_submission.return_value = None
    mock_run_store.get_run_manifest.return_value = {
        "context": {"tenant": "mismatch_tenant"},
        "scope_digest": "corrupted_or_different_digest",
    }
    with pytest.raises(ValueError, match="Scope digest mismatch in run provenance"):
        migrate_unscoped_approval(
            "tok_mig_mismatch", run_id="run_mismatch_digest", store=store, run_store=mock_run_store
        )


def test_get_default_approval_store_extension_branch(monkeypatch):
    mock_resolve = MagicMock(return_value="mock_extension_store")
    monkeypatch.setattr("agentv_runtime.discovery.resolve_extension", mock_resolve)
    res = get_default_approval_store(store_type="custom_extension")
    assert res == "mock_extension_store"
    mock_resolve.assert_called_once()
