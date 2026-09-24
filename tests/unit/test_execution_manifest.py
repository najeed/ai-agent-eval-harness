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


def test_execution_manifest_rejects_unknown_physical_fields():
    manifest = ExecutionManifest(
        manifest_id="m-closed", scenario_id="s", scenario_version="1", scenario_hash="sha3_256:x"
    ).to_dict()
    manifest["unbound_execution_override"] = "unsafe"
    with pytest.raises(ValueError, match="ExecutionManifestUnknownFields"):
        ExecutionManifest.from_dict(manifest)


def test_execution_manifest_rich_provenance_support():
    """
    Validates that ExecutionManifest reliably captures and preserves the full
    provenance specification across agent, model, tool, prompt, and environment.
    """
    manifest = ExecutionManifest(
        manifest_id="man_rich_prov_001",
        scenario_id="scen_healthcare_triage",
        scenario_version="2.1.0",
        scenario_hash="sha3_256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        agent_config={
            "agent_id": "triage_agent",
            "version": "1.4.2",
            "source_commit": "a1b2c3d4e5f6",
            "model_provider": "anthropic",
            "model": "claude-3-5-sonnet",
            "configured_model_id": "claude-3-5-sonnet",
            "framework": "langchain",
            "framework_version": "0.3.0",
            "adapter_version": "2.0.0",
            "tool_versions": {"patient_db": "1.2.0", "vital_signs": "2.0.1"},
            "prompt_revision": "sha3_256:prompt123",
            "config_revision": "sha3_256:config123",
        },
        runtime_config={
            "execution_mode": "live",
            "attempts": 1,
            "seed": 42,
            "runtime_version": "2.0.0",
            "scenario_hash": (
                "sha3_256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            ),
            "policy_hash": "sha3_256:policy123",
            "oracle_hash": "sha3_256:oracle123",
        },
        environment={
            "platform": "linux",
            "python_version": "3.12.2",
            "hostname": "eval-runner-01",
            "runtime_version": "2.0.0",
            "environment_fingerprint": "sha3_256:envfp123",
        },
    )

    manifest_dict = manifest.to_dict()
    restored = ExecutionManifest.from_dict(manifest_dict)

    assert restored.agent_config["source_commit"] == "a1b2c3d4e5f6"
    assert restored.agent_config["model_provider"] == "anthropic"
    assert restored.agent_config["tool_versions"]["patient_db"] == "1.2.0"
    assert restored.runtime_config["policy_hash"] == "sha3_256:policy123"
    assert restored.environment["environment_fingerprint"] == "sha3_256:envfp123"
    assert restored.compute_manifest_hash() == manifest.compute_manifest_hash()
