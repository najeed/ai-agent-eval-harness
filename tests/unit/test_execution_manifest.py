"""
tests/unit/test_execution_manifest.py
Unit tests for the authoritative ExecutionManifest contract (AgentV v2.0.0).
"""

from dataclasses import FrozenInstanceError

import pytest

from agentv_runtime.manifest import ExecutionManifest, ManifestBuilder, compute_scenario_hash


def test_compute_scenario_hash_deterministic():
    scenario_a = {
        "metadata": {"id": "scen_loan_approval", "version": "1.2.0"},
        "workflow": {"nodes": [{"id": "node_1", "task": "verify_identity"}]},
        "industry": "fintech",
    }
    scenario_b = {
        "industry": "fintech",
        "workflow": {"nodes": [{"id": "node_1", "task": "verify_identity"}]},
        "metadata": {"version": "1.2.0", "id": "scen_loan_approval"},
    }

    hash_a = compute_scenario_hash(scenario_a)
    hash_b = compute_scenario_hash(scenario_b)

    assert hash_a.startswith("sha3_256:")
    assert hash_a == hash_b


def test_manifest_builder_and_immutability():
    scenario = {
        "metadata": {"id": "sec_eval_01", "version": "2.0.0"},
        "industry": "cybersecurity",
    }
    agent_config = {
        "agent_name": "agent_alpha",
        "protocol": "http_rest",
        "endpoint": "http://localhost:8000",
    }
    runtime_config = {
        "max_turns": 15,
        "signing_backend": "ed25519",
    }

    manifest = ManifestBuilder.build(
        scenario_data=scenario,
        agent_config=agent_config,
        runtime_config=runtime_config,
        created_by="user_auditor_01",
    )

    assert isinstance(manifest, ExecutionManifest)
    assert manifest.scenario_id == "sec_eval_01"
    assert manifest.scenario_version == "2.0.0"
    assert manifest.created_by == "user_auditor_01"
    assert manifest.agent_config["agent_name"] == "agent_alpha"
    assert manifest.manifest_id.startswith("man_")

    # Verify frozen immutability
    with pytest.raises(FrozenInstanceError):
        manifest.scenario_id = "mutated_id"  # type: ignore

    # Roundtrip serialization
    manifest_dict = manifest.to_dict()
    restored = ExecutionManifest.from_dict(manifest_dict)
    assert restored == manifest
    assert restored.compute_manifest_hash() == manifest.compute_manifest_hash()
