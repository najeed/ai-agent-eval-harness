"""
tests.unit.core.test_scope_bound_approval_persistence

Authoritative Test Suite for Phase 54: Scope-Bound HITL Persistence Contract.
Validates:
1. Mandatory-scope pause fail-closed (MandatoryScopeMissingError).
2. Four-way identical scope_digest binding across:
   - Persisted Approval Record
   - Checkpoint state and metadata
   - Run Index record
   - Execution Manifest
3. Cross-scope isolation on reads and resolution (ScopeMismatchError).
4. Atomic persistence of first-class scope fields in File and SQLite stores.
5. Storage degradation reporting (ApprovalStorageDegradedError instead of empty queue).
6. Legacy unscoped isolation and audited migration.
7. Architectural purity (zero Enterprise imports in Core).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import eval_runner.hitl.pending as hitl_pending
from agentv_runtime.interfaces import (
    ApprovalLedger,
    ApprovalRequest,
    ApprovalStorageDegradedError,
    MandatoryScopeMissingError,
    ScopeMismatchError,
)
from agentv_runtime.scope import (
    ScopePolicy,
    ScopeToken,
)
from eval_runner import config
from eval_runner.reference.approval_store import (
    FileApprovalStore,
    SQLiteApprovalStore,
    migrate_unscoped_approval,
)
from eval_runner.run_index import read_run_index
from eval_runner.session_components.approval_manager import SessionApprovalManager


class StrictEnterpriseScopePolicy(ScopePolicy):
    """Test policy requiring mandatory enterprise scope."""

    def is_scope_mandatory(self) -> bool:
        return True

    def validate_scope(self, scope: ScopeToken) -> None:
        if not scope.digest or not scope.tags.get("tenant_id"):
            raise MandatoryScopeMissingError("Valid tenant_id is required.")


class DummyCheckpointManager:
    """Mock checkpoint manager tracking saved checkpoints."""

    def __init__(self):
        self.checkpoints: dict[str, dict] = {}
        self._count = 0

    def create_checkpoint(self, state: dict, metadata: dict | None = None) -> str:
        self._count += 1
        cid = f"chk_{self._count:04d}"
        self.checkpoints[cid] = {"state": state, "metadata": metadata or {}}
        return cid


def test_approval_stores_implement_approval_ledger(tmp_path: Path):
    """FileApprovalStore and SQLiteApprovalStore satisfy the ApprovalLedger protocol."""
    file_store = FileApprovalStore(base_dir=tmp_path / "approvals")
    db_store = SQLiteApprovalStore(db_path=str(tmp_path / "approvals.db"))

    assert isinstance(file_store, ApprovalLedger)
    assert isinstance(db_store, ApprovalLedger)


def test_mandatory_scope_pause_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """AC 1: A mandatory-scope pause cannot be persisted without verified tags and digest."""
    monkeypatch.setenv("AGENTV_REQUIRE_ENTERPRISE_CONTEXT", "1")
    strict_policy = StrictEnterpriseScopePolicy()

    with patch("agentv_runtime.scope.get_active_scope_policy", return_value=strict_policy):
        store = FileApprovalStore(base_dir=tmp_path / "approvals")
        mgr = SessionApprovalManager(run_id="run_unscoped_01", approval_store=store)

        with pytest.raises(MandatoryScopeMissingError) as exc_info:
            mgr.create_durable_request(
                turn_index=1,
                action_payload={"tool": "transfer_funds", "amount": 1000},
                metadata={},  # No scope tags provided
            )

        assert "MandatoryScopeMissing" in str(exc_info.value)


def test_four_way_scope_digest_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Manifest, run index, checkpoint, and approval record contain identical scope digests."""
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)

    scope_data = {
        "org_id": "org_acme",
        "tenant_id": "tenant_prod",
        "workspace_id": "ws_fin",
        "active_environment": "production",
    }
    token = ScopeToken.from_tags(scope_data)
    run_id = "run_four_way_01"

    store = FileApprovalStore(base_dir=tmp_path / "approvals")
    chk_mgr = DummyCheckpointManager()

    mgr = SessionApprovalManager(
        run_id=run_id,
        approval_store=store,
        checkpoint_manager=chk_mgr,
        scope=token,
    )

    persisted = mgr.create_durable_request(
        turn_index=3,
        action_payload={"tool": "deploy_service", "version": "1.2.0"},
        metadata={"task_id": "task_deploy", "scenario_id": "scen_prod_deploy"},
    )

    # 1. Approval record
    assert persisted.scope_digest == token.digest
    assert persisted.scope == scope_data
    assert persisted.scope_status == "SCOPED"
    assert persisted.is_legacy_unscoped is False
    assert persisted.manifest_id is not None
    assert persisted.idempotency_key is not None
    assert isinstance(persisted.created_at, datetime)

    # 2. Checkpoint
    assert len(chk_mgr.checkpoints) == 1
    chk_data = list(chk_mgr.checkpoints.values())[0]
    assert chk_data["metadata"]["scope_digest"] == token.digest
    assert chk_data["metadata"]["scope"] == scope_data
    assert chk_data["state"]["scope_digest"] == token.digest

    # 3. Run Index
    idx_rec = read_run_index(run_id, root=tmp_path / "runs")
    assert idx_rec is not None
    assert idx_rec["scope_digest"] == token.digest
    assert idx_rec["context"] == scope_data

    # 4. Execution Manifest
    manifest_file = tmp_path / "runs" / run_id / "execution_manifest.json"
    assert manifest_file.exists()
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["scope_digest"] == token.digest
    assert manifest_data["scope"] == scope_data
    from agentv_runtime.manifest import ExecutionManifest

    manifest_obj = ExecutionManifest.from_dict(manifest_data)
    assert manifest_obj.scope == scope_data

    # All four match exactly
    assert (
        persisted.scope_digest
        == chk_data["metadata"]["scope_digest"]
        == idx_rec["scope_digest"]
        == manifest_data["scope_digest"]
        == token.digest
    )


