from pathlib import Path

import pytest

from eval_runner.tool_sandbox import ToolSandbox


@pytest.mark.asyncio
async def test_resource_registry_cleanup():
    # Setup
    scenario = {"scenario_id": "test_cleanup", "initial_state": {}}
    sandbox = ToolSandbox(scenario)

    # Create transient artifacts
    temp_file = Path("test_artifact.db")
    temp_file.write_text("dummy data")

    temp_dir = Path("test_artifact_dir")
    temp_dir.mkdir(exist_ok=True)
    (temp_dir / "child.txt").write_text("child data")

    assert temp_file.exists()
    assert temp_dir.exists()

    # Register with sandbox
    sandbox.register_artifact(temp_file)
    sandbox.register_artifact(temp_dir)

    # Execute teardown
    await sandbox.teardown()

    # Verify cleanup
    assert not temp_file.exists(), "File should have been unlinked"
    assert not temp_dir.exists(), "Directory should have been rmtree'd"


@pytest.mark.asyncio
async def test_resource_registry_audit_proxy():
    # Setup with a mock forensics object
    class MockForensics:
        def __init__(self):
            self.registered = []

        def register_artifact(self, path, alias):
            self.registered.append((path, alias))

    mock_forensics = MockForensics()
    scenario = {"scenario_id": "test_proxy", "initial_state": {}}
    sandbox = ToolSandbox(scenario, forensics=mock_forensics)

    # Create and register
    temp_file = Path("test_proxy.db")
    temp_file.write_text("data")

    sandbox.register_artifact(temp_file, alias="my_db")

    # Verify proxy to forensics
    assert len(mock_forensics.registered) == 1
    assert mock_forensics.registered[0][1] == "my_db"

    # Cleanup
    await sandbox.teardown()
    assert not temp_file.exists()
