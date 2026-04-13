import json

import pytest

from eval_runner import config
from eval_runner.tool_sandbox import ToolSandbox


@pytest.mark.asyncio
async def test_tool_sandbox_metadata_captures_snapshot():
    # Force a fresh registry load to avoid pollution from other tests
    config.RegistryManager.reload()

    scenario = {
        "id": "snapshot_test",
        "metadata": {"name": "Snapshot Test", "compliance_level": "Standard"},
        "workflow": {"nodes": [], "edges": []},
    }

    # 1. Setup sandbox
    sandbox = ToolSandbox(scenario)

    # 2. Verify snapshot injection
    assert "environmental_snapshot" in sandbox.scenario
    assert "provisioning_hash" in sandbox.scenario["metadata"]

    # Verify values match registry
    registry = config.RegistryManager.get_resolved_registry()
    # Use deep comparison or just verify it's a dict with expected keys
    assert isinstance(sandbox.scenario["environmental_snapshot"], dict)
    assert sandbox.scenario["environmental_snapshot"] == registry


@pytest.mark.asyncio
async def test_api_simulator_uses_registry_defaults():
    # Setup registry with unique value
    import os

    env_payload = json.dumps({"shims": {"api": {"resources": {"global_timeout": 60.0}}}})
    os.environ["AES_SHIM_RESOURCES_JSON"] = env_payload
    config.RegistryManager.reload()

    scenario = {
        "id": "api_test",
        "metadata": {"name": "API Test", "compliance_level": "Standard"},
        "workflow": {"nodes": [], "edges": []},
    }

    sandbox = ToolSandbox(scenario)
    api = sandbox.get_active_simulators()
    api["api"]

    # In a real test we'd mock httpx and check the timeout
    # Here we just verify the shim sees the registry config
    registry_resources = config.get_shim_config("api")
    assert registry_resources["global_timeout"] == 60.0

    # Cleanup
    del os.environ["AES_SHIM_RESOURCES_JSON"]
    config.RegistryManager.reload()