@pytest.mark.parametrize("store_type", ["file", "sqlite"])
def test_cross_scope_isolation_read_and_resolve(tmp_path: Path, store_type: str):
    """AC 3: Matching scope can read & resolve; mismatched scope cannot list or resolve."""
    if store_type == "file":
        store = FileApprovalStore(base_dir=tmp_path / f"approvals_{store_type}")
    else:
        store = SQLiteApprovalStore(db_path=str(tmp_path / f"approvals_{store_type}.db"))

    scope_a = ScopeToken.from_tags({"tenant_id": "tenant_alpha", "org_id": "org_1"})
    scope_b = ScopeToken.from_tags({"tenant_id": "tenant_beta", "org_id": "org_2"})

    run_id = f"run_iso_{store_type}"
    req = ApprovalRequest(
        approval_token=f"tok_{store_type}_01",
        run_id=run_id,
        turn_index=1,
        status="PENDING",
        prompt="Transfer authorization",
        scope=dict(scope_a.tags),
        scope_digest=scope_a.digest,
        manifest_id=f"man_{run_id}",
    )
    store.create_request(req)

    # 1. Matching scope can read
    matching_req = store.get_request(req.approval_token, scope=scope_a)
    assert matching_req is not None
    assert matching_req.approval_token == req.approval_token

    matching_list = list(store.list_pending(run_id=run_id, scope=scope_a))
    assert len(matching_list) == 1
    assert matching_list[0].approval_token == req.approval_token

    # 2. Other scope cannot read (returns None / empty queue)
    mismatched_req = store.get_request(req.approval_token, scope=scope_b)
    assert mismatched_req is None

    mismatched_list = list(store.list_pending(run_id=run_id, scope=scope_b))
    assert len(mismatched_list) == 0

    # 3. Other scope attempting resolution raises ScopeMismatchError
    with pytest.raises(ScopeMismatchError):
        store.resolve_request(
            approval_token=req.approval_token,
            decision="APPROVED",
            decided_by="intruder@beta.com",
            scope=scope_b,
        )

    # 4. Matching scope can resolve successfully
    resolved = store.resolve_request(
        approval_token=req.approval_token,
        decision="APPROVED",
        decided_by="auditor@alpha.com",
        decision_reason="Verified authorization",
        scope=scope_a,
    )
    assert resolved.status == "APPROVED"
    assert resolved.decided_by == "auditor@alpha.com"


