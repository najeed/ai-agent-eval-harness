import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dataproc_engine.providers.healthcare import HealthcareProvider
from eval_runner.artifact_plugin import ArtifactPlugin
from eval_runner.console.routes import subscribe_debugger
from eval_runner.console.routes.system import DebuggerStateStore
from eval_runner.simulators import BaseSimulator


@pytest.mark.asyncio
async def test_base_simulator_on_poll_hardened():
    """Verify hardened on_poll logic in BaseSimulator."""
    sim = BaseSimulator(initial_state={"status": "running", "temp": 72, "is_active": True})

    # Test truthiness of state key
    assert await sim.on_poll("is_active", {})

    # Test exact value match
    assert await sim.on_poll("temp", {"expected_value": 72})
    assert not await sim.on_poll("temp", {"expected_value": 100})

    # Priority check: expected_value should take precedence over truthiness
    sim.state["error"] = True  # Truthy
    assert not await sim.on_poll("error", {"expected_value": False})

    # Default to True for unknown keys if no expected_value
    assert await sim.on_poll("unknown", {})


@pytest.mark.asyncio
async def test_base_simulator_on_verify_hardened():
    """Verify hardened on_verify logic in BaseSimulator."""
    sim = BaseSimulator(initial_state={"status": "running", "temp": 72})

    # Success case
    res = await sim.on_verify({"criteria": {"status": "running", "temp": 72}})
    assert res["status"] == "success"

    # Failure case
    res = await sim.on_verify({"criteria": {"status": "stopped"}})
    assert res["status"] == "error"
    assert "expected stopped, got running" in res["message"]

    # Empty criteria
    assert (await sim.on_verify({}))["status"] == "success"


@pytest.mark.asyncio
async def test_artifact_signature_verification_hardened(tmp_path):
    """Verify Ed25519 signature verification in ArtifactPlugin."""
    plugin = ArtifactPlugin()

    # Create test bundle
    test_file = tmp_path / "data.txt"
    test_file.write_text("Hardened Integrity Test")

    bundle_result = plugin.bundle_artifacts(str(tmp_path), ["data.txt"])
    manifest_path = Path(bundle_result["manifest_path"])

    # 1. Initial validity
    assert plugin.verify_integrity(str(manifest_path))["is_valid"]

    # 2. Tamper with signature
    with open(manifest_path) as f:
        manifest = json.load(f)
    manifest["signature_ed25519"] = base64.b64encode(b"invalid_signature").decode()
    with open(manifest_path, "w") as f:
        json.dump(manifest, f)

    assert not plugin.verify_integrity(str(manifest_path))["is_valid"]

    # 3. Tamper with file content
    test_file.write_text("Tampered Content")
    # Resign correctly
    bundle_result = plugin.bundle_artifacts(str(tmp_path), ["data.txt"])
    # Then tamper again without resigning
    test_file.write_text("Post-sign Tamper")

    assert not plugin.verify_integrity(str(manifest_path))["is_valid"]


def test_debugger_subscription_hardened():
    """Verify that Visual Debugger correctly subscribes to the event bus."""
    from eval_runner import events

    # Ensure a fresh state
    DebuggerStateStore.reset()

    # Initial state should be empty
    assert len(DebuggerStateStore._events) == 0

    # Subscribe
    subscribe_debugger()

    # Emit a core event
    test_event_data = {"run_id": "test-run-123", "agent_name": "HardenedAgent"}
    events.emit("turn_start", test_event_data)

    # Verify the state store captured it
    state = DebuggerStateStore.get_state()
    assert len(state["timeline"]) > 0
    assert state["summary"]["current_agent"] == "Agent HardenedAgent"


@pytest.mark.asyncio
async def test_healthcare_path_resolution_hardened(tmp_path):
    """Verify hardened path resolution in HealthcareProvider."""
    # Setup real file
    real_csv = tmp_path / "real_data.csv"
    real_csv.write_text("Hospital Name,Provider ID\nHospital A,001")

    # Case 1: Real path + Non-existent path with simulation allowed
    provider = HealthcareProvider(
        config={"input_uris": [str(real_csv), "non_existent.csv"], "allow_simulation": True}
    )

    with patch.object(provider, "load_raw_data"):
        # Mocking extraction logic if needed, but HealthcareProvider.extract
        # calls fetch_csv which checks os.path.exists

        # We need to mock pd.read_csv or ensure HealthcareProvider can run

        artifacts = await provider.extract()

        # Should have 2 artifacts: one from real file, one simulated
        assert len(artifacts) == 2
        assert artifacts[0].source_url == str(real_csv)
        assert "sim_non_existent.csv" in artifacts[1].source_url

    # Case 2: No valid paths, no simulation
    provider_no_sim = HealthcareProvider(
        config={"input_uris": ["broken.csv"], "allow_simulation": False}
    )

    artifacts = await provider_no_sim.extract()
    assert len(artifacts) == 0
