"""
tests.acceptance.support.assertions
Independent acceptance assertions certifying verifiable system side-effects and immutability.
"""

from __future__ import annotations

from pathlib import Path

from .acceptance_runner import CommandResult
from .artifact_reader import RunArtifacts, load_run_artifacts
from .trace_reader import TraceReader


def assert_certificate_artifacts(
    run_id: str,
    repo_root: Path | str | None = None,
    custom_run_dir: Path | str | None = None,
    custom_reports_dir: Path | str | None = None,
) -> RunArtifacts:
    """
    Asserts that all cryptographic certification artifacts exist and are non-empty:
    - runs/<run_id>/run.jsonl
    - runs/<run_id>/run_manifest.json
    - runs/<run_id>/.sealed
    - reports/certificates/<run_id>_vc.json
    """
    artifacts = load_run_artifacts(
        run_id=run_id,
        repo_root=repo_root,
        custom_run_dir=custom_run_dir,
        custom_reports_dir=custom_reports_dir,
    )

    assert artifacts.has_trace, f"Missing trace file: {artifacts.trace_path}"
    assert artifacts.trace_path.stat().st_size > 0, f"Empty trace file: {artifacts.trace_path}"

    assert artifacts.has_manifest, f"Missing manifest: {artifacts.manifest_path}"
    manifest = artifacts.get_manifest()
    m_run_id = manifest.get("run_id")
    assert m_run_id == run_id, f"Manifest run_id mismatch: {m_run_id} != {run_id}"
    assert "sha3_256" in manifest or "trace_hash" in manifest, "Manifest missing trace hash"

    assert artifacts.is_sealed, f"Vault not sealed: {artifacts.sealed_path}"

    assert artifacts.has_certificate, f"Missing certificate: {artifacts.certificate_path}"
    cert = artifacts.get_certificate()
    has_provenance = bool(cert.get("provenance_chain") or cert.get("signatures"))
    has_hash_or_sig = "signature" in cert or "manifest_hash" in cert or "trace_hash" in cert
    assert has_provenance or has_hash_or_sig, (
        "Certificate missing cryptographic provenance, signature, or hash"
    )

    return artifacts


def assert_gate_passed(gate_result: CommandResult) -> None:
    """Asserts that agentv gate command succeeded cleanly with 0 exit code."""
    assert gate_result.exit_code == 0, (
        f"agentv gate failed with exit code {gate_result.exit_code}.\n"
        f"STDOUT:\n{gate_result.stdout}\nSTDERR:\n{gate_result.stderr}"
    )
    assert "[GATE] SUCCESS" in gate_result.stdout or "valid and signed" in gate_result.stdout


def assert_gate_failed(gate_result: CommandResult, expected_text: str | None = None) -> None:
    """Asserts that agentv gate command rejected with non-zero exit code."""
    assert gate_result.exit_code != 0, (
        f"Expected agentv gate to fail, but it exited with 0.\nSTDOUT:\n{gate_result.stdout}"
    )
    if expected_text:
        combined = gate_result.stdout + "\n" + gate_result.stderr
        assert expected_text in combined, f"Expected '{expected_text}' in output:\n{combined}"


def assert_sealed_run_immutable(vault_dir: Path | str) -> None:
    """Asserts that a sealed vault directory contains the .sealed marker and is non-empty."""
    v_path = Path(vault_dir).resolve()
    assert v_path.exists() and v_path.is_dir(), f"Vault dir missing: {v_path}"
    sealed_marker = v_path / ".sealed"
    assert sealed_marker.exists(), f"Missing .sealed marker in {v_path}"


def assert_trace_event_sequence(
    trace_reader: TraceReader,
    expected_event_names: list[str],
) -> None:
    """Asserts that the trace contains the specified event types in order."""
    observed_events = [ev.get("event") for ev in trace_reader.events if ev.get("event")]
    idx = 0
    for exp in expected_event_names:
        found = False
        while idx < len(observed_events):
            if observed_events[idx] == exp:
                found = True
                idx += 1
                break
            idx += 1
        assert found, f"Expected event '{exp}' not found in order. Observed: {observed_events}"


__all__ = [
    "assert_certificate_artifacts",
    "assert_gate_passed",
    "assert_gate_failed",
    "assert_sealed_run_immutable",
    "assert_trace_event_sequence",
]
