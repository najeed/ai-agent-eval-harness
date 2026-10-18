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
