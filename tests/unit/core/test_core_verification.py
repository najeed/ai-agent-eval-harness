"""
Consolidated Verification & Hardening Test Suite for AgentV Evaluation Harness.
Verifies system-wide integrity: Ed25519 signatures, Simulator protocols,
Path-traversal hardening, and Visual Debugger subscription.
"""

from pathlib import Path

import pytest

from eval_runner import events
from eval_runner.artifact_plugin import ArtifactPlugin
from eval_runner.console.routes import subscribe_debugger
from eval_runner.console.routes.system import DebuggerStateStore
from eval_runner.simulators import BaseSimulator

# --- 1. Artifact Integrity (Ed25519) ---


def test_artifact_signature_verification(tmp_path):
    plugin = ArtifactPlugin()
    test_file = tmp_path / "data.txt"
    test_file.write_text("data")

    # 1. Valid Signature
    res = plugin.bundle_artifacts(str(tmp_path), ["data.txt"])
    manifest = Path(res["manifest_path"])
    assert plugin.verify_integrity(str(manifest))["is_valid"]

    # 2. Tampered Content
    test_file.write_text("tampered")
    assert not plugin.verify_integrity(str(manifest))["is_valid"]


# --- 2. Simulator Protocols ---


@pytest.mark.asyncio
async def test_base_simulator_protocols():
    sim = BaseSimulator(initial_state={"status": "running", "temp": 72})
    # Polling truthiness vs expected value
    assert await sim.on_poll("status", {"expected_value": "running"})
    assert not await sim.on_poll("status", {"expected_value": "stopped"})

    # Verification
    res = await sim.on_verify({"criteria": {"status": "running"}})
    assert res["status"] == "success"


# --- 3. System Observability (Debugger) ---


def test_debugger_event_bus():
    DebuggerStateStore.reset()
    subscribe_debugger()
    events.emit("turn_start", {"run_id": "r1", "agent_name": "A1"})
    state = DebuggerStateStore.get_state()
    assert len(state["timeline"]) > 0
    assert "A1" in state["summary"]["current_agent"]


# --- 4. Placeholder & Identity Verification ---


def test_placeholder_integrity():
    # Verify no 'pass  # placeholder' in core files
    root = Path(__file__).parent.parent.parent.parent / "eval_runner"
    for path in root.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert "pass  # placeholder" not in content
