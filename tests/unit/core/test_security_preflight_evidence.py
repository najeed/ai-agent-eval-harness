"""Unit tests for typed failure evidence emission on security preflight and authorization mutations.

Ensures that adversarial mutations rejected before agent dispatch:
1. Register execution node attempt ('status: running').
2. Emit typed AssertionEvaluated event with 'outcome: FAIL' and 'security:{fault}'.
3. Emit terminal ExecutionGraphNode ('status: failed', 'failure_class: APPROVAL_SECURITY_REJECTED').
4. Enable Trust Center / CertificationService to attest evaluation failure ('attested_failed')
   without DecisionOnlyTrace errors.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentv_runtime.evidence_graph import build_evidence_graph_from_events
from eval_runner import config
from eval_runner.identity import IdentityService
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.runner import DefaultRunner, run_scenario
from eval_runner.services.certification import execute_industrial_certification


@pytest.fixture
def test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up isolated project root, keys, and local run store."""
    project_root = tmp_path / "project"
    trust_root = project_root / ".aes" / "keys"
    trust_root.mkdir(parents=True, exist_ok=True)
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(config, "TRUST_ROOT", trust_root)

    # Provision identities needed for evaluation kernel and certification authority
    for ident in ("system_id", "eval_runner.runner.EvaluationKernel", "eval_kernel"):
        IdentityService._provision_local_identity(ident)

    store = LocalFileRunStore(runs_dir)
    return store, runs_dir, trust_root


def test_security_preflight_approval_stale_emits_typed_failure_evidence(test_env):
    store, runs_dir, _ = test_env
    run_id = "run-preflight-stale-001"

    scenario = {
        "id": "scenario_stale_approval_test",
        "version": "1.0.0",
        "execution_mode": "live",
        "failure_policy": "fail_fast",
        "workflow": {
            "nodes": [
                {
                    "id": "step_transfer_funds",
                    "task_description": "Transfer 500 USD with pre-authorized token",
                    "approval_token": "EXPIRED_SIG_1970",
                    "expected_outcome": [{"target": "state", "property": "ok", "expected": True}],
                }
            ],
            "edges": [],
        },
    }

    runner = DefaultRunner(run_store=store)
    result = run_scenario(
        scenario=scenario,
        attempts=1,
        run_id=run_id,
        runner=runner,
        run_store=store,
    )

    # 1. Run must fail cleanly
    assert result.pass_at_k == 0.0
    assert result.successful_attempts == 0
    assert result.total_attempts == 1

    # 2. Inspect physical trace persisted to store
    trace_events = store.get_events(run_id, offset=0, limit=10_000)
    assert len(trace_events) > 0

    event_names = [e.get("event") for e in trace_events if isinstance(e, dict)]
    assert "run_start" in event_names
    assert "execution_graph_node" in event_names
    assert "assertion_evaluated" in event_names
    assert "run_end" in event_names

    # Check the assertion_evaluated event
    assertion_events = [
        e for e in trace_events if isinstance(e, dict) and e.get("event") == "assertion_evaluated"
    ]
    assert len(assertion_events) >= 1
    stale_assertion = next(
        (a for a in assertion_events if a.get("oracle_id") == "security:approval_stale"), None
    )
    assert stale_assertion is not None
    assert stale_assertion.get("outcome") == "FAIL"
    assert stale_assertion.get("passed") is False
    assert stale_assertion.get("expected") == "ALLOWED"
    assert stale_assertion.get("observed") == "REJECTED"
    assert "expired in 1970" in stale_assertion.get("error", "")

    # Check execution_graph_node events
    node_events = [
        e for e in trace_events if isinstance(e, dict) and e.get("event") == "execution_graph_node"
    ]
    assert len(node_events) >= 2  # running, then failed
    running_node = next((n for n in node_events if n.get("status") == "running"), None)
    assert running_node is not None
    assert running_node.get("scenario_node_id") == "step_transfer_funds"

    failed_node = next((n for n in node_events if n.get("status") == "failed"), None)
    assert failed_node is not None
    assert failed_node.get("failure_class") == "APPROVAL_SECURITY_REJECTED"
    assert any(
        isinstance(o, dict) and o.get("oracle_id") == "security:approval_stale"
        for o in failed_node.get("oracle_results", [])
    )

    # 3. Evidence graph reconstruction must yield total_nodes >= 1
    raw_tuples = [(e, json.dumps(e)) for e in trace_events if isinstance(e, dict)]
    ev_graph = build_evidence_graph_from_events(raw_tuples)
    assert ev_graph.get("total_nodes", 0) >= 1
    assert ev_graph.get("evidence_root_hash") is not None

    # 4. Attestation of Non-Certification must succeed without DecisionOnlyTrace
    cert_res = execute_industrial_certification(
        run_id=run_id,
        run_store=store,
        identity_id="system_id",
    )
    assert cert_res["status"] == "attested_failed"
    assert cert_res["certified"] is False
    assert cert_res["compliance_status"] == "fail"
    assert "manifest" in cert_res
    assert "verification_package" in cert_res
    assert cert_res["verification_package"] is not None


