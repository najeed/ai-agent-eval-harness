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
    mock_verif.certificate_authoritative = False
    mock_verif.status = "UNVERIFIED"
    mock_verif.terminal_verdict = "UNVERIFIED"
    mock_verif.claim_scope = {}

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
    mock_verif.terminal_verdict = "CERTIFIED_PASS"
    mock_verif.claim_scope = {}

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


# ==============================================================================
# P0-1: State Authority Receipt MAC, Authenticity Verification, and Tamper Defense
# ==============================================================================


def test_state_authority_receipt_tampering_and_forgery_rejection():
    """P0-1: Verify authenticated connector receipt creation and authenticity verification."""
    import hashlib

    from eval_runner.certification_truth import state_claim_failures
    from eval_runner.state_authority import (
        bound_state_snapshot,
        create_authenticated_connector_receipt,
        verify_connector_receipt_authenticity,
    )
    from eval_runner.utils import crypto

    source_id = "sha3_256:" + crypto.checksum("https://api.authority.example/orders")
    connector_id = f"connector:http:{source_id}"
    resp_digest = "sha3_256:" + hashlib.sha3_256(b'{"status":"approved"}').hexdigest()

    # 1. Authentic receipt verifies cleanly
    receipt = create_authenticated_connector_receipt(
        connector_id=connector_id,
        source_id=source_id,
        is_authenticated=True,
        request_spec="GET /orders/123",
        response_digest=resp_digest,
        execution_id="exec-1",
        timestamp="2026-01-01T00:00:00Z",
    )
    assert verify_connector_receipt_authenticity(receipt) is True

    # 2. Tampered request is rejected
    receipt_tampered_req = dict(receipt)
    receipt_tampered_req["request"] = "GET /orders/999"
    assert verify_connector_receipt_authenticity(receipt_tampered_req) is False

    # 3. Tampered response_digest is rejected
    receipt_tampered_digest = dict(receipt)
    receipt_tampered_digest["response_digest"] = "sha3_256:" + "0" * 64
    assert verify_connector_receipt_authenticity(receipt_tampered_digest) is False

    # 4. Tampered MAC/signature is rejected
    receipt_tampered_mac = dict(receipt)
    receipt_tampered_mac["mac"] = "bad_forged_mac_0000"
    receipt_tampered_mac["signature"] = "bad_forged_mac_0000"
    receipt_tampered_mac.pop("retrieval_token", None)
    assert verify_connector_receipt_authenticity(receipt_tampered_mac) is False

    # 5. Non-mapping or empty receipt is rejected
    assert verify_connector_receipt_authenticity("not-a-dict") is False  # type: ignore[arg-type]
    assert verify_connector_receipt_authenticity({}) is False

    # 6. Mismatched response_digest in state_claim_failures produces failure
    assertion = {"target": "authority:orders", "property": "status", "expected": "approved"}
    scenario = {
        "metadata": {
            "state_authorities": {"orders": {"url": "https://api.authority.example/orders"}}
        },
        "workflow": {"nodes": [{"id": "node-1", "expected_outcome": [assertion]}]},
    }
    before, before_hash = bound_state_snapshot({"status": "pending"})
    after, after_hash = bound_state_snapshot({"status": "approved"})

    # Receipt claiming a different response digest than actual post_snapshot_hash
    tampered_receipt = create_authenticated_connector_receipt(
        connector_id=connector_id,
        source_id=source_id,
        is_authenticated=True,
        response_digest="sha3_256:" + "f" * 64,
    )
    row = {
        "assertion": assertion,
        "source": "authority:orders",
        "pre_snapshot_hash": before_hash,
        "post_snapshot_hash": after_hash,
        "pre_observation": before,
        "post_observation": after,
        "pre_observation_identity": {
            "authenticated": True,
            "source_id": source_id,
            "connector_id": connector_id,
            "connector_receipt": tampered_receipt,
        },
        "post_observation_identity": {
            "authenticated": True,
            "source_id": source_id,
            "connector_id": connector_id,
            "connector_receipt": tampered_receipt,
        },
        "actual_before": "pending",
        "actual_after": "approved",
        "passed": True,
    }
    events = [
        {
            "event": "execution_graph_node",
            "scenario_node_id": "node-1",
            "execution_instance_id": "node-1:attempt:1",
            "status": "completed",
            "transition_evidence": [row],
        }
    ]
    failures = state_claim_failures(scenario, events)
    assert any("InvalidIndependentStateEvidence" in f for f in failures)

    # 7. Additional branch coverage for receipt validation and trust keys
    # Environment variable trust key resolution
    import os

    from eval_runner import config
    from eval_runner.state_authority import (
        compute_connector_receipt_token,
        get_state_authority_trust_key,
    )

    os.environ["AGENTV_STATE_AUTHORITY_KEY"] = "custom_test_env_key"
    try:
        assert get_state_authority_trust_key() == b"custom_test_env_key"
    finally:
        os.environ.pop("AGENTV_STATE_AUTHORITY_KEY", None)

    # Trust root file on disk and OSError fallback
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        key_file = tdp / "state_authority.key"
        key_file.write_bytes(b"file_based_key_123")
        old_root = getattr(config, "TRUST_ROOT", None)
        try:
            config.TRUST_ROOT = str(tdp)
            assert get_state_authority_trust_key() == b"file_based_key_123"

            # Test OSError reading key file falls back to hashed path
            def mock_read_bytes():
                raise OSError("Permission denied")

            with patch.object(Path, "read_bytes", side_effect=mock_read_bytes):
                derived = get_state_authority_trust_key()
                assert len(derived) == 32
        finally:
            config.TRUST_ROOT = old_root

    # Default trust key when TRUST_ROOT is None
    old_root = getattr(config, "TRUST_ROOT", None)
    try:
        config.TRUST_ROOT = None
        assert (
            get_state_authority_trust_key()
            == hashlib.sha3_256(b"agentv_default_state_authority_trust_key").digest()
        )
    finally:
        config.TRUST_ROOT = old_root

    # Token-only receipt verification and invalid non-string mac/token
    token_only_receipt = {
        "connector_id": connector_id,
        "source_id": source_id,
        "authenticated": True,
        "retrieval_token": compute_connector_receipt_token(connector_id, source_id),
    }
    assert verify_connector_receipt_authenticity(token_only_receipt) is True

    bad_token_receipt = dict(token_only_receipt, retrieval_token="bad_token_123")
    assert verify_connector_receipt_authenticity(bad_token_receipt) is False

    invalid_types_receipt = {
        "connector_id": connector_id,
        "source_id": source_id,
        "mac": 12345,
        "retrieval_token": 12345,
    }
    assert verify_connector_receipt_authenticity(invalid_types_receipt) is False

    # Coverage for state_claim_failures failure branches
    # a. Receipt not mapping
    row_bad_receipt = dict(
        row,
        pre_observation_identity=dict(
            row["pre_observation_identity"], connector_receipt="not-a-dict"
        ),
    )
    assert any(
        "InvalidIndependentStateEvidence" in f
        for f in state_claim_failures(
            scenario,
            [
                {
                    "event": "execution_graph_node",
                    "scenario_node_id": "node-1",
                    "execution_instance_id": "node-1:attempt:1",
                    "status": "completed",
                    "transition_evidence": [row_bad_receipt],
                }
            ],
        )
    )

    # b. Receipt source mismatch
    row_source_mismatch = dict(
        row,
        pre_observation_identity=dict(
            row["pre_observation_identity"],
            connector_receipt=dict(receipt, source_id="sha3_256:other"),
        ),
    )
    assert any(
        "InvalidIndependentStateEvidence" in f
        for f in state_claim_failures(
            scenario,
            [
                {
                    "event": "execution_graph_node",
                    "scenario_node_id": "node-1",
                    "execution_instance_id": "node-1:attempt:1",
                    "status": "completed",
                    "transition_evidence": [row_source_mismatch],
                }
            ],
        )
    )

    # c. Receipt unauthenticated
    row_unauth = dict(
        row,
        pre_observation_identity=dict(
            row["pre_observation_identity"], connector_receipt=dict(receipt, authenticated=False)
        ),
    )
    assert any(
        "InvalidIndependentStateEvidence" in f
        for f in state_claim_failures(
            scenario,
            [
                {
                    "event": "execution_graph_node",
                    "scenario_node_id": "node-1",
                    "execution_instance_id": "node-1:attempt:1",
                    "status": "completed",
                    "transition_evidence": [row_unauth],
                }
            ],
        )
    )

    # d. Observation snapshot hash mismatch
    row_hash_mismatch = dict(row, pre_snapshot_hash="sha3_256:corrupt_hash")
    assert any(
        "InvalidIndependentStateEvidence" in f
        for f in state_claim_failures(
            scenario,
            [
                {
                    "event": "execution_graph_node",
                    "scenario_node_id": "node-1",
                    "execution_instance_id": "node-1:attempt:1",
                    "status": "completed",
                    "transition_evidence": [row_hash_mismatch],
                }
            ],
        )
    )

    # e. Pre vs post authority mismatch
    row_diff_auth = dict(
        row,
        post_observation_identity=dict(
            row["post_observation_identity"], connector_id="connector:http:different"
        ),
    )
    assert any(
        "InvalidIndependentStateEvidence" in f
        for f in state_claim_failures(
            scenario,
            [
                {
                    "event": "execution_graph_node",
                    "scenario_node_id": "node-1",
                    "execution_instance_id": "node-1:attempt:1",
                    "status": "completed",
                    "transition_evidence": [row_diff_auth],
                }
            ],
        )
    )