@pytest.mark.parametrize("store_type", ["file", "sqlite"])
def test_atomic_persistence_of_scope_fields(tmp_path: Path, store_type: str):
    """AC 4: Stores persist scope, scope_digest, manifest_id, idempotency_key atomically."""
    if store_type == "file":
        store = FileApprovalStore(base_dir=tmp_path / f"approvals_atom_{store_type}")
    else:
        store = SQLiteApprovalStore(db_path=str(tmp_path / f"approvals_atom_{store_type}.db"))

    scope = ScopeToken.from_tags({"tenant_id": "tenant_zeta", "workspace_id": "ws_sec"})
    now_utc = datetime.now(UTC)

    req = ApprovalRequest(
        approval_token=f"tok_atom_{store_type}",
        run_id=f"run_atom_{store_type}",
        turn_index=2,
        outbound_payload_hash="sha3_256:abc123payload",
        required_role="security_officer",
        reviewer_credentials={"level": "tier_3"},
        status="PENDING",
        rule_id="RULE_FINANCIAL_GATE",
        checkpoint_id="chk_0042",
        action_payload={"tx_id": "tx_9988"},
        prompt="Sign off financial transaction",
        metadata={"custom_flag": True},
        scope=dict(scope.tags),
        scope_digest=scope.digest,
        manifest_id="manifest_rev_001",
        idempotency_key="key_idempotent_99",
        created_at=now_utc,
    )

    created = store.create_request(req)
    assert created.approval_token == req.approval_token

    # Reload from store independently
    loaded = store.get_request(req.approval_token, scope=scope)
    assert loaded is not None
    assert loaded.approval_token == req.approval_token
    assert loaded.scope_digest == scope.digest
    assert loaded.scope == scope.tags
    assert loaded.manifest_id == "manifest_rev_001"
    assert loaded.idempotency_key == "key_idempotent_99"
    assert loaded.required_role == "security_officer"
    assert loaded.reviewer_credentials == {"level": "tier_3"}
    assert loaded.rule_id == "RULE_FINANCIAL_GATE"
    assert loaded.checkpoint_id == "chk_0042"
    assert loaded.action_payload == {"tx_id": "tx_9988"}
    assert loaded.metadata == {"custom_flag": True}
    assert isinstance(loaded.created_at, datetime)
    assert abs((loaded.created_at - now_utc).total_seconds()) < 2.0


def test_unreadable_approval_storage_reports_degradation(tmp_path: Path):
    """AC 6: Unreadable approval storage yields explicit availability failure, not empty queue."""
    # 1. FileApprovalStore degradation
    corrupt_dir = tmp_path / "corrupt_approvals"
    corrupt_dir.mkdir(parents=True, exist_ok=True)
    corrupt_token_file = corrupt_dir / "token_corrupt_tok.json"
    corrupt_token_file.write_text("CORRUPTED_JSON_NOT_VALID", encoding="utf-8")

    file_store = FileApprovalStore(base_dir=corrupt_dir)
    scope = ScopeToken.from_tags({"tenant_id": "tenant_1"})

    with patch.object(Path, "glob", side_effect=OSError("Disk I/O Error: unreadable sector")):
        with pytest.raises(ApprovalStorageDegradedError) as exc_info:
            list(file_store.list_pending(run_id="run_any", scope=scope))
        assert "Error scanning approval directory" in str(exc_info.value)

    # 2. SQLiteApprovalStore degradation
    db_store = SQLiteApprovalStore(db_path=str(tmp_path / "degraded.db"))
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.execute.side_effect = sqlite3.DatabaseError(
        "database disk image is malformed"
    )
    with patch.object(db_store, "_get_connection", return_value=mock_conn):
        with pytest.raises(ApprovalStorageDegradedError) as exc_info_db:
            list(db_store.list_pending(run_id="run_any", scope=scope))
        assert "SQLite database error listing pending approvals" in str(exc_info_db.value)


