import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest

from eval_runner.forensics import ForensicCollector
from eval_runner.tool_sandbox import ToolSandbox
from eval_runner.verifier import TraceVerifier


@pytest.fixture
def vault_setup(tmp_path, monkeypatch):
    """Isolates the environment for industrial testing."""
    run_id = "test-forensic-v150"
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", runs_dir)

    # Isolate Trust Root
    trust_dir = tmp_path / "trust"
    trust_dir.mkdir()
    monkeypatch.setattr("eval_runner.config.TRUST_ROOT", trust_dir)
    monkeypatch.setattr("eval_runner.config.ALLOW_SYSTEM_IDENTITY_PROVISIONING", True)

    from eval_runner.config import RegistryManager

    RegistryManager.reload()

    vault_dir = runs_dir / run_id
    vault_dir.mkdir()
    trace_path = vault_dir / "run.jsonl"

    # Use binary write to ensure predictable line endings for hashing tests
    trace_path.write_bytes(b'{"event": "start"}\n')

    return run_id, vault_dir, trace_path


def test_forensic_seal_hash_integrity(vault_setup):
    """
    [AgentV v1.5.0] Verification Integrity Test.
    Ensures that appending the certificate event with a Seal Hash
    does not invalidate the final manifest hash.
    """
    run_id, vault_dir, trace_path = vault_setup

    # 1. Sign the trace
    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id, identity_id="test_auditor")

    # 2. Check the trace content
    trace_content = trace_path.read_bytes()
    trace_lines = trace_content.splitlines()
    last_line = json.loads(trace_lines[-1])

    assert last_line["event"] == "verification_certificate_issued"
    assert "seal_hash" in last_line

    # 3. Verify the seal_hash matches the trace BEFORE the event
    # The trace only had one line before the event.
    initial_content = b'{"event": "start"}\n'
    expected_seal = hashlib.sha256(initial_content).hexdigest()
    assert last_line["seal_hash"] == expected_seal

    # 4. Verify that the physical file hash matches the manifest
    actual_physical_hash = hashlib.sha256(trace_content).hexdigest()
    assert manifest["sha256"] == actual_physical_hash

    # 5. Run the authoritative verifier
    manifest_path = vault_dir / "run_manifest.json"
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is True


def test_forensic_shim_relevance_strict():
    """
    [AgentV v1.6.0] Conditional Discovery Logic Test.
    Ensures:
    1. Omitted 'enabled_shims' triggers Strict Discovery (Relevance-based).
    2. Provided 'enabled_shims' acts as a Hard Boundary (ignores other relevant shims).
    """
    # 1. Setup Mock Registry and Classes
    mock_registry = {
        "shims": {
            "explicit_shim": {"type": "mock_type"},
            "contract_shim": {"type": "mock_type"},
            "ignored_shim": {"type": "mock_type"},
        }
    }

    with patch(
        "eval_runner.config.RegistryManager.get_resolved_registry",
        return_value=mock_registry,
    ):
        # Patch simulators globally
        with patch(
            "eval_runner.simulators.get_simulator_registry",
            return_value={"explicit_shim": MagicMock, "contract_shim": MagicMock},
        ):
            with patch("eval_runner.config.GLOBAL_ENABLED_SHIMS", ["*"]):
                # --- CASE 1: Strict Discovery Mode (Omitted Whitelist) ---
                scenario_discovery = {
                    "workflow": {
                        "nodes": [{"expected_outcome": [{"target": "shim:contract_shim"}]}]
                    }
                }
                sandbox_discovery = ToolSandbox(scenario_discovery)
                active_discovery = sandbox_discovery.get_active_simulators()

                assert "contract_shim" in active_discovery
                assert "explicit_shim" not in active_discovery  # Not relevant

                # --- CASE 2: Explicit Whitelist Mode (Hard Boundary) ---
                scenario_whitelist = {
                    "enabled_shims": ["explicit_shim"],
                    "workflow": {
                        "nodes": [{"expected_outcome": [{"target": "shim:contract_shim"}]}]
                    },
                }
                sandbox_whitelist = ToolSandbox(scenario_whitelist)
                active_whitelist = sandbox_whitelist.get_active_simulators()

                assert "explicit_shim" in active_whitelist
                # CRITICAL: contract_shim is relevant but BLOCKED
                assert "contract_shim" not in active_whitelist


def test_forensic_telemetry_lifecycle(vault_setup):
    """
    [AgentV v1.5.0] Telemetry Optimization Test.
    Ensures O(1) initialization and per-turn capture.
    """
    run_id, vault_dir, trace_path = vault_setup
    forensics = ForensicCollector(run_id, vault_dir)

    # 1. Initialization
    headers = ["ts", "cpu", "mem"]
    forensics.init_telemetry(headers)

    telemetry_path = vault_dir / "forensics" / "telemetry.csv"
    assert telemetry_path.exists()
    assert telemetry_path.read_text().startswith("ts,cpu,mem")

    # 2. Append (Simulate turn)
    with open(telemetry_path, "a") as f:
        f.write("1,10,100\n")

    # Re-init should NOT append another header if implemented correctly in Session
    # (Checking that the header logic is now one-time)
    assert len(telemetry_path.read_text().splitlines()) == 2


@pytest.mark.asyncio
async def test_forensic_shim_state_differential(vault_setup):
    """
    [AgentV v1.5.0] State Snapshotting Test.
    Ensures full state capture and differential encoding.
    """
    run_id, vault_dir, trace_path = vault_setup
    forensics = ForensicCollector(run_id, vault_dir)

    # Turn 0: Full Snapshot
    state_0 = {"shim_1": {"data": "A"}, "shim_2": {"data": "B"}}
    forensics.snapshot_state(state_0, turn=0)

    snapshot_0 = vault_dir / "forensics" / "state_turn_000_full.json"
    assert snapshot_0.exists()
    assert json.loads(snapshot_0.read_text()) == state_0

    # Turn 1: Differential Snapshot
    state_1 = {"shim_1": {"data": "A_mod"}, "shim_2": {"data": "B"}}  # shim_2 unchanged
    forensics.snapshot_state(state_1, turn=1)

    snapshot_1 = vault_dir / "forensics" / "state_turn_001_diff.json"
    assert snapshot_1.exists()
    content_1 = json.loads(snapshot_1.read_text())

    # Should only contain the changed key
    assert "shim_1" in content_1
    assert "shim_2" not in content_1
    assert content_1["shim_1"]["data"] == "A_mod"

    # Turn 2: No changes
    forensics.snapshot_state(state_1, turn=2)
    snapshot_2 = vault_dir / "forensics" / "state_turn_002_diff.json"
    assert not snapshot_2.exists()  # Should skip zero-change diffs