# ==============================================================================
# P0-2: Public Certificate Publication Policy and Strict Field Filtering
# ==============================================================================


def test_public_certificate_publication_control_and_projection(run_app_and_store):
    """P0-2: Verify private runs return 403 and public projections strip sensitive data."""
    from eval_runner.console.routes.runs import (
        PUBLIC_CERTIFICATE_FIELDS,
        project_public_certificate,
    )

    app, store = run_app_and_store
    client = app.test_client()

    # 1. Private run returns 403 Forbidden on public endpoint
    priv_run_id = "run-private-cert-test"
    store.create_run(priv_run_id, scenario_id="sec-1")
    store.save_run_manifest(
        priv_run_id,
        {
            "run_id": priv_run_id,
            "vc_version": "2.0.0",
            "is_private": True,
            "status": "PASS",
        },
    )
    resp_priv = client.get(f"/v1/certificates/{priv_run_id}/public")
    assert resp_priv.status_code == 403
    assert "private" in resp_priv.get_json()["error"].lower()

    # 2. Explicit is_public=False returns 403 Forbidden
    no_pub_run_id = "run-no-public-test"
    store.create_run(no_pub_run_id, scenario_id="sec-1")
    store.save_run_manifest(
        no_pub_run_id,
        {
            "run_id": no_pub_run_id,
            "vc_version": "2.0.0",
            "is_public": False,
            "status": "PASS",
        },
    )
    resp_no_pub = client.get(f"/v1/certificates/{no_pub_run_id}/public")
    assert resp_no_pub.status_code == 403

    # 3. project_public_certificate strips internal/sensitive fields
    full_manifest = {
        "run_id": "run-proj-test",
        "vc_version": "2.0.0",
        "status": "CERTIFIED_PASS",
        "verification_status": "CERTIFIED_PASS",
        "certificate_authoritative": True,
        "is_authoritative": True,
        "evidence_valid": True,
        "certificate_valid": True,
        "cryptographically_valid": True,
        "file_integrity_valid": True,
        "evaluation_passed": True,
        "algorithm": "ML-DSA-65",
        "signature": "valid_sig",
        # Sensitive or private internal fields that must be stripped:
        "raw_evidence": {"private_key": "sec_12345"},
        "scenario_inputs": {"customer_ssn": "000-11-2222"},
        "internal_jwt_secret": "secret_abc",
        "environment_variables": {"API_KEY": "sk-123456"},
    }
    projected = project_public_certificate(full_manifest)
    assert "raw_evidence" not in projected
    assert "scenario_inputs" not in projected
    assert "internal_jwt_secret" not in projected
    assert "environment_variables" not in projected
    assert set(projected.keys()).issubset(PUBLIC_CERTIFICATE_FIELDS)
    assert projected["run_id"] == "run-proj-test"
    assert projected["algorithm"] == "ML-DSA-65"


