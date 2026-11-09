"""
tests/unit/console/test_certification_readiness_and_report_defects.py
Authoritative unit tests verifying remediations for the 8 release-blocking assurance defects:
1. P0: PDF report authoritative verification gate (TraceVerifier.verify_run).
2. P0: Public verification API disentanglement (independent integrity, signature, cert, outcome).
3. P0: Regression-suite PDF authoritative per-run pass counts and labels.
4. P1: Run-detail certification eligibility (eligible, ineligible, pending with blocking reasons).
5. P1: Verification package result authority preservation.
6. P1: PDF signature & PQC status projection (verified facts vs UNVERIFIED).
7. P1: Reject caller-supplied scenario_data in certification REST route.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.console.app import create_app
from eval_runner.console.pdf_service import (
    _is_run_authoritative_pass,
    _run_verification_label,
    generate_bundle_pdf,
    generate_run_pdf,
)
from eval_runner.console.routes.runs import _assess_run_certification_readiness
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.verifier import TraceVerifier


@pytest.fixture
def run_app_and_store(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    reports_dir = tmp_path / "reports"
    keys_dir = tmp_path / "keys"
    runs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    keys_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr(config, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(config, "TRUST_ROOT", keys_dir)

    store = LocalFileRunStore(log_dir=runs_dir)
    app = create_app(run_store=store)
    app.config["TESTING"] = True
    return app, store


# ==============================================================================
# 1. Defect 6.1 & 6.4: Certification Readiness & PDF Report Verifier Authority
# ==============================================================================


def test_assess_certification_readiness_pending():
    run = {"run_id": "r1", "execution_mode": "live"}
    manifest = {}
    events = [{"event": "step", "data": {}}]
    eligibility, reasons = _assess_run_certification_readiness(
        run=run,
        manifest=manifest,
        events=events,
        raw_status="RUNNING",
        terminal=False,
        evidence_nodes=5,
    )
    assert eligibility == "pending"
    assert "currently active" in reasons[0]


def test_assess_certification_readiness_already_certified():
    run = {"run_id": "r1", "execution_mode": "live"}
    manifest = {"verification_package": {"pkg": True}}
    events = [
        {"event": "run_start", "data": {"execution_mode": "live"}},
        {"event": "evaluator_finalization", "data": {"outcome": "pass"}},
    ]
    eligibility, reasons = _assess_run_certification_readiness(
        run=run,
        manifest=manifest,
        events=events,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=5,
    )
    assert eligibility == "ineligible"
    assert any("already has an issued verification certificate" in r for r in reasons)


def test_assess_certification_readiness_no_events_and_zero_nodes():
    run = {"run_id": "r1", "execution_mode": "live"}
    manifest = {}
    eligibility, reasons = _assess_run_certification_readiness(
        run=run,
        manifest=manifest,
        events=[],
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=0,
    )
    assert eligibility == "ineligible"
    assert any("No trace events recorded" in r for r in reasons)
    assert any("Evidence graph contains 0 nodes" in r for r in reasons)


def test_assess_certification_readiness_ineligible_mode_and_provisional():
    run = {"run_id": "r1", "execution_mode": "simulated", "provisional": True}
    manifest = {"execution_mode": "simulated", "provisional": True}
    events = [
        {"event": "run_start", "data": {"execution_mode": "simulated"}},
        {"event": "evaluator_finalization", "data": {"outcome": "pass"}},
    ]
    eligibility, reasons = _assess_run_certification_readiness(
        run=run,
        manifest=manifest,
        events=events,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=3,
    )
    assert eligibility == "ineligible"
    assert any("not eligible for authoritative certification" in r for r in reasons)


def test_assess_certification_readiness_simulated_tools():
    # Case A: has_simulated_tools in event data
    run = {"run_id": "r1", "execution_mode": "live"}
    manifest = {"execution_mode": "live"}
    events_a = [
        {"event": "run_start", "data": {"execution_mode": "live"}},
        {"event": "tool_call", "data": {"has_simulated_tools": True}},
        {"event": "evaluator_finalization", "data": {"outcome": "pass"}},
    ]
    eligibility, reasons = _assess_run_certification_readiness(
        run=run,
        manifest=manifest,
        events=events_a,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=3,
    )
    assert eligibility == "ineligible"
    assert any("Trace contains simulated tool execution events" in r for r in reasons)

    # Case B: has_simulated_tools at event root with non-simulated inner data
    events_b = [
        {"event": "run_start", "data": {"execution_mode": "live"}},
        {"event": "tool_call", "data": {"tool": "live_bash"}, "has_simulated_tools": True},
        {"event": "evaluator_finalization", "data": {"outcome": "pass"}},
    ]
    eligibility_b, _ = _assess_run_certification_readiness(
        run=run,
        manifest=manifest,
        events=events_b,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=3,
    )
    assert eligibility_b == "ineligible"

    # Case C: tool_call provenance in simulated/mock/synthetic
    for prov in ("simulated", "mock", "synthetic"):
        events_c = [
            {"event": "run_start", "data": {"execution_mode": "live"}},
            {"event": "tool_result", "data": {"provenance": prov}},
            {"event": "evaluator_finalization", "data": {"outcome": "pass"}},
        ]
        elig, _ = _assess_run_certification_readiness(
            run=run,
            manifest=manifest,
            events=events_c,
            raw_status="COMPLETED",
            terminal=True,
            evidence_nodes=3,
        )
        assert elig == "ineligible"


def test_assess_certification_readiness_finalization_missing_and_fail():
    run = {"run_id": "r1", "execution_mode": "live"}
    manifest = {"execution_mode": "live"}

    # Missing finalization
    events_no_fin = [
        {"event": "run_start", "data": {"execution_mode": "live"}},
        {"event": "step", "data": {}},
    ]
    elig_no_fin, reasons_no_fin = _assess_run_certification_readiness(
        run=run,
        manifest=manifest,
        events=events_no_fin,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=2,
    )
    assert elig_no_fin == "ineligible"
    assert any("Missing authoritative evaluator finalization record" in r for r in reasons_no_fin)

    # Failing finalization outcome
    events_fail_fin = [
        {"event": "run_start", "data": {"execution_mode": "live"}},
        {"event": "evaluator_finalization", "data": {"outcome": "fail"}},
    ]
    elig_fail, reasons_fail = _assess_run_certification_readiness(
        run=run,
        manifest=manifest,
        events=events_fail_fin,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=2,
    )
    assert elig_fail == "ineligible"
    assert any("is not an authoritative pass" in r for r in reasons_fail)


def test_assess_certification_readiness_eligible_success():
    run = {"run_id": "r1", "execution_mode": "live"}
    manifest = {"execution_mode": "live"}
    events = [
        {"event": "run_start", "data": {"execution_mode": "live"}},
        {"event": "tool_call", "data": {"provenance": "provider_live"}},
        {"event": "evaluator_finalization", "data": {"outcome": "pass"}},
    ]
    eligibility, reasons = _assess_run_certification_readiness(
        run=run,
        manifest=manifest,
        events=events,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=3,
    )
    assert eligibility == "eligible"
    assert len(reasons) == 0


def test_get_run_status_exposes_certification_readiness(run_app_and_store):
    app, store = run_app_and_store
    run_id = "run-status-test"
    store.create_run(run_id, "scenario-1")

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = {"id": "test-admin", "name": "Admin", "permissions": ["*"]}
        res = client.get(f"/api/v1/runs/{run_id}")
        assert res.status_code == 200
        data = res.get_json()
        assert "certification_eligibility" in data
        assert "certification_blocking_reasons" in data
        assert "can_certify" in data
        assert data["can_certify"] is False


def test_download_pdf_report_authoritative_gate(run_app_and_store):
    app, store = run_app_and_store
    run_id = "run-pdf-auth"
    store.create_run(run_id, "scenario-pdf")
    store.update_run_status(run_id, "PASSED")  # Stored status claims PASSED

    captured_report_data = {}

    def mock_generate_pdf(report_data, destination):
        captured_report_data.update(report_data)
        Path(destination).write_bytes(b"%PDF-1.7 Authoritative Output")
        return True

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = {"id": "test-admin", "name": "Admin", "permissions": ["*"]}

        # 1. Stored status PASSED, but TraceVerifier returns UNVERIFIED -> passed must be False!
        unverified_result = {
            "run_id": run_id,
            "verification_status": "UNVERIFIED",
            "verified": False,
            "has_certificate": False,
        }
        with (
            patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=unverified_result),
            patch(
                "eval_runner.console.pdf_service.generate_run_pdf", side_effect=mock_generate_pdf
            ),
        ):
            resp = client.get(f"/api/v1/runs/{run_id}/report.pdf")
            assert resp.status_code == 200
            assert captured_report_data["passed"] is False
            assert captured_report_data["is_certified"] is False
            assert captured_report_data["verification_status"] == "UNVERIFIED"

        # 2. TraceVerifier returns VERIFIED -> passed is True!
        verified_result = {
            "run_id": run_id,
            "verification_status": "VERIFIED",
            "verified": True,
            "has_certificate": True,
            "cryptographically_valid": True,
            "file_integrity_valid": True,
            "certificate_valid": True,
            "algorithm": "ML-DSA-65",
        }
        captured_report_data.clear()
        with (
            patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=verified_result),
            patch(
                "eval_runner.console.pdf_service.generate_run_pdf", side_effect=mock_generate_pdf
            ),
        ):
            resp = client.get(f"/api/v1/runs/{run_id}/report.pdf")
            assert resp.status_code == 200
            assert captured_report_data["passed"] is True
            assert captured_report_data["is_certified"] is True
            assert captured_report_data["verification_status"] == "VERIFIED"
            assert captured_report_data["cryptographically_valid"] is True
            assert captured_report_data["algorithm"] == "ML-DSA-65"


# ==============================================================================
# 2. Defect 6.2 & 6.8: Verification API Disentanglement & Scenario Rejection
# ==============================================================================


def test_public_verify_run_disentangled_dimensions(run_app_and_store):
    app, store = run_app_and_store
    run_id = "disentangled-verify"
    run_dir = Path(config.RUN_LOG_DIR) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text('{"event": "start"}\n', encoding="utf-8")
    (run_dir / ".sealed").touch()
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"execution_mode": "live", "compliance": {"status": "pass", "score": 1.0}}),
        encoding="utf-8",
    )

    verif_mock = {
        "run_id": run_id,
        "is_valid": True,
        "file_integrity_valid": True,
        "cryptographically_valid": True,
        "certificate_valid": True,
        "certificate_authoritative": True,
        "evaluation_passed": True,
        "verified": True,
        "terminal_verdict": "CERTIFIED_PASS",
        "verification_status": "VERIFIED",
    }

    with app.test_client() as client:
        with patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=verif_mock):
            res = client.get(f"/api/v1/verify/{run_id}")
            assert res.status_code == 200
            data = res.get_json()
            assert data["file_integrity_valid"] is True
            assert data["cryptographically_valid"] is True
            assert data["certificate_valid"] is True
            assert data["evaluation_passed"] is True
            assert data["certificate_authoritative"] is True
            assert data["terminal_verdict"] == "CERTIFIED_PASS"


def test_certify_run_rejects_caller_supplied_scenario(run_app_and_store):
    app, store = run_app_and_store
    run_id = "cert-scenario-reject"
    store.create_run(run_id, "scen-orig")

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = {"id": "test-admin", "name": "Admin", "permissions": ["*"]}
        res = client.post(
            "/api/v1/certify",
            json={"run_id": run_id, "scenario_data": {"id": "caller-injected"}},
        )
        assert res.status_code == 400
        assert "Caller-supplied scenario_data is rejected" in res.get_json()["error"]


# ==============================================================================
# 3. Defect 6.3 & 6.7: PDF Service PQC Projection & Bundle Authoritative Verification
# ==============================================================================


def test_pdf_service_pqc_and_cert_status_branches(tmp_path):
    output_path = tmp_path / "branches.pdf"

    # Branch 1: Custom verified algorithm
    data_custom = {
        "run_id": "r-custom",
        "scenario": "s",
        "cryptographically_valid": True,
        "certificate_valid": True,
        "algorithm": "FALCON-512",
        "status": "PASSED",
    }
    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", False):
            generate_run_pdf(data_custom, output_path)
    txt_custom = output_path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "FALCON-512" in txt_custom
    assert "ISSUED / VALIDATED" in txt_custom

    # Branch 2: Attested fail with valid certificate
    data_fail = {
        "run_id": "r-fail",
        "scenario": "s",
        "cryptographically_valid": True,
        "certificate_valid": True,
        "algorithm": "Ed25519",
        "status": "ATTESTED FAIL",
    }
    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", False):
            generate_run_pdf(data_fail, output_path)
    txt_fail = output_path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "CLASSICAL (Ed25519)" in txt_fail
    assert "ATTESTATION OF NON-CERTIFICATION" in txt_fail

    # Branch 3: Cryptographically valid but no algorithm specified -> UNVERIFIED
    data_no_algo = {
        "run_id": "r-no-algo",
        "scenario": "s",
        "cryptographically_valid": True,
        "certificate_valid": False,
        "algorithm": "",
        "status": "UNVERIFIED",
    }
    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", False):
            generate_run_pdf(data_no_algo, output_path)
    txt_no_algo = output_path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "NOT ISSUED (Unverified)" in txt_no_algo


def test_bundle_pdf_verification_labels_and_pass_counts(tmp_path):
    # Test _is_run_authoritative_pass directly
    assert _is_run_authoritative_pass({"verification_status": "VERIFIED"}) is True
    assert _is_run_authoritative_pass({"terminal_verdict": "CERTIFIED_PASS"}) is True
    assert _is_run_authoritative_pass({"verified": True, "verdict": "CERTIFIED"}) is True
    assert _is_run_authoritative_pass({"status": "COMPLETED"}) is False
    assert _is_run_authoritative_pass({"status": "passed"}) is False
    assert _is_run_authoritative_pass({}) is False

    # Test _run_verification_label directly
    assert _run_verification_label({"verification_status": "VERIFIED"}) == "VERIFIED"
    assert _run_verification_label({"terminal_verdict": "CERTIFIED_PASS"}) == "VERIFIED"
    assert _run_verification_label({"terminal_verdict": "ATTESTED_FAIL"}) == "ATTESTED FAIL"
    assert _run_verification_label({"verification_status": "FAILED_VERIFICATION"}) == "FAILING"
    assert _run_verification_label({"status": "COMPLETED"}) == "UNVERIFIED"

    # Test ReportLab path with authoritative bundle runs
    suite_data = {"suite_id": "s1", "name": "Suite", "agent_name": "A1", "created_at": "2026-01-01"}
    runs = [
        {"run_id": "r1", "status": "COMPLETED", "verification_status": "VERIFIED"},
        {"run_id": "r2", "status": "COMPLETED", "verification_status": "ATTESTED_FAIL"},
        {"run_id": "r3", "status": "FAILED", "verification_status": "FAILED"},
        {"run_id": "r4", "status": "COMPLETED"},  # unverified completed run
    ]
    out_rl = tmp_path / "bundle_rl.pdf"
    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", True):
            with patch("eval_runner.console.pdf_service.SimpleDocTemplate") as mock_doc:
                mock_doc.return_value.build = MagicMock()
                res = generate_bundle_pdf(suite_data, runs, out_rl)
                assert res is True


def test_assess_certification_readiness_run_end_finalization():
    run = {"run_id": "r1", "execution_mode": "live"}
    manifest = {"execution_mode": "live"}
    events = [
        {"event": "run_start", "data": {"execution_mode": "live"}},
        {"event": "run_end", "data": {"finalization": {"outcome": "certified_pass"}}},
    ]
    eligibility, reasons = _assess_run_certification_readiness(
        run=run,
        manifest=manifest,
        events=events,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=2,
    )
    assert eligibility == "eligible"
    assert len(reasons) == 0


def test_public_verify_run_authoritative_fallback_without_dict_key(run_app_and_store):
    app, store = run_app_and_store
    run_id = "disentangled-fallback"
    run_dir = Path(config.RUN_LOG_DIR) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text('{"event": "start"}\n', encoding="utf-8")
    (run_dir / ".sealed").touch()
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"execution_mode": "live", "compliance": {"status": "pass", "score": 1.0}}),
        encoding="utf-8",
    )

    verif_legacy = {
        "run_id": run_id,
        "is_valid": True,
        "verified": True,
        "terminal_verdict": "CERTIFIED_PASS",
        "verification_status": "VERIFIED",
    }

    with app.test_client() as client:
        with patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=verif_legacy):
            res = client.get(f"/api/v1/verify/{run_id}")
            assert res.status_code == 200
            data = res.get_json()
            assert data["certificate_authoritative"] is True
            assert data["file_integrity_valid"] is True
            assert data["cryptographically_valid"] is True


def test_trace_verifier_disentangled_dimensions_branches(tmp_path, monkeypatch):
    import hashlib

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    store = LocalFileRunStore(log_dir=runs_dir)

    run_id = "test-disentangled-branches"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    trace_content = b'{"event": "init"}\n'
    (run_dir / "run.jsonl").write_bytes(trace_content)
    (run_dir / ".sealed").touch()

    trace_sha3 = hashlib.sha3_256(trace_content).hexdigest()

    # Case 1: sha3_256 prefix, simulated mode, verify_trace_certificate succeeds
    manifest_data = {
        "run_id": run_id,
        "execution_mode": "simulated",
        "trace_hash": f"sha3_256:{trace_sha3}",
        "scenario": {"scenario_id": "test-scen", "version": "1.0"},
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    with patch("eval_runner.verifier.verify_trace_certificate", return_value={"verified": True}):
        res = TraceVerifier.verify_run(run_id, run_store=store)
        assert res["file_integrity_valid"] is True
        assert res["cryptographically_valid"] is True
        assert res["certificate_valid"] is False
        assert res["certificate_authoritative"] is False
        assert res["is_valid"] is False

    # Case 2: no prefix on trace_hash, mismatching hash, verify raises Exception
    manifest_data["trace_hash"] = "mismatched_hex_digest"
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    with patch(
        "eval_runner.verifier.verify_trace_certificate", side_effect=RuntimeError("Crypto error")
    ):
        res = TraceVerifier.verify_run(run_id, run_store=store)
        assert res["file_integrity_valid"] is False
        assert res["cryptographically_valid"] is False
        assert res["certificate_valid"] is False

    # Case 3: trace_bytes is None (missing run.jsonl)
    (run_dir / "run.jsonl").unlink()
    with patch("eval_runner.verifier.verify_trace_certificate", return_value={"verified": False}):
        res = TraceVerifier.verify_run(run_id, run_store=store)
        assert res["file_integrity_valid"] is False
        assert res["cryptographically_valid"] is False
