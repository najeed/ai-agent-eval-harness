"""
tests/contracts/test_aes_schema_contract.py
Contract Test: AES v1.4 Scenario Validation Schema

Validates that the industrial scenario schema remains stable across major versions.
Any change to these assertions requires a semver MAJOR bump (v2.x.0 → v3.0.0).
"""

from __future__ import annotations

import json

import pytest
from jsonschema import ValidationError

import eval_runner.config as config
from eval_runner.loader import get_universal_registry, load_scenario, reset_universal_registry

# ─────────────────────────────────────────────────────────────────────────────
# Minimal AES v1.4 compliant scenario structure (public contract)
# ─────────────────────────────────────────────────────────────────────────────

MINIMAL_VALID_SCENARIO = {
    "aes_version": 1.4,
    "metadata": {
        "id": "contract_test_001",
        "name": "Contract Validation Scenario",
        "compliance_level": "Standard",
    },
    "workflow": {
        "nodes": [
            {
                "id": "node_1",
                "task_description": "Perform a basic validation task.",
            }
        ],
        "edges": [],
    },
    "evaluation": {"metrics": []},
}


class TestAESSchemaContract:
    """
    AES Schema Contract Tests.
    These tests verify the mandatory fields and structural invariants of the AES v1.4
    scenario schema. Breaking any structural requirement is a MAJOR version contract violation.
    """

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        reset_universal_registry()
        yield
        reset_universal_registry()

    def test_universal_registry_loads_successfully(self):
        """AES Contract: Universal registry indexes schema definitions without error."""
        registry = get_universal_registry()
        assert registry is not None

    def test_minimal_scenario_passes_validation(self, tmp_path):
        """AES Contract: A scenario with required AES v1.4 fields validates successfully."""
        scen_file = tmp_path / "valid_contract.json"
        scen_file.write_text(json.dumps(MINIMAL_VALID_SCENARIO), encoding="utf-8")
        loaded = load_scenario(scen_file)
        assert loaded["aes_version"] == 1.4
        assert loaded["metadata"]["id"] == "contract_test_001"
        assert len(loaded["workflow"]["nodes"]) == 1

    def test_missing_version_is_rejected(self, tmp_path):
        """AES Contract: Scenario without aes_version must fail validation."""
        scenario = {
            "metadata": {"id": "no_ver", "name": "No Version"},
            "workflow": {"nodes": [{"id": "n1"}], "edges": []},
            "evaluation": {"metrics": []},
        }
        scen_file = tmp_path / "no_ver.json"
        scen_file.write_text(json.dumps(scenario), encoding="utf-8")
        with pytest.raises(ValueError) as cm:
            load_scenario(scen_file)
        assert "Unsupported AES version" in str(cm.value)

    def test_legacy_version_is_rejected(self, tmp_path):
        """AES Contract: Legacy AES versions (1.2, 1.3) must be rejected."""
        scenario = {
            "aes_version": 1.2,
            "metadata": {"id": "legacy_v12", "name": "Legacy Scenario"},
            "workflow": {"nodes": [{"id": "n1"}], "edges": []},
            "evaluation": {"metrics": []},
        }
        scen_file = tmp_path / "legacy.json"
        scen_file.write_text(json.dumps(scenario), encoding="utf-8")
        with pytest.raises(ValueError) as cm:
            load_scenario(scen_file)
        assert "Unsupported AES version: 1.2" in str(cm.value)

    def test_missing_workflow_is_rejected(self, tmp_path):
        """AES Contract: Scenario without 'workflow' must fail validation."""
        scenario = {
            "aes_version": 1.4,
            "metadata": {"id": "no_workflow", "name": "No Workflow"},
            "evaluation": {"metrics": []},
        }
        scen_file = tmp_path / "no_workflow.json"
        scen_file.write_text(json.dumps(scenario), encoding="utf-8")
        with pytest.raises((ValueError, ValidationError, KeyError)):
            load_scenario(scen_file)

    def test_missing_metadata_id_is_rejected(self, tmp_path):
        """AES Contract: Scenario without metadata.id must fail validation."""
        scenario = {
            "aes_version": 1.4,
            "metadata": {"name": "No ID"},
            "workflow": {"nodes": [{"id": "n1"}], "edges": []},
            "evaluation": {"metrics": []},
        }
        scen_file = tmp_path / "no_id.json"
        scen_file.write_text(json.dumps(scenario), encoding="utf-8")
        with pytest.raises((ValidationError, ValueError)):
            load_scenario(scen_file)

    def test_aes_version_constant(self):
        """AES Contract: The AES schema version is pinned at 1.4."""
        assert config.AES_VERSION == 1.4, (
            f"AES schema version drifted to {config.AES_VERSION}. "
            "A change to the schema version requires a MAJOR bump."
        )