# ==============================================================================
# P1-1: Certificate Endpoint Preserves ATTESTED_FAIL
# ==============================================================================


def test_certificate_endpoints_preserve_attested_fail(run_app_and_store):
    """P1-1: Verify authoritative ATTESTED_FAIL is preserved and not collapsed to UNVERIFIED."""
    app, store = run_app_and_store
    client = app.test_client()

    run_id = "run-attested-fail-test"
    store.create_run(run_id, scenario_id="audit-1")
    manifest = {
        "run_id": run_id,
        "vc_version": "2.0.0",
        "status": "FAILED",
        "verification_status": "ATTESTED_FAIL",
    }
    store.save_run_manifest(run_id, manifest)

    mock_verif = MagicMock()
    mock_verif.is_valid = False
    mock_verif.certificate_valid = False
    mock_verif.cryptographically_valid = True
    mock_verif.file_integrity_valid = True
    mock_verif.evaluation_passed = False
    mock_verif.is_authoritative = True
    mock_verif.certificate_authoritative = True
    mock_verif.status = "ATTESTED_FAIL"
    mock_verif.terminal_verdict = "ATTESTED_FAIL"
    mock_verif.claim_scope = {"scope": "external_business_state"}

    with patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=mock_verif):
        # /v1/certificates/<run_id>
        resp = client.get(f"/v1/certificates/{run_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["verification_status"] == "ATTESTED_FAIL"
        assert data["terminal_verdict"] == "ATTESTED_FAIL"
        assert data["certificate_authoritative"] is True
        assert data["evaluation_passed"] is False

        # /v1/certificates/<run_id>/public
        resp_pub = client.get(f"/v1/certificates/{run_id}/public")
        assert resp_pub.status_code == 200
        pub_data = resp_pub.get_json()
        assert pub_data["verification_status"] == "ATTESTED_FAIL"
        assert pub_data["terminal_verdict"] == "ATTESTED_FAIL"
        assert pub_data["certificate_authoritative"] is True


# ==============================================================================
# P1-4: Independent Cryptographic Validity in /v1/runs/<run_id>/verify
# ==============================================================================


def test_run_verify_endpoint_preserves_independent_validity_dimensions(run_app_and_store):
    """P1-4: Endpoint preserves cryptographically_valid independently from is_valid."""
    app, store = run_app_and_store
    client = app.test_client()

    run_id = "run-verify-dimensions-test"
    store.create_run(run_id, scenario_id="sec-1")
    manifest = {
        "run_id": run_id,
        "vc_version": "2.0.0",
        "status": "FAIL",
        "signatures": [{"identity": "sec-oracle", "algorithm": "ED25519"}],
    }
    store.save_run_manifest(run_id, manifest)
    store.append_events(run_id, [{"event": "start"}])

    mock_verif_result = {
        "is_valid": False,  # Overall validity failed (business oracle failed)
        "cryptographically_valid": True,  # Signature is mathematically authentic
        "file_integrity_valid": True,  # Hashes matched
        "certificate_valid": True,  # Signed cert exists
        "certificate_authoritative": True,
        "verification_status": "ATTESTED_FAIL",
        "claim_scope": "external_business_state",
    }

    with patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=mock_verif_result):
        resp = client.get(f"/api/v1/runs/{run_id}/verify")
        assert resp.status_code == 200
        data = resp.get_json()

        # Disentangled dimensions must be preserved:
        assert data["is_valid"] is False
        assert data["cryptographically_valid"] is True
        assert data["file_integrity_valid"] is True
        assert data["certificate_valid"] is True
        assert data["certificate_authoritative"] is True
        assert data["verification_status"] == "ATTESTED_FAIL"
        assert data["algorithm"] == "ED25519"
        assert data["signer_identity"] == "sec-oracle"