def test_security_preflight_approval_mismatch_typed_evidence(test_env):
    store, _, _ = test_env
    run_id = "run-preflight-mismatch-002"

    scenario = {
        "id": "scenario_mismatch_approval_test",
        "version": "1.0.0",
        "execution_mode": "live",
        "failure_policy": "fail_fast",
        "workflow": {
            "nodes": [
                {
                    "id": "step_payout",
                    "task_description": "Execute payout with wrong transaction binding",
                    "approval_transaction_id": "TX_MISMATCH_DIFFERENT_PAYMENT",
                    "expected_outcome": [{"target": "state", "property": "ok", "expected": True}],
                }
            ],
            "edges": [],
        },
    }

    runner = DefaultRunner(run_store=store)
    result = run_scenario(
        scenario=scenario,
        attempts=1,
        run_id=run_id,
        runner=runner,
        run_store=store,
    )
    assert result.pass_at_k == 0.0

    trace_events = store.get_events(run_id, offset=0, limit=10_000)
    assertion_events = [
        e for e in trace_events if isinstance(e, dict) and e.get("event") == "assertion_evaluated"
    ]
    mismatch_assertion = next(
        (a for a in assertion_events if a.get("oracle_id") == "security:approval_mismatch"), None
    )
    assert mismatch_assertion is not None
    assert mismatch_assertion["outcome"] == "FAIL"

    cert_res = execute_industrial_certification(
        run_id=run_id,
        run_store=store,
        identity_id="system_id",
    )
    assert cert_res["status"] == "attested_failed"


def test_security_preflight_approval_revocation_typed_evidence(test_env):
    store, _, _ = test_env
    run_id = "run-preflight-revocation-003"

    scenario = {
        "id": "scenario_revocation_approval_test",
        "version": "1.0.0",
        "execution_mode": "live",
        "failure_policy": "fail_fast",
        "workflow": {
            "nodes": [
                {
                    "id": "step_settle",
                    "task_description": "Execute settlement with revoked approval token",
                    "approval_revocation": True,
                    "expected_outcome": [{"target": "state", "property": "ok", "expected": True}],
                }
            ],
            "edges": [],
        },
    }

    runner = DefaultRunner(run_store=store)
    result = run_scenario(
        scenario=scenario,
        attempts=1,
        run_id=run_id,
        runner=runner,
        run_store=store,
    )
    assert result.pass_at_k == 0.0

    trace_events = store.get_events(run_id, offset=0, limit=10_000)
    assertion_events = [
        e for e in trace_events if isinstance(e, dict) and e.get("event") == "assertion_evaluated"
    ]
    revocation_assertion = next(
        (a for a in assertion_events if a.get("oracle_id") == "security:approval_revocation"), None
    )
    assert revocation_assertion is not None
    assert revocation_assertion["outcome"] == "FAIL"

    cert_res = execute_industrial_certification(
        run_id=run_id,
        run_store=store,
        identity_id="system_id",
    )
    assert cert_res["status"] == "attested_failed"


def test_security_preflight_preserves_required_scenario_oracles(test_env):
    store, _, _ = test_env
    run_id = "run-preflight-required-oracles-004"

    scenario = {
        "id": "scenario_required_oracles_security_test",
        "version": "1.0.0",
        "execution_mode": "live",
        "workflow": {
            "nodes": [
                {
                    "id": "step_escrow",
                    "task_description": "Release escrow funds",
                    "approval_token": "EXPIRED_SIG_1970",
                    "expected_outcome": [
                        {
                            "oracle_id": "oracle:escrow_verified",
                            "target": "state",
                            "property": "ok",
                            "expected": True,
                            "required": True,
                        }
                    ],
                }
            ],
            "edges": [],
        },
    }

    runner = DefaultRunner(run_store=store)
    result = run_scenario(
        scenario=scenario,
        attempts=1,
        run_id=run_id,
        runner=runner,
        run_store=store,
    )
    assert result.pass_at_k == 0.0

    trace_events = store.get_events(run_id, offset=0, limit=10_000)
    assertion_events = [
        e for e in trace_events if isinstance(e, dict) and e.get("event") == "assertion_evaluated"
    ]
    oracle_ids = [a.get("oracle_id") for a in assertion_events]
    assert "security:approval_stale" in oracle_ids
    assert "oracle:escrow_verified" in oracle_ids

    escrow_assertion = next(
        (a for a in assertion_events if a.get("oracle_id") == "oracle:escrow_verified"), None
    )
    assert escrow_assertion is not None
    assert escrow_assertion["outcome"] == "FAIL"

    cert_res = execute_industrial_certification(
        run_id=run_id,
        run_store=store,
        identity_id="system_id",
    )
    assert cert_res["status"] == "attested_failed"
