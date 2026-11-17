"""
tests.unit.core.test_reproducibility
Unit tests for evaluation reproducibility contract and fingerprinting.
"""

from __future__ import annotations

from unittest.mock import patch

from eval_runner.reproducibility import (
    _canonical_hash,
    build_reproducibility_contract,
    fingerprint,
    metric_registry_fingerprint,
)


def test_canonical_hash_deterministic():
    data = {"b": 2, "a": 1}
    h1 = _canonical_hash(data)
    h2 = _canonical_hash({"a": 1, "b": 2})
    assert h1.startswith("sha3_256:")
    assert h1 == h2


def test_build_reproducibility_contract_full():
    scenario = {
        "id": "scen-1",
        "run_id": "ephemeral-run-123",
        "metadata": {"name": "Test Scenario", "model": "gpt-4"},
        "tools": {"t1": {}},
        "initial_state": {"count": 0},
        "workflow": {"nodes": []},
    }
    adapter_meta = {
        "protocol": "local",
        "agent": "agent.py",
        "adapter_version": "1.0",
        "model": "claude-3-5-sonnet",
    }
    contract = build_reproducibility_contract(
        scenario=scenario,
        resolved_config=None,
        seed=42,
        attempts=3,
        execution_mode="live",
        adapter_metadata=adapter_meta,
        evaluator_fingerprint="eval-fp-abc",
        plugin_provenance={"plugin_a": {}},
    )

    assert contract["contract_version"] == "1.1.0"
    assert contract["seed"] == 42
    assert contract["seeding_strategy"] == "base_seed_plus_attempt_index"
    assert contract["attempts_requested"] == 3
    assert contract["execution_mode"] == "live"
    assert contract["scenario_id"] == "scen-1"
    assert contract["adapter"]["protocol"] == "local"
    assert contract["adapter"]["provider_model"] == "claude-3-5-sonnet"
    assert contract["evaluator"]["fingerprint"] == "eval-fp-abc"

    fp = fingerprint(contract)
    assert fp.startswith("sha3_256:")
    contract_with_fp = dict(contract, fingerprint="dummy")
    assert fingerprint(contract_with_fp) == fp


def test_build_reproducibility_contract_minimal_and_none_branches():
    contract = build_reproducibility_contract(
        scenario={},
        resolved_config=None,
        seed=None,
        attempts=1,
        execution_mode=None,
        adapter_metadata=None,
        evaluator_fingerprint=None,
        plugin_provenance=None,
    )

    assert "execution_mode" not in contract
    assert contract["seed"] is None
    assert contract["seeding_strategy"] == "none"
    assert contract["adapter"]["protocol"] is None
    assert contract["adapter"]["provider_model"] is None
    assert contract["evaluator"]["fingerprint"] is None
    assert contract["evaluator"]["plugin_provenance"] == {}


def test_metric_registry_fingerprint_success():
    fp = metric_registry_fingerprint()
    assert fp.startswith("sha3_256:")


def test_metric_registry_fingerprint_exception_handling():
    with patch(
        "eval_runner.metrics.MetricRegistry.list_metrics",
        side_effect=RuntimeError("Metric registry unavailable"),
    ):
        fp = metric_registry_fingerprint()
        assert fp.startswith("sha3_256:")
        assert fp == _canonical_hash([])