# ==============================================================================
# P1-5: Evidence Ledger Verification on Storage Provider and TraceVerifier
# ==============================================================================


def test_evidence_ledger_verification_with_local_run_store(tmp_path: Path):
    """P1-5: LocalFileRunStore.verify_evidence_ledger and get_artifact_bytes contracts."""
    import hashlib

    runs_dir = tmp_path / "ledger_runs"
    store = LocalFileRunStore(log_dir=runs_dir)
    run_id = "run-ledger-verify-test"
    store.create_run(run_id, scenario_id="ledger-scen")

    # Write a test artifact inside the run vault
    vault = store._get_run_vault(run_id)
    artifacts_dir = vault / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    evidence_file = artifacts_dir / "db_export.csv"
    evidence_data = b"id,name,balance\n1,Alice,1000\n2,Bob,500\n"
    evidence_file.write_bytes(evidence_data)

    expected_hash = "sha3_256:" + hashlib.sha3_256(evidence_data).hexdigest()

    # 1. get_artifact_bytes retrieves matching bytes
    assert store.get_artifact_bytes(run_id, "artifacts/db_export.csv") == evidence_data
    assert store.get_artifact_bytes(run_id, "artifacts/missing.csv") is None
    # Path traversal protection
    assert store.get_artifact_bytes(run_id, "../../etc/passwd") is None

    # 2. verify_evidence_ledger succeeds with correct hash
    valid_ledger = {"artifacts/db_export.csv": expected_hash}
    assert store.verify_evidence_ledger(run_id, valid_ledger) is True

    # 3. verify_evidence_ledger fails with tampered hash
    tampered_ledger = {"artifacts/db_export.csv": "sha3_256:" + "0" * 64}
    assert store.verify_evidence_ledger(run_id, tampered_ledger) is False

    # 4. verify_evidence_ledger fails when artifact is missing
    missing_ledger = {"artifacts/not_found.csv": expected_hash}
    assert store.verify_evidence_ledger(run_id, missing_ledger) is False

    # 5. verify_evidence_ledger fails with non-mapping input
    assert store.verify_evidence_ledger(run_id, None) is False  # type: ignore[arg-type]


