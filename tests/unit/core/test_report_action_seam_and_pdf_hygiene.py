"""Unit tests for the neutral Core report-action discovery seam and OSS PDF layout hygiene."""

from __future__ import annotations

from pathlib import Path

from flask import Flask
from pypdf import PdfReader

from eval_runner.console.pdf_service import generate_run_pdf
from eval_runner.console.routes.runs import (
    register_report_action_provider,
    resolve_run_report_actions,
    run_bp,
)


def test_core_report_action_default_and_custom_provider_registration(monkeypatch):
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    run_id = "run-agentv-demo-um-adverse-review-v3-physician-hitl-01a19cf30bc3758fb92820439e9c64e5"

    register_report_action_provider(None)
    default_action = resolve_run_report_actions(run_id)
    assert default_action["mode"] == "basic"
    assert default_action["default_profile"] == "basic"
    assert len(default_action["profiles"]) == 1
    assert default_action["profiles"][0]["href"] == f"/api/v1/runs/{run_id}/report.pdf"

    def custom_provider(target_run_id: str, _context=None):
        return {
            "mode": "governed",
            "label": "Download Enterprise Assurance Report",
            "download_url": f"/api/v1/runs/{target_run_id}/report.pdf?profile=executive",
            "href": f"/api/v1/runs/{target_run_id}/report.pdf?profile=executive",
            "authority": "enterprise_control_plane",
            "default_profile": "executive",
            "profiles": [
                {
                    "id": "executive",
                    "label": "Executive Assurance Brief (1-Page)",
                    "description": "1-page summary",
                    "href": f"/api/v1/runs/{target_run_id}/report.pdf?profile=executive",
                },
                {
                    "id": "diagnostics",
                    "label": "Verification & Diagnostics Report",
                    "description": "Multi-page diagnostics",
                    "href": f"/api/v1/runs/{target_run_id}/report.pdf?profile=diagnostics",
                },
            ],
        }

    try:
        register_report_action_provider(custom_provider)
        app = Flask(__name__)
        app.secret_key = "test"
        app.config["TESTING"] = True
        app.register_blueprint(run_bp, url_prefix="/api")
        client = app.test_client()

        resp = client.get(f"/api/v1/runs/{run_id}/report-actions")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["mode"] == "governed"
        assert payload["default_profile"] == "executive"
        assert [p["id"] for p in payload["profiles"]] == ["executive", "diagnostics"]
    finally:
        register_report_action_provider(None)


def test_oss_pdf_service_wraps_long_ids_and_prevents_two_page_spill(tmp_path: Path):
    long_run_id = (
        "run-agentv-demo-um-adverse-review-v3-physician-hitl_mutated_approval_stale-"
        "01a1995be82574b1b17e830a9ebe60ca"
    )
    out_file = tmp_path / "oss_report.pdf"
    ok = generate_run_pdf(
        {
            "run_id": long_run_id,
            "scenario": "agentv-demo-um-adverse-review-v3-physician-hitl_mutated_approval_stale",
            "status": "ATTESTED_FAIL",
            "verification_status": "ATTESTED_FAIL",
            "passed": False,
            "score": 0.0,
            "trace_hash": "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
            "failed_turn": 6,
            "failed_node": "reset_authority",
        },
        str(out_file),
    )
    assert ok is True
    reader = PdfReader(str(out_file))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text() or ""
    assert "Run Identifier:" in text
    assert "Evidence Reference:" in text
    assert "Run Hash:" not in text
