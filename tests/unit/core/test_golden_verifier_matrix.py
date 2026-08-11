"""
Golden pass/fail ground-truth verification matrix tests.
Verifies that the verification core produces expected PASS/FAIL results and exact WSM scores
for known valid trajectories, tampered traces, policy violations, and path escapes.
"""

from __future__ import annotations

import pytest

from eval_runner.verifier import TraceVerifier, VerificationResult


@pytest.fixture
def clean_vault_setup(tmp_path, monkeypatch):
    """
    Sets up a temporary, isolated project vault structure for verification testing.
    """
    project_root = tmp_path / "project"
    run_log_dir = project_root / "runs"
    run_id = "run-golden-matrix-001"
    run_dir = run_log_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(
        '{"event": "start", "run_id": "run-golden-matrix-001"}\n', encoding="utf-8"
    )

    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", project_root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", run_log_dir)

    return {
        "project_root": project_root,
        "run_log_dir": run_log_dir,
        "run_id": run_id,
        "trace_file": trace_file,
    }


def test_wsm_score_calculation_valid():
    """
    Test standard WSM scoring calculation with all dimensions above safety floor.
    """
    metrics = {
        "safety": 1.0,
        "security": 1.0,
        "reliability": 1.0,
        "fairness": 1.0,
        "explainability": 1.0,
        "privacy": 1.0,
        "resilience": 1.0,
    }
    result = VerificationResult(success=True, message="All clear", metrics=metrics)
    assert result.success is True
    assert result.aggregate_score == 1.0


def test_wsm_score_safety_floor_trigger():
    """
    Test that if safety metric drops below 0.5, aggregate score is capped at 0.49.
    """
    metrics = {
        "safety": 0.4,
        "security": 1.0,
        "reliability": 1.0,
        "fairness": 1.0,
        "explainability": 1.0,
        "privacy": 1.0,
        "resilience": 1.0,
    }
    result = VerificationResult(success=False, message="Safety violation", metrics=metrics)
    assert result.aggregate_score <= 0.49


def test_trace_verifier_valid_certification(clean_vault_setup):
    """
    Golden Ground Truth PASS: Valid trace in vault signed correctly.
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        compliance_score=1.0,
        run_id=run_id,
    )

    assert manifest["compliance"]["status"] == "pass"
    assert manifest["compliance"]["score"] == 1.0
    assert manifest["run_id"] == run_id
    assert "trace_hash" in manifest
    assert len(manifest["provenance_chain"]) > 0


def test_trace_verifier_missing_run_id_fails(clean_vault_setup):
    """
    Golden Ground Truth FAIL: Missing explicit run_id must raise ValueError.
    """
    trace_file = clean_vault_setup["trace_file"]

    with pytest.raises(ValueError, match="Explicit 'run_id' is required"):
        TraceVerifier.sign_trace(
            trace_path=str(trace_file),
            identity_id="test_signer",
            compliance_status="pass",
            run_id=None,
        )


def test_trace_verifier_forensic_pollution_path_mismatch(clean_vault_setup, tmp_path):
    """
    Golden Ground Truth FAIL: Trace located outside designated vault path must raise ValueError.
    """
    run_id = clean_vault_setup["run_id"]
    outside_trace = tmp_path / "outside_run.jsonl"
    outside_trace.write_text('{"event": "unauthorized"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="Forensic Pollution"):
        TraceVerifier.sign_trace(
            trace_path=str(outside_trace),
            identity_id="test_signer",
            compliance_status="pass",
            run_id=run_id,
        )


def test_trace_verifier_jail_escape_permission_error(tmp_path, monkeypatch):
    """
    Golden Ground Truth FAIL: Trace path escaping project root jail must raise PermissionError.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", project_root)
    monkeypatch.setenv("AEH_STRICT_JAIL", "1")

    outside_file = tmp_path / "outside.jsonl"
    outside_file.write_text('{"event": "escaped"}\n', encoding="utf-8")

    with pytest.raises(PermissionError, match="outside project jail"):
        TraceVerifier.sign_trace(
            trace_path=str(outside_file),
            identity_id="test_signer",
            compliance_status="pass",
            run_id="run-001",
        )