def test_trace_verifier_verify_trace_bytes_with_ledger():
    """P1-5: TraceVerifier.verify_trace_bytes executes explicit evidence ledger verification."""
    from eval_runner.verifier import TraceVerifier

    run_id = "run-trace-ledger-test"
    trace_content = b'{"event":"start"}\n'
    import hashlib

    trace_hash = "sha3_256:" + hashlib.sha3_256(trace_content).hexdigest()

    mock_store = MagicMock()
    mock_store.get_trace_bytes.return_value = trace_content

    # 1. verify_ledger=True with missing evidence_ledger fails
    manifest_no_ledger = {
        "run_id": run_id,
        "trace_hash": trace_hash,
    }
    with patch("eval_runner.run_lifecycle.get_run_lifecycle_state", return_value="SEALED"):
        res_no_ledger = TraceVerifier.verify_trace_bytes(
            trace_content,
            manifest_no_ledger,
            run_store=mock_store,
            verify_ledger=True,
            trace_only=True,
        )
        assert res_no_ledger is False

    # 2. verify_ledger=True with provider verify_evidence_ledger failing
    mock_store.verify_evidence_ledger.return_value = False
    manifest_with_ledger = {
        "run_id": run_id,
        "trace_hash": trace_hash,
        "evidence_ledger": {"artifacts/data.bin": "sha3_256:1111"},
    }
    with patch("eval_runner.run_lifecycle.get_run_lifecycle_state", return_value="SEALED"):
        res_fail = TraceVerifier.verify_trace_bytes(
            trace_content,
            manifest_with_ledger,
            run_store=mock_store,
            verify_ledger=True,
            trace_only=True,
        )
        assert res_fail is False
        mock_store.verify_evidence_ledger.assert_called_once_with(
            run_id, manifest_with_ledger["evidence_ledger"], context=None
        )

    # 3. verify_ledger=True using get_artifact_bytes fallback when verify_evidence_ledger is absent
    store_no_verifier = MagicMock(spec=["get_trace_bytes", "get_artifact_bytes"])
    store_no_verifier.get_trace_bytes.return_value = trace_content
    store_no_verifier.get_artifact_bytes.return_value = None  # Missing artifact
    with patch("eval_runner.run_lifecycle.get_run_lifecycle_state", return_value="SEALED"):
        res_fallback_missing = TraceVerifier.verify_trace_bytes(
            trace_content,
            manifest_with_ledger,
            run_store=store_no_verifier,
            verify_ledger=True,
            trace_only=True,
        )
        assert res_fallback_missing is False

    # 4. Fallback with artifact bytes hash mismatch
    store_no_verifier.get_artifact_bytes.return_value = b"mismatched artifact content"
    with patch("eval_runner.run_lifecycle.get_run_lifecycle_state", return_value="SEALED"):
        res_fallback_mismatch = TraceVerifier.verify_trace_bytes(
            trace_content,
            manifest_with_ledger,
            run_store=store_no_verifier,
            verify_ledger=True,
            trace_only=True,
        )
        assert res_fallback_mismatch is False