def test_legacy_unscoped_approvals_hidden_and_migratable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """AC 7: Legacy unscoped approvals remain unavailable until privileged, audited migration."""
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)

    store = FileApprovalStore(base_dir=tmp_path / "approvals")
    run_id = "run_legacy_migration_01"

    # Create unscoped legacy approval
    legacy_req = ApprovalRequest(
        approval_token="tok_legacy_001",
        run_id=run_id,
        turn_index=1,
        status="PENDING",
        prompt="Legacy un-scoped action",
        scope={},
        scope_digest="",  # Unscoped
    )
    store.create_request(legacy_req)

    tenant_scope = ScopeToken.from_tags(
        {
            "org_id": "org_1",
            "tenant_id": "tenant_gamma",
            "workspace_id": "ws_1",
            "active_environment": "staging",
        }
    )

    # 1. Unscoped approval must NOT appear in tenant queue
    pending_tenant = list(store.list_pending(run_id=run_id, scope=tenant_scope))
    assert len(pending_tenant) == 0

    # 2. Migration fails closed if run identity has no verified provenance
    with pytest.raises(ValueError) as val_err:
        migrate_unscoped_approval(
            approval_token="tok_legacy_001",
            store=store,
            operator="secops_admin",
            reason="Backfill tenant scope",
            run_index_root=tmp_path / "runs",
        )
    assert "no verified run or unambiguous scope" in str(val_err.value)

    # 3. Create verified run provenance in run index
    from eval_runner.run_index import create_run_index

    create_run_index(
        run_id=run_id,
        context=tenant_scope.tags,
        scenario_id="scen_migrated",
        root=tmp_path / "runs",
    )

    # 4. Privileged migration succeeds with audit trail
    migrated = migrate_unscoped_approval(
        approval_token="tok_legacy_001",
        store=store,
        operator="secops_admin",
        reason="Backfilled verified scope from run_index",
        run_index_root=tmp_path / "runs",
    )

    assert migrated.scope_digest == tenant_scope.digest
    assert migrated.scope == tenant_scope.tags
    assert migrated.scope_status == "SCOPED"
    assert migrated.is_legacy_unscoped is False
    assert "migration" in migrated.metadata
    assert migrated.metadata["migration"]["operator"] == "secops_admin"
    assert migrated.metadata["migration"]["reason"] == "Backfilled verified scope from run_index"

    # 5. Approval now appears in tenant queue
    pending_now = list(store.list_pending(run_id=run_id, scope=tenant_scope))
    assert len(pending_now) == 1
    assert pending_now[0].approval_token == "tok_legacy_001"


def test_core_retains_no_enterprise_imports():
    """AC 8: Core retains zero imports of Enterprise packages."""
    import re
    import sys

    # Target modules
    target_modules = [
        "agentv_runtime.interfaces",
        "agentv_runtime.scope",
        "eval_runner.reference.approval_store",
        "eval_runner.session_components.approval_manager",
        "eval_runner.run_index",
    ]

    for mod_name in target_modules:
        mod = sys.modules.get(mod_name)
        assert mod is not None, f"Module '{mod_name}' not loaded"
        source = Path(mod.__file__).read_text(encoding="utf-8")
        has_enterprise_import = bool(
            re.search(r"^\s*(?:from|import)\s+enterprise\b", source, re.MULTILINE)
        )
        assert not has_enterprise_import, (
            f"Module '{mod_name}' contains illegal Enterprise package imports."
        )


def test_session_approval_manager_property_and_list_pending(tmp_path: Path):
    store = FileApprovalStore(base_dir=tmp_path / "approvals")
    with patch(
        "eval_runner.session_components.approval_manager.resolve_approval_store", return_value=store
    ):
        mgr = SessionApprovalManager(run_id="run_prop_01")
        assert mgr.approval_store is store


def test_request_approval_plugin_interceptor_rejections_and_state_failure(tmp_path: Path):
    registry = hitl_pending.PendingApprovalRegistry()
    mock_plugin = MagicMock()

    # 1. Interceptor returns False
    mock_plugin.trigger_interceptor.return_value = False
    mock_plugin.last_rejection_reason = "Policy violation"
    mgr = SessionApprovalManager(
        run_id="run_plug_01", registry=registry, plugin_manager=mock_plugin
    )
    with pytest.raises(PermissionError, match="Policy violation"):
        mgr.request_approval("t1", "tool_x", {})

    # 2. Interceptor returns allowed: False with error string
    mock_plugin.trigger_interceptor.return_value = {"allowed": False, "error": "Custom rule fail"}
    mock_plugin.last_rejection_reason = None
    with pytest.raises(PermissionError, match="Custom rule fail"):
        mgr.request_approval("t1", "tool_x", {})

    # 3. Interceptor returns allowed: False with default message
    mock_plugin.trigger_interceptor.return_value = {"allowed": False}
    with pytest.raises(PermissionError, match="Approval rejected by security policy"):
        mgr.request_approval("t1", "tool_x", {})

    # 4. State provider raises exception -> checkpoint still created
    mock_plugin.trigger_interceptor.return_value = True
    chk = DummyCheckpointManager()

    def fail_state():
        raise RuntimeError("state provider crash")

    mgr_state = SessionApprovalManager(
        run_id="run_state_01",
        registry=registry,
        checkpoint_manager=chk,
        state_provider=fail_state,
        plugin_manager=mock_plugin,
    )
    appr = mgr_state.request_approval("t1", "tool_x", {"param": 1})
    assert appr.run_id == "run_state_01"
    assert len(chk.checkpoints) == 1

    # 5. List and resolve pending approvals
    assert len(mgr_state.list_pending_approvals()) == 1
    assert mgr_state.resolve_approval(appr.id, "approve", response="OK", resolved_by="admin")
    assert len(mgr_state.list_pending_approvals()) == 0


