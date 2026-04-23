import json

import pytest

from eval_runner.loader import load_scenario, reset_universal_registry


@pytest.fixture(autouse=True)
def cleanup_loader():
    reset_universal_registry()
    yield


def test_loader_rejects_missing_version(tmp_path):
    """Verify that scenarios without aes_version are rejected with clear error."""
    scen_path = tmp_path / "legacy.json"
    content = {"id": "legacy-v1", "workflow": {"nodes": [{"id": "t1"}], "edges": []}}
    scen_path.write_text(json.dumps(content))

    with pytest.raises(ValueError) as cm:
        load_scenario(scen_path)
    assert "Unsupported AES version: missing" in str(cm.value)


def test_loader_rejects_legacy_version(tmp_path):
    """Verify that scenarios with legacy aes_version (v1.2) are rejected."""
    scen_path = tmp_path / "v12.json"
    content = {
        "aes_version": 1.2,
        "id": "legacy-v12",
        "workflow": {"nodes": [{"id": "t1"}], "edges": []},
    }
    scen_path.write_text(json.dumps(content))

    with pytest.raises(ValueError) as cm:
        load_scenario(scen_path)
    assert "Unsupported AES version: 1.2" in str(cm.value)


def test_loader_accepts_v14_minimal(tmp_path):
    """Verify that a minimal valid AES v1.4.0 scenario is accepted."""
    scen_path = tmp_path / "valid.json"
    content = {
        "aes_version": 1.4,
        "metadata": {"id": "valid-v14", "name": "Valid Scenario", "compliance_level": "Standard"},
        "workflow": {"nodes": [{"id": "task-1", "task_description": "First task"}], "edges": []},
        "evaluation": {"metrics": []},
    }
    scen_path.write_text(json.dumps(content))

    loaded = load_scenario(scen_path)
    assert loaded["aes_version"] == 1.4
    assert loaded["metadata"]["id"] == "valid-v14"
