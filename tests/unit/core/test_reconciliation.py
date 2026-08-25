"""
E4: LIVE/HYBRID reconciliation records.

build_reconciliation_record() commits to the exact before/after state
snapshots and reconciles every declared expected_state_changes entry against
the observed post-state. No inference: missing paths are mismatches, and an
empty expectation set yields reconciled=False (nothing to reconcile is not a
pass).
"""

import pytest

from eval_runner.reconciliation import build_reconciliation_record


def test_matching_expectations_reconcile():
    before = {"balance": 100}
    after = {"balance": 50, "plan": "Premium"}
    rec = build_reconciliation_record(
        node_id="n1",
        execution_mode="live",
        state_before=before,
        state_after=after,
        expected_state_changes=[{"path": "balance", "value": 50}],
        observations={"used_tools": ["withdraw"]},
    )
    assert rec["reconciled"] is True
    assert rec["expected_change_checks"] == [
        {"path": "balance", "expected": 50, "actual": 50, "matched": True}
    ]
    assert rec["observations"] == {"used_tools": ["withdraw"]}
    assert rec["execution_mode"] == "live"


def test_mismatched_or_missing_paths_do_not_reconcile():
    rec = build_reconciliation_record(
        node_id="n1",
        execution_mode="hybrid",
        state_before={},
        state_after={"other": 1},
        expected_state_changes=[{"path": "missing.path", "value": 7}],
    )
    assert rec["reconciled"] is False
    assert rec["expected_change_checks"][0]["matched"] is False
    assert rec["expected_change_checks"][0]["actual"] is None


def test_empty_expectations_are_not_a_pass():
    rec = build_reconciliation_record(
        node_id="n1",
        execution_mode="live",
        state_before={"a": 1},
        state_after={"a": 2},
        expected_state_changes=[],
    )
    assert rec["reconciled"] is False


def test_state_hashes_commit_to_exact_snapshots():
    a = build_reconciliation_record(
        node_id="n", execution_mode="live", state_before={"x": 1}, state_after={"x": 2}
    )
    b = build_reconciliation_record(
        node_id="n", execution_mode="live", state_before={"x": 1}, state_after={"x": 3}
    )
    c = build_reconciliation_record(
        node_id="n", execution_mode="live", state_before={"x": 1}, state_after={"x": 2}
    )
    assert a["state_hash_before"] == b["state_hash_before"]
    assert a["state_hash_after"] != b["state_hash_after"]
    assert a["state_hash_after"] == c["state_hash_after"]
    assert all(h.startswith("sha3_256:") for h in (a["state_hash_before"], a["state_hash_after"]))


def test_missing_snapshots_report_none_not_zero():
    rec = build_reconciliation_record(
        node_id="n", execution_mode="live", state_before=None, state_after=None
    )
    assert rec["state_hash_before"] is None
    assert rec["state_hash_after"] is None


@pytest.mark.parametrize("mode", ["live", "hybrid"])
def test_mode_is_recorded_verbatim(mode):
    rec = build_reconciliation_record(
        node_id="n", execution_mode=mode, state_before={}, state_after={}
    )
    assert rec["execution_mode"] == mode