def test_create_durable_request_scope_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    store = FileApprovalStore(base_dir=tmp_path / "approvals")

    valid_context = {
        "org_id": "org_1",
        "tenant_id": "t1",
        "workspace_id": "ws_1",
        "active_environment": "staging",
    }
    scope_token = ScopeToken.from_tags(valid_context)

    # 1. Candidate scope via meta["scope_token"]
    mgr1 = SessionApprovalManager(run_id="run_sc_01", approval_store=store)
    req1 = mgr1.create_durable_request(
        turn_index=1,
        metadata={"scope_token": scope_token},
    )
    assert req1.scope_digest == scope_token.digest

    # 2. Candidate scope via run_index.read_run_index
    from eval_runner.run_index import create_run_index

    ctx2 = dict(valid_context, tenant_id="t2")
    create_run_index(run_id="run_sc_02", context=ctx2, scenario_id="sc_02", root=tmp_path / "runs")
    mgr2 = SessionApprovalManager(run_id="run_sc_02", approval_store=store)
    req2 = mgr2.create_durable_request(turn_index=1)
    assert req2.scope["tenant_id"] == "t2"

    # 3. Candidate scope via state_provider metadata and scenario_data
    def provider_with_scope():
        return {"scenario_data": {"runtime_context": dict(valid_context, tenant_id="t3")}}

    mgr3 = SessionApprovalManager(
        run_id="run_sc_03", approval_store=store, state_provider=provider_with_scope
    )
    req3 = mgr3.create_durable_request(turn_index=1)
    assert req3.scope["tenant_id"] == "t3"

    # 4. Candidate scope via injected run_store.get_manifest
    mock_run_store = MagicMock()
    mock_run_store.get_manifest.return_value = {"context": dict(valid_context, tenant_id="t4")}
    mgr4 = SessionApprovalManager(
        run_id="run_sc_04", approval_store=store, run_store=mock_run_store
    )
    req4 = mgr4.create_durable_request(turn_index=1)
    assert req4.scope["tenant_id"] == "t4"

    # 5. Raw context as ScopeToken directly in meta["runtime_context"]
    mgr5 = SessionApprovalManager(run_id="run_sc_05", approval_store=store)
    req5 = mgr5.create_durable_request(turn_index=1, metadata={"runtime_context": scope_token})
    assert req5.scope_digest == scope_token.digest

    # 6. Policy query raises exception
    mock_policy = MagicMock()
    mock_policy.is_scope_mandatory.side_effect = RuntimeError("Policy check failure")
    with patch("agentv_runtime.scope.get_active_scope_policy", return_value=mock_policy):
        mgr6 = SessionApprovalManager(run_id="run_sc_06", approval_store=store)
        req6 = mgr6.create_durable_request(turn_index=1)
        assert req6.status == "PENDING"


def test_create_durable_request_plugin_interceptor_rejection(tmp_path: Path):
    store = FileApprovalStore(base_dir=tmp_path / "approvals")
    mock_plugin = MagicMock()
    mock_plugin.trigger_interceptor.return_value = False
    mock_plugin.last_rejection_reason = "Durable policy reject"

    mgr = SessionApprovalManager(
        run_id="run_durable_reject", approval_store=store, plugin_manager=mock_plugin
    )
    with pytest.raises(PermissionError, match="Durable policy reject"):
        mgr.create_durable_request(turn_index=1)

    mock_plugin.trigger_interceptor.return_value = {
        "allowed": False,
        "error": "Custom durable error",
    }
    mock_plugin.last_rejection_reason = None
    with pytest.raises(PermissionError, match="Custom durable error"):
        mgr.create_durable_request(turn_index=1)


