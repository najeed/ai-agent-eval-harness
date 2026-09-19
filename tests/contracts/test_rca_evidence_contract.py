"""
tests/contracts/test_rca_evidence_contract.py
Contract Test: RCA Failure Summary & Evidence Graph Binding

Validates that the evidence package contract faithfully populates verdict.assertions,
allowing the RCA failure summary and "What failed" / first-divergence view to
identify the failing assertion, causal node, and expected vs actual values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import eval_runner.config as config
from eval_runner.console.routes.evidence import build_verification_package


@pytest.fixture
def run_with_failed_assertion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Sets up a run directory with a failed assertion and returns run_id."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")

    run_id = "run-rca-contract-failed-001"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    trace_path = run_dir / "run.jsonl"
    events: list[dict[str, Any]] = [
        {
            "_seq": 1,
            "event": "run_start",
            "execution_mode": "live",
            "execution_mode_declared": True,
            "timestamp": "2026-09-19T00:00:00Z",
            "data": {
                "metadata": {
                    "execution_mode": "live",
                    "execution_mode_declared": True,
                    "reproducibility_fingerprint": "fp_test_123",
                    "identifier": "target-agent",
                }
            },
        },
        {
            "_seq": 2,
            "event": "tool_call",
            "timestamp": "2026-09-19T00:00:01Z",
            "data": {
                "tool": "execute_query",
                "parameters": {"query": "SELECT balance FROM accounts"},
                "result": {"balance": 100},
            },
        },
        {
            "_seq": 3,
            "event": "run_end",
            "timestamp": "2026-09-19T00:00:02Z",
            "data": {
                "status": "FAILED",
                "duration": 2.5,
                "score": 0.0,
                "assertions": [
                    {
                        "metric": "balance_reconciliation",
                        "assertion": "balance_matches_audit",
                        "node": "node_audit_verify",
                        "node_id": "node_audit_verify",
                        "passed": False,
                        "expected": 200,
                        "actual": 100,
                        "source": "metric",
                        "severity": "required",
                    }
                ],
            },
        },
    ]

    with open(trace_path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

    manifest = {
        "run_id": run_id,
        "execution_mode": "live",
        "execution_mode_declared": True,
        "runtime_config": {"execution_mode": "live"},
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    return run_id


def test_rca_evidence_contract_populates_verdict_assertions(run_with_failed_assertion: str):
    """
    Contract guarantee: build_verification_package MUST populate
    verdict.assertions with the causal node, metric, expected, and actual values.
    """
    package = build_verification_package(run_with_failed_assertion)
    assert package is not None, "Failed to build verification package"

    # 1. Verdict contract check
    verdict = package.get("verdict")
    assert isinstance(verdict, dict), "Package verdict must be a dictionary"
    assert "assertions" in verdict, "verdict.assertions must be populated for RCA"

    verdict_assertions = verdict["assertions"]
    assert isinstance(verdict_assertions, list)
    assert len(verdict_assertions) == 1

    failed_assertion = verdict_assertions[0]
    assert failed_assertion["passed"] is False
    assert failed_assertion["node"] == "node_audit_verify"
    assert failed_assertion["expected"] == 200
    assert failed_assertion["actual"] == 100
    assert failed_assertion["metric"] == "balance_reconciliation"

    # 2. Evidence graph parity check
    evidence_graph = package.get("evidence_graph")
    assert isinstance(evidence_graph, dict), "evidence_graph must be present"
    nodes = evidence_graph.get("nodes", [])
    assert len(nodes) >= 1

    matching_node = next((n for n in nodes if n.get("node") == "node_audit_verify"), None)
    assert matching_node is not None, "Evidence graph must contain the failing node"
    assert matching_node["passed"] is False
    assert matching_node["outcome"] == "FAIL"
    assert matching_node.get("expected") == 200
    assert matching_node.get("actual") == 100
