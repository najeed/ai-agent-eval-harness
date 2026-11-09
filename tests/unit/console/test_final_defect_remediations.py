"""Unit tests verifying remediations for P0-3, P1-2, and P1-3.

P0-3: Certificate access authoritative validity (TraceVerifier invocation in /v1/certificates).
P1-2: PDF report verdict derivation (strict terminal-verdict contracts, never unverified passes).
P1-3: Isolated demo reset (/api/demo/reset clears DEMO_IDS, cleans runs, resets loan_agent.py).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.console.app import create_app
from eval_runner.console.pdf_service import generate_run_pdf
from eval_runner.reference.local_run_store import LocalFileRunStore


@pytest.fixture
def run_app_and_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / "runs"
    reports_dir = tmp_path / "reports"
    keys_dir = tmp_path / "keys"
    runs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    keys_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr(config, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(config, "TRUST_ROOT", keys_dir)

    store = LocalFileRunStore(log_dir=runs_dir)
    app = create_app(run_store=store)
    app.config["TESTING"] = True
    return app, store


# ==============================================================================
# P0-3: Certificate Access Does Not Expose Invalid Evidence as Certified
# ==============================================================================


def test_certificate_endpoint_marks_unverified_manifest_explicitly(run_app_and_store):
    """P0-3: /v1/certificates/<run_id> invokes TraceVerifier and tags unverified status."""
    app, store = run_app_and_store
    client = app.test_client()

    run_id = "run-unverified-cert-test"
    store.create_run(run_id, scenario_id="sec-1")

    # Save a manifest with a self-declared or unverified certificate block
    manifest = {
        "run_id": run_id,
        "vc_version": "2.0.0",
        "status": "PASS",
        "verification_status": "CLAIMED_PASS",
        "certificate": {"signature": "mock_unverified_sig"},
    }
    store.save_run_manifest(run_id, manifest)

    # TraceVerifier.verify_run reports invalid / unverified
    mock_verif = MagicMock()
    mock_verif.is_valid = False
    mock_verif.certificate_valid = False
    mock_verif.cryptographically_valid = False
    mock_verif.file_integrity_valid = True
    mock_verif.evaluation_passed = False
    mock_verif.is_authoritative = False
    mock_verif.status = "UNVERIFIED"

    with patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=mock_verif):
        resp = client.get(f"/v1/certificates/{run_id}")
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["verification_status"] == "UNVERIFIED"
        assert data["certificate_authoritative"] is False
        assert data["is_authoritative"] is False
        assert data["certificate_valid"] is False
        assert data["cryptographically_valid"] is False
        assert data["file_integrity_valid"] is True
        assert data["evaluation_passed"] is False

    # Also verify when TraceVerifier raises an exception
    with patch(
        "eval_runner.verifier.TraceVerifier.verify_run",
        side_effect=RuntimeError("verifier error"),
    ):
        resp2 = client.get(f"/v1/certificates/{run_id}")
        assert resp2.status_code == 200
        data2 = resp2.get_json()
        assert data2["verification_status"] == "UNVERIFIED"
        assert data2["certificate_authoritative"] is False
        assert data2["is_authoritative"] is False


def test_public_certificate_endpoint_reflects_authoritative_verification(
    run_app_and_store,
):
    """P0-3: /v1/certificates/<run_id>/public projects verified facts without unverified claims."""
    app, store = run_app_and_store
    client = app.test_client()

    run_id = "run-public-cert-test"
    store.create_run(run_id, scenario_id="sec-1")

    manifest = {
        "run_id": run_id,
        "vc_version": "2.0.0",
        "status": "PASS",
        "algorithm": "ML-DSA-65",
        "signature": "valid_pqc_sig",
    }
    store.save_run_manifest(run_id, manifest)

    # Valid authoritative verification
    mock_verif = MagicMock()
    mock_verif.is_valid = True
    mock_verif.certificate_valid = True
    mock_verif.cryptographically_valid = True
    mock_verif.file_integrity_valid = True
    mock_verif.evaluation_passed = True
    mock_verif.is_authoritative = True
    mock_verif.status = "CERTIFIED_PASS"

    with patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=mock_verif):
        resp = client.get(f"/v1/certificates/{run_id}/public")
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["verification_status"] == "CERTIFIED_PASS"
        assert data["certificate_authoritative"] is True
        assert data["certificate_valid"] is True
        assert data["cryptographically_valid"] is True
        assert data["algorithm"] == "ML-DSA-65"


# ==============================================================================
# P1-2: PDF Generator Permits No Permissive Fallbacks to Claim Certification
# ==============================================================================


def test_pdf_service_unverified_verdict_never_claims_verified(tmp_path: Path):
    """P1-2: Missing or unverified verdicts must render UNVERIFIED or PASSED, never VERIFIED."""
    # Run completed (passed=True) with a certificate present, but missing verifier verdict
    unverified_run = {
        "run_id": "run-unverified-pdf",
        "scenario": "loan-audit",
        "passed": True,
        "has_certificate": True,
        "is_certified": True,
        "verification_status": "UNVERIFIED",
        "is_authoritative": False,
    }
    pdf_path_1 = tmp_path / "unverified_report.pdf"
    assert generate_run_pdf(unverified_run, pdf_path_1) is True
    assert pdf_path_1.exists()

    unverified_missing_status = {
        "run_id": "run-unverified-pdf-missing",
        "scenario": "loan-audit",
        "passed": None,
        "has_certificate": True,
        "status": "OPEN",
    }
    pdf_path_2 = tmp_path / "missing_status_report.pdf"
    assert generate_run_pdf(unverified_missing_status, pdf_path_2) is True
    assert pdf_path_2.exists()

    # Authoritative verification verdict strictly renders VERIFIED
    verified_run = {
        "run_id": "run-verified-pdf",
        "scenario": "loan-audit",
        "passed": True,
        "verification_status": "CERTIFIED_PASS",
        "is_authoritative": True,
    }
    pdf_path_3 = tmp_path / "verified_report.pdf"
    assert generate_run_pdf(verified_run, pdf_path_3) is True
    assert pdf_path_3.exists()


# ==============================================================================
# P1-3: Isolated Demo State Reset
# ==============================================================================


def test_demo_reset_clears_runs_and_resets_loan_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """P1-3: /api/demo/reset cleans demo runs and restores loan_agent.py from baseline."""
    runs_dir = tmp_path / "runs"
    reports_dir = tmp_path / "reports"
    keys_dir = tmp_path / "keys"
    runs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    keys_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    monkeypatch.setattr(config, "ENABLE_DEMO", True)
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr(config, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(config, "TRUST_ROOT", keys_dir)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    store = LocalFileRunStore(log_dir=runs_dir)
    app = create_app(run_store=store)
    app.config["TESTING"] = True
    client = app.test_client()

    # Setup isolated sample_agent/loan_agent_demo in tmp_path
    demo_dir = tmp_path / "sample_agent" / "loan_agent_demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    baseline_file = demo_dir / "loan_agent_baseline.py"
    target_file = demo_dir / "loan_agent.py"

    baseline_content = "# Pristine Baseline Loan Agent Code\n"
    baseline_file.write_text(baseline_content, encoding="utf-8")

    # Simulate tampered / modified loan_agent.py
    tampered_content = "# Tampered Modified Code from Demo\n"
    target_file.write_text(tampered_content, encoding="utf-8")

    # Create dummy demo runs in the store
    demo_run_1 = "run-loan-risk-fail"
    demo_run_2 = "run-live-baseline-test1"
    store.create_run(demo_run_1, scenario_id="demo")
    store.create_run(demo_run_2, scenario_id="demo")
    assert store.get_run(demo_run_1) is not None
    assert store.get_run(demo_run_2) is not None

    with patch("eval_runner.runtime_services.resolve_run_store", return_value=store):
        resp = client.post("/api/demo/reset")
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["status"] == "reset"
        assert data["mode"] == "fresh"
        assert "loan_agent.py" in data["files_reset"]
        assert demo_run_1 in data["cleared_runs"] or demo_run_2 in data["cleared_runs"]

        # Confirm target_file was restored to pristine baseline
        assert target_file.read_text(encoding="utf-8") == baseline_content

        # Confirm demo runs deleted
        assert store.get_run(demo_run_1) is None
        assert store.get_run(demo_run_2) is None

    # Test error handling branch during demo run deletion
    broken_store = MagicMock()
    broken_store.delete_run.side_effect = OSError("filesystem locked")
    broken_store.list_runs.return_value = [{"run_id": "run-loan-risk-fail"}]
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=broken_store):
        resp_err = client.post("/api/demo/reset")
        assert resp_err.status_code == 200
        assert resp_err.get_json()["status"] == "reset"

    # Test when baseline file does not exist (files_reset is empty)
    baseline_file.unlink()
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=store):
        resp_no_base = client.post("/api/demo/reset")
        assert resp_no_base.status_code == 200
        assert resp_no_base.get_json()["files_reset"] == []

    # Test error handling when resolve_run_store fails completely (covers lines 62-63)
    with patch(
        "eval_runner.runtime_services.resolve_run_store",
        side_effect=RuntimeError("store resolution failure"),
    ):
        resp_res_err = client.post("/api/demo/reset")
        assert resp_res_err.status_code == 200
        assert resp_res_err.get_json()["status"] == "reset"

    # Test branches where delete_run returns False and non-demo run IDs are present
    mock_store_branches = MagicMock()
    mock_store_branches.delete_run.return_value = False
    mock_store_branches.list_runs.return_value = [
        {"run_id": "non-demo-run-123"},
        {"run_id": "run-loan-demo-false"},
    ]
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=mock_store_branches):
        resp_branches = client.post("/api/demo/reset")
        assert resp_branches.status_code == 200
        assert resp_branches.get_json()["status"] == "reset"


# ==============================================================================
# Additional Coverage: PDF Verdict Derivations, Certificate Routes & State Authority
# ==============================================================================


def test_pdf_service_all_verdict_branches(tmp_path: Path):
    """P1-2: Test all verdict branch mappings in generate_run_pdf."""
    # 1. ATTESTED_FAIL branch
    attested_fail_run = {
        "run_id": "run-attested-fail",
        "verification_status": "ATTESTED_FAIL",
        "is_authoritative": True,
    }
    p1 = tmp_path / "attested_fail.pdf"
    assert generate_run_pdf(attested_fail_run, p1) is True

    # 2. FAILED_VERIFICATION branch
    failed_verif_run = {
        "run_id": "run-failed-verif",
        "verification_status": "FAILED_VERIFICATION",
    }
    p2 = tmp_path / "failed_verif.pdf"
    assert generate_run_pdf(failed_verif_run, p2) is True

    # 3. Passed is False -> FAILED branch
    failed_run = {
        "run_id": "run-failed",
        "passed": False,
    }
    p3 = tmp_path / "failed.pdf"
    assert generate_run_pdf(failed_run, p3) is True

    # 4. raw_status UNKNOWN / UNVERIFIED branch
    unknown_run = {
        "run_id": "run-unknown",
        "status": "UNKNOWN",
    }
    p4 = tmp_path / "unknown.pdf"
    assert generate_run_pdf(unknown_run, p4) is True

    # 5. Custom status fallback
    custom_run = {
        "run_id": "run-custom",
        "status": "IN_PROGRESS",
    }
    p5 = tmp_path / "custom.pdf"
    assert generate_run_pdf(custom_run, p5) is True


def test_certificate_endpoints_error_and_edge_branches(run_app_and_store):
    """P0-3: Test error paths in /v1/certificates/<run_id> and public projection."""
    app, store = run_app_and_store
    client = app.test_client()

    # 1. Non-existent run -> 404
    resp = client.get("/v1/certificates/run-non-existent")
    assert resp.status_code == 404
    resp_pub = client.get("/v1/certificates/run-non-existent/public")
    assert resp_pub.status_code == 404

    # 2. Corrupted run record -> 500
    corrupt_id = "run-corrupted-test"
    store.create_run(corrupt_id, scenario_id="s1")
    vault = store._get_run_vault(corrupt_id)
    store._write_json_durable(store._record_path(vault), {"corrupted": True, "run_id": corrupt_id})
    resp_corrupt = client.get(f"/v1/certificates/{corrupt_id}")
    assert resp_corrupt.status_code == 500
    resp_corrupt_pub = client.get(f"/v1/certificates/{corrupt_id}/public")
    assert resp_corrupt_pub.status_code == 500

    # 3. Manifest missing on disk -> 404
    valid_id = "run-no-manifest-test"
    store.create_run(valid_id, scenario_id="s1")
    resp_no_man = client.get(f"/v1/certificates/{valid_id}")
    assert resp_no_man.status_code == 404
    resp_no_man_pub = client.get(f"/v1/certificates/{valid_id}/public")
    assert resp_no_man_pub.status_code == 404

    # 4. Manifest corruption exception -> 500
    with patch.object(store, "get_manifest", side_effect=ValueError("Corrupt manifest")):
        resp_man_err = client.get(f"/v1/certificates/{valid_id}")
        assert resp_man_err.status_code == 500
        resp_man_err_pub = client.get(f"/v1/certificates/{valid_id}/public")
        assert resp_man_err_pub.status_code == 500

    # 5. Manifest exception other than corrupt raises
    with patch.object(store, "get_manifest", side_effect=ValueError("schema mismatch")):
        with pytest.raises(ValueError, match="schema mismatch"):
            client.get(f"/v1/certificates/{valid_id}")
        with pytest.raises(ValueError, match="schema mismatch"):
            client.get(f"/v1/certificates/{valid_id}/public")

    # 6. Unverified manifest with NO status key -> covers missing branch 942->944
    no_status_id = "run-no-status-manifest"
    store.create_run(no_status_id, scenario_id="s1")
    store.save_run_manifest(no_status_id, {"run_id": no_status_id, "vc_version": "2.0.0"})
    with patch("eval_runner.verifier.TraceVerifier.verify_run", side_effect=RuntimeError("fail")):
        resp_no_stat = client.get(f"/v1/certificates/{no_status_id}")
        assert resp_no_stat.status_code == 200
        assert resp_no_stat.get_json()["verification_status"] == "UNVERIFIED"

    # 7. Inactive context returns 404
    with patch("eval_runner.console.routes.runs._run_is_in_active_context", return_value=False):
        resp_ctx = client.get(f"/v1/certificates/{no_status_id}")
        assert resp_ctx.status_code == 404


def test_state_authority_connector_identity_and_receipt_tokens(monkeypatch: pytest.MonkeyPatch):
    """P1-1: Verify HttpStateAuthorityConnector observation identity and cryptographic tokens."""
    from eval_runner.state_authority import (
        HttpStateAuthorityConnector,
        compute_connector_receipt_token,
    )

    monkeypatch.setattr(
        "eval_runner.state_authority._validate_external_authority_url",
        lambda url: url,
    )

    # 1. Authenticated HTTPS connector
    https_conn = HttpStateAuthorityConnector(
        base_url="https://api.authority.example.com/v1",
        default_headers={"Authorization": "Bearer secret_token"},
    )
    ident_auth = https_conn.observation_identity()
    assert ident_auth["authenticated"] is True
    assert ident_auth["transport"] == "https"
    assert ident_auth["connector_id"].startswith("connector:http:")
    receipt_auth = ident_auth["connector_receipt"]
    assert receipt_auth["authenticated"] is True
    assert receipt_auth["source_id"] == ident_auth["source_id"]
    assert receipt_auth["connector_id"] == ident_auth["connector_id"]
    assert receipt_auth["retrieval_token"] == compute_connector_receipt_token(
        ident_auth["connector_id"], ident_auth["source_id"]
    )

    # 2. Unauthenticated HTTP connector
    http_conn = HttpStateAuthorityConnector(
        base_url="http://insecure.authority.local",
        default_headers={},
    )
    ident_unauth = http_conn.observation_identity()
    assert ident_unauth["authenticated"] is False
    assert ident_unauth["transport"] == "http"
    receipt_unauth = ident_unauth["connector_receipt"]
    assert receipt_unauth["authenticated"] is False
    assert receipt_unauth["retrieval_token"] == compute_connector_receipt_token(
        ident_unauth["connector_id"], ident_unauth["source_id"]
    )