def test_create_durable_request_manifest_and_run_index_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    run_dir = tmp_path / "runs" / "run_mismatch_01"
    run_dir.mkdir(parents=True, exist_ok=True)
    store = FileApprovalStore(base_dir=tmp_path / "approvals")

    valid_context = {
        "org_id": "org_1",
        "tenant_id": "t1",
        "workspace_id": "ws_1",
        "active_environment": "staging",
    }
    token_b = ScopeToken.from_tags(dict(valid_context, tenant_id="b"))

    # 1. Execution manifest on disk with mismatched scope digest
    manifest_path = run_dir / "execution_manifest.json"
    manifest_path.write_text(
        json.dumps({"manifest_id": "m1", "scope_digest": "digest_a"}), encoding="utf-8"
    )

    mgr = SessionApprovalManager(run_id="run_mismatch_01", approval_store=store, scope=token_b)
    with pytest.raises(
        ScopeMismatchError, match="Scope digest mismatch between execution manifest"
    ):
        mgr.create_durable_request(turn_index=1)

    # 2. Matching execution manifest is updated cleanly
    manifest_path.write_text(
        json.dumps({"manifest_id": "m1", "scope_digest": token_b.digest}), encoding="utf-8"
    )
    req = mgr.create_durable_request(turn_index=1)
    assert req.manifest_id == "m1"

    # 3. Pre-existing run index record with mismatched digest
    from eval_runner.run_index import create_run_index

    ctx_a = dict(valid_context, tenant_id="a")
    create_run_index(
        run_id="run_mismatch_02", context=ctx_a, scenario_id="sc_mismatch", root=tmp_path / "runs"
    )
    mgr2 = SessionApprovalManager(run_id="run_mismatch_02", approval_store=store, scope=token_b)
    with pytest.raises(ScopeMismatchError, match="Scope digest mismatch between run index"):
        mgr2.create_durable_request(turn_index=1)

    # 4. Pre-existing run index record with matching digest updates status
    create_run_index(
        run_id="run_match_idx",
        context=dict(valid_context, tenant_id="b"),
        scenario_id="sc_match",
        root=tmp_path / "runs",
    )
    mgr_match = SessionApprovalManager(run_id="run_match_idx", approval_store=store, scope=token_b)
    req_match = mgr_match.create_durable_request(turn_index=1)
    assert req_match.status == "PENDING"


def test_create_durable_request_fallbacks_and_fault_tolerance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    store = FileApprovalStore(base_dir=tmp_path / "approvals")

    # 1. State provider returns scenario_id and checkpoint state
    def provider_with_scenario():
        return {"scenario_data": {"id": "scenario_42"}, "extra_state": True}

    chk = DummyCheckpointManager()
    mock_plugin = MagicMock()
    mock_plugin.trigger_interceptor.return_value = True
    mock_plugin.trigger.side_effect = RuntimeError(
        "Plugin trigger error"
    )  # on_approval_created fails

    mock_bus = MagicMock()
    mock_bus.emit.side_effect = RuntimeError("Event bus emit error")

    mgr = SessionApprovalManager(
        run_id="run_fault_01",
        approval_store=store,
        checkpoint_manager=chk,
        state_provider=provider_with_scenario,
        plugin_manager=mock_plugin,
        event_bus=mock_bus,
    )

    req = mgr.create_durable_request(
        turn_index=2,
        action_payload={"tool": "exec", "cmd": "ls"},
        idempotency_key="custom_idemp_key",
    )
    assert req.idempotency_key == "custom_idemp_key"
    assert len(chk.checkpoints) == 1
    assert chk.checkpoints["chk_0001"]["state"]["extra_state"] is True

    # 2. Checkpoint state provider error is tolerated
    def crash_state():
        raise RuntimeError("Checkpoint state extraction error")

    mgr_crash = SessionApprovalManager(
        run_id="run_fault_02",
        approval_store=store,
        checkpoint_manager=chk,
        state_provider=crash_state,
    )
    req_crash = mgr_crash.create_durable_request(turn_index=1)
    assert req_crash.status == "PENDING"

    # 3. Execution manifest write error and run index creation error are caught
    with patch("pathlib.Path.replace", side_effect=OSError("Disk write error")):
        mgr_disk_err = SessionApprovalManager(run_id="run_disk_err", approval_store=store)
        req_disk_err = mgr_disk_err.create_durable_request(turn_index=1)
        assert req_disk_err.status == "PENDING"


def test_resolve_durable_request_approval_lifecycle_and_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    store = FileApprovalStore(base_dir=tmp_path / "approvals")
    token_scope = ScopeToken.from_tags({"tenant": "prod"})

    mock_run_store = MagicMock()
    mock_plugin = MagicMock()
    mock_plugin.trigger_interceptor.return_value = True
    mock_plugin.trigger.side_effect = RuntimeError("on_approval_resolved failed")
    mock_bus = MagicMock()
    mock_bus.emit.side_effect = RuntimeError("emit failed")

    mgr = SessionApprovalManager(
        run_id="run_resolve_01",
        approval_store=store,
        scope=token_scope,
        run_store=mock_run_store,
        plugin_manager=mock_plugin,
        event_bus=mock_bus,
    )

    req = mgr.create_durable_request(turn_index=1)

    # 1. Interceptor rejection on resolution
    mock_plugin.trigger_interceptor.return_value = {
        "allowed": False,
        "error": "Resolution forbidden",
    }
    with pytest.raises(PermissionError, match="Resolution forbidden"):
        mgr.resolve_durable_request(req.approval_token, decision="APPROVED")

    # 2. Successful approval resolution with bound recorder & lifecycle transition
    mock_plugin.trigger_interceptor.return_value = True
    with (
        patch("eval_runner.flight_recorder.FlightRecorderPlugin.bind_active_recorder") as mock_bind,
        patch("eval_runner.run_lifecycle.transition_run_lifecycle") as mock_trans,
    ):
        resolved = mgr.resolve_durable_request(
            req.approval_token,
            decision="APPROVED",
            decided_by="admin",
            decision_reason="Verified valid",
        )
        assert resolved.status == "APPROVED"
        mock_bind.assert_called_once_with(
            "run_resolve_01", mock_run_store, context={"tenant": "prod"}
        )
        mock_trans.assert_called_once()

    # 3. get_durable_request and list_durable_pending with and without explicit scope
    assert mgr.get_durable_request(req.approval_token) is not None
    assert mgr.get_durable_request(req.approval_token, scope=token_scope) is not None
    assert len(mgr.list_durable_pending()) == 0  # It was approved, no longer pending

    # 4. Resolve rejection leaves run closed without recorder binding
    req_rej = mgr.create_durable_request(turn_index=2)
    mock_plugin.trigger.side_effect = None
    mock_bus.emit.side_effect = None
    resolved_rej = mgr.resolve_durable_request(req_rej.approval_token, decision="REJECTED")
    assert resolved_rej.status == "REJECTED"


def test_approval_manager_uncovered_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    store = FileApprovalStore(base_dir=tmp_path / "approvals")
    valid_context = {
        "org_id": "org_1",
        "tenant_id": "t1",
        "workspace_id": "ws_1",
        "active_environment": "staging",
    }
    scope_token = ScopeToken.from_tags(valid_context)

    # 1. request_approval without plugin_manager, without checkpoint_manager (67->84, 84->105)
    registry = hitl_pending.PendingApprovalRegistry()
    mgr_basic = SessionApprovalManager(run_id="run_basic_01", registry=registry)
    appr1 = mgr_basic.request_approval("task_1", "my_tool", {"a": 1})
    assert appr1.run_id == "run_basic_01"

    # 2. request_approval with checkpoint_manager but state_provider is None (91->96)
    chk = DummyCheckpointManager()
    mgr_chk_only = SessionApprovalManager(
        run_id="run_chk_only", registry=registry, checkpoint_manager=chk
    )
    appr2 = mgr_chk_only.request_approval("task_2", "my_tool", {"b": 2})
    assert appr2.run_id == "run_chk_only"

    # 3. state_provider raises exception during scope extraction (174->185)
    def fail_scope_st():
        raise RuntimeError("state provider crash on scope")

    mgr_st_fail = SessionApprovalManager(
        run_id="run_st_fail",
        approval_store=store,
        state_provider=fail_scope_st,
    )
    req_st_fail = mgr_st_fail.create_durable_request(turn_index=1)
    assert req_st_fail.status == "PENDING"

    # 4. run_store.get_manifest raises exception and returns empty context (188->193, 190-191)
    mock_rs = MagicMock()
    mock_rs.get_manifest.side_effect = RuntimeError("run store get_manifest failed")
    mgr_rs_fail = SessionApprovalManager(
        run_id="run_rs_fail", approval_store=store, run_store=mock_rs
    )
    req_rs_fail = mgr_rs_fail.create_durable_request(turn_index=1)
    assert req_rs_fail.status == "PENDING"

    mock_rs.get_manifest.side_effect = None
    mock_rs.get_manifest.return_value = {}  # No context
    mgr_rs_empty = SessionApprovalManager(
        run_id="run_rs_empty", approval_store=store, run_store=mock_rs
    )
    req_rs_empty = mgr_rs_empty.create_durable_request(turn_index=1)
    assert req_rs_empty.status == "PENDING"

    # 5. Patch get_active_scope_policy on approval_manager module where it was imported (202-203)
    mock_pol = MagicMock()
    mock_pol.is_scope_mandatory.side_effect = RuntimeError("is_scope_mandatory crash")
    with patch(
        "eval_runner.session_components.approval_manager.get_active_scope_policy",
        return_value=mock_pol,
    ):
        mgr_pol_err = SessionApprovalManager(run_id="run_pol_err", approval_store=store)
        req_pol_err = mgr_pol_err.create_durable_request(turn_index=1)
        assert req_pol_err.status == "PENDING"

    # 6. is_scope_mandatory is True AND candidate_scope is valid (206->212)
    mock_pol_mandatory = MagicMock()
    mock_pol_mandatory.is_scope_mandatory.return_value = True
    with patch(
        "eval_runner.session_components.approval_manager.get_active_scope_policy",
        return_value=mock_pol_mandatory,
    ):
        mgr_mand_ok = SessionApprovalManager(
            run_id="run_mand_ok", approval_store=store, scope=scope_token
        )
        req_mand_ok = mgr_mand_ok.create_durable_request(turn_index=1)
        assert req_mand_ok.scope_digest == scope_token.digest

    # 7. execution_manifest on disk has no manifest_id (281) and corrupt JSON (288-289)
    run_dir_281 = tmp_path / "runs" / "run_281"
    run_dir_281.mkdir(parents=True, exist_ok=True)
    man_281 = run_dir_281 / "execution_manifest.json"
    man_281.write_text(
        json.dumps({"scope_digest": scope_token.digest}), encoding="utf-8"
    )  # no manifest_id
    mgr_281 = SessionApprovalManager(run_id="run_281", approval_store=store, scope=scope_token)
    req_281 = mgr_281.create_durable_request(turn_index=1, manifest_id="man_explicit_281")
    assert req_281.manifest_id == "man_explicit_281"

    # Corrupt execution_manifest.json (288-289)
    run_dir_corrupt = tmp_path / "runs" / "run_corrupt"
    run_dir_corrupt.mkdir(parents=True, exist_ok=True)
    (run_dir_corrupt / "execution_manifest.json").write_text("{bad-json", encoding="utf-8")
    mgr_corrupt = SessionApprovalManager(run_id="run_corrupt", approval_store=store)
    req_corrupt = mgr_corrupt.create_durable_request(turn_index=1)
    assert req_corrupt.status == "PENDING"

    # 8. state_provider returns non-dict and create_run_index raises
    def non_dict_st():
        return "not-a-dict"

    mgr_non_dict = SessionApprovalManager(
        run_id="run_non_dict",
        approval_store=store,
        checkpoint_manager=chk,
        state_provider=non_dict_st,
    )
    with patch(
        "eval_runner.run_index.create_run_index", side_effect=RuntimeError("create_run_index error")
    ):
        req_non_dict = mgr_non_dict.create_durable_request(turn_index=1)
        assert req_non_dict.status == "PENDING"

    # 9. resolve_durable_request without plugin_manager
    mgr_no_plugin = SessionApprovalManager(run_id="run_no_plug", approval_store=store)
    req_no_plug = mgr_no_plugin.create_durable_request(turn_index=1)
    res_no_plug = mgr_no_plugin.resolve_durable_request(
        req_no_plug.approval_token, decision="REJECTED"
    )
    assert res_no_plug.status == "REJECTED"

    # 10. resolve_durable_request with plugin_manager when token is not found
    mock_plug = MagicMock()
    mock_plug.trigger_interceptor.return_value = True
    mgr_plug_missing = SessionApprovalManager(
        run_id="run_plug_miss", approval_store=store, plugin_manager=mock_plug
    )
    # Store does not have non-existent-token
    with pytest.raises(KeyError):
        mgr_plug_missing.resolve_durable_request("non-existent-token", decision="APPROVED")
