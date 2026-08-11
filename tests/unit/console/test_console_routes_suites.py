"""
tests/unit/console/test_console_routes_suites.py

Unit tests for eval_runner.console.routes.suites.
Covers: _load_suites, list_suites, create_suite, bundle_suite,
        download_suite_bundle, verify_bundle, get_run_report_pdf.
"""

import json
import zipfile
from io import BytesIO
from unittest.mock import patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.suites import suites_bp


@pytest.fixture
def suites_jail(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    runs = root / "runs"
    runs.mkdir()
    reports = root / "reports"
    (reports / "certificates").mkdir(parents=True)
    suites_dir = root / "results" / "suites"
    suites_dir.mkdir(parents=True)

    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs)
    monkeypatch.setattr(config, "REPORTS_DIR", reports)
    monkeypatch.setattr("eval_runner.console.routes.suites.SUITES_DIR", suites_dir)

    return {"root": root, "runs": runs, "reports": reports, "suites_dir": suites_dir}


@pytest.fixture
def suites_client(suites_jail):
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(suites_bp, url_prefix="/api")

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


# ---------------------------------------------------------------------------
# GET /v1/suites
# ---------------------------------------------------------------------------


def test_suites_list_empty(suites_client):
    res = suites_client.get("/api/v1/suites")
    assert res.status_code == 200
    assert res.get_json()["suites"] == []


def test_suites_list_with_data(suites_client, suites_jail):
    s1 = {"suite_id": "suite-aaa", "name": "Suite A", "created_at": "2026-07-01T00:00:00Z"}
    s2 = {"suite_id": "suite-bbb", "name": "Suite B", "created_at": "2026-07-02T00:00:00Z"}
    (suites_jail["suites_dir"] / "suite-aaa.json").write_text(json.dumps(s1), encoding="utf-8")
    (suites_jail["suites_dir"] / "suite-bbb.json").write_text(json.dumps(s2), encoding="utf-8")

    res = suites_client.get("/api/v1/suites")
    assert res.status_code == 200
    data = res.get_json()["suites"]
    assert len(data) == 2
    # Sorted descending by created_at
    assert data[0]["suite_id"] == "suite-bbb"


def test_suites_list_skips_manifest_files(suites_client, suites_jail):
    (suites_jail["suites_dir"] / "suite-ccc_manifest.json").write_text("{}", encoding="utf-8")
    (suites_jail["suites_dir"] / "suite-ccc.json").write_text(
        json.dumps({"suite_id": "suite-ccc", "created_at": ""}), encoding="utf-8"
    )
    res = suites_client.get("/api/v1/suites")
    assert len(res.get_json()["suites"]) == 1


def test_suites_list_skips_corrupt_file(suites_client, suites_jail):
    (suites_jail["suites_dir"] / "corrupt.json").write_text("{{bad", encoding="utf-8")
    res = suites_client.get("/api/v1/suites")
    assert res.status_code == 200
    assert res.get_json()["suites"] == []


# ---------------------------------------------------------------------------
# POST /v1/suites (create)
# ---------------------------------------------------------------------------


def test_suites_create_missing_fields(suites_client):
    res = suites_client.post("/api/v1/suites", json={"name": "Only Name"})
    assert res.status_code == 400
    assert "Missing" in res.get_json()["error"]


def test_suites_create_success(suites_client, suites_jail):
    res = suites_client.post(
        "/api/v1/suites",
        json={"name": "Finance Suite", "agent_name": "GPT-4", "run_ids": ["r1", "r2"]},
    )
    assert res.status_code == 201
    data = res.get_json()
    assert data["name"] == "Finance Suite"
    assert data["suite_id"].startswith("suite_")

    # Verify persisted to disk
    saved = list(suites_jail["suites_dir"].glob("suite_*.json"))
    assert len(saved) == 1


def test_suites_create_write_error(suites_client, suites_jail):
    with patch("builtins.open", side_effect=OSError("disk full")):
        res = suites_client.post(
            "/api/v1/suites",
            json={"name": "Fail Suite", "agent_name": "Agt", "run_ids": ["r1"]},
        )
    assert res.status_code == 500


# ---------------------------------------------------------------------------
# POST /v1/suites/<id>/bundle
# ---------------------------------------------------------------------------


def test_suites_bundle_not_found(suites_client):
    res = suites_client.post("/api/v1/suites/nonexistent/bundle")
    assert res.status_code == 404


def test_suites_bundle_success(suites_client, suites_jail):
    run_id = "run-bundle-1"
    run_dir = suites_jail["runs"] / run_id
    run_dir.mkdir()
    trace = run_dir / "run.jsonl"
    trace.write_text(
        json.dumps({"run_id": run_id, "timestamp": "2026-07-01T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )

    suite = {
        "suite_id": "suite-bundle",
        "name": "Bundle Suite",
        "agent_name": "GPT",
        "run_ids": [run_id],
        "created_at": "2026-07-01T00:00:00Z",
    }
    suite_path = suites_jail["suites_dir"] / "suite-bundle.json"
    suite_path.write_text(json.dumps(suite), encoding="utf-8")

    mock_bundle_res = {
        "bundle_path": str(suites_jail["suites_dir"] / "suite-bundle_bundle.zip"),
        "manifest_path": str(suites_jail["suites_dir"] / "suite-bundle_audit_manifest.json"),
    }
    # Create the fake ZIP and manifest
    (suites_jail["suites_dir"] / "suite-bundle_bundle.zip").write_bytes(b"PK")
    (suites_jail["suites_dir"] / "suite-bundle_audit_manifest.json").write_text(
        "{}", encoding="utf-8"
    )

    with patch(
        "eval_runner.console.routes.suites.explain_trace",
        return_value={"root_cause": "none", "suggestion": "N/A", "confidence": 0.9},
    ):
        with patch(
            "eval_runner.console.routes.suites.generate_run_pdf",
            return_value=True,
        ):
            with patch(
                "eval_runner.console.routes.suites.generate_bundle_pdf",
                return_value=True,
            ):
                with patch(
                    "eval_runner.console.routes.suites.ArtifactPlugin.bundle_artifacts",
                    return_value=mock_bundle_res,
                ):
                    res = suites_client.post("/api/v1/suites/suite-bundle/bundle")

    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"


def test_suites_bundle_corrupt_suite_record(suites_client, suites_jail):
    suite_path = suites_jail["suites_dir"] / "suite-corrupt.json"
    suite_path.write_text("{{bad", encoding="utf-8")
    res = suites_client.post("/api/v1/suites/suite-corrupt/bundle")
    assert res.status_code == 500


def test_suites_bundle_missing_trace(suites_client, suites_jail):
    """Run IDs with no trace files are silently skipped."""
    suite = {
        "suite_id": "suite-skip",
        "name": "Skip Suite",
        "agent_name": "Agt",
        "run_ids": ["nonexistent-run"],
        "created_at": "2026-07-01T00:00:00Z",
    }
    suite_path = suites_jail["suites_dir"] / "suite-skip.json"
    suite_path.write_text(json.dumps(suite), encoding="utf-8")

    fake_bundle = {
        "bundle_path": str(suites_jail["suites_dir"] / "suite-skip_bundle.zip"),
        "manifest_path": str(suites_jail["suites_dir"] / "suite-skip_audit_manifest.json"),
    }
    (suites_jail["suites_dir"] / "suite-skip_bundle.zip").write_bytes(b"PK")
    (suites_jail["suites_dir"] / "suite-skip_audit_manifest.json").write_text(
        "{}", encoding="utf-8"
    )

    with patch("eval_runner.console.routes.suites.generate_bundle_pdf", return_value=True):
        with patch(
            "eval_runner.console.routes.suites.ArtifactPlugin.bundle_artifacts",
            return_value=fake_bundle,
        ):
            res = suites_client.post("/api/v1/suites/suite-skip/bundle")

    assert res.status_code == 200


# ---------------------------------------------------------------------------
# GET /v1/suites/<id>/download
# ---------------------------------------------------------------------------


def test_suites_download_not_found(suites_client):
    res = suites_client.get("/api/v1/suites/missing-suite/download")
    assert res.status_code == 404


def test_suites_download_success(suites_client, suites_jail):
    zip_path = suites_jail["suites_dir"] / "suite-dl_bundle.zip"
    zip_path.write_bytes(b"PK")
    with patch("eval_runner.console.routes.suites.send_file") as mock_sf:
        mock_sf.return_value = ("data", 200, {})
        res = suites_client.get("/api/v1/suites/suite-dl/download")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# POST /v1/bundles/verify
# ---------------------------------------------------------------------------


def test_suites_verify_no_file_uploaded(suites_client):
    res = suites_client.post("/api/v1/bundles/verify")
    assert res.status_code == 400
    assert "No manifest" in res.get_json()["error"]


def test_suites_verify_success(suites_client, suites_jail):
    mock_result = {"valid": True, "signature": "OK"}

    data = {"file": (BytesIO(b'{"version":1}'), "audit_manifest.json")}
    with patch(
        "eval_runner.console.routes.suites.ArtifactPlugin.verify_integrity",
        return_value=mock_result,
    ):
        res = suites_client.post(
            "/api/v1/bundles/verify",
            data=data,
            content_type="multipart/form-data",
        )

    assert res.status_code == 200
    assert res.get_json()["valid"] is True


def test_suites_verify_plugin_exception(suites_client, suites_jail):
    data = {"file": (BytesIO(b'{"version":1}'), "audit_manifest.json")}
    with patch(
        "eval_runner.console.routes.suites.ArtifactPlugin.verify_integrity",
        side_effect=RuntimeError("corrupt manifest"),
    ):
        res = suites_client.post(
            "/api/v1/bundles/verify",
            data=data,
            content_type="multipart/form-data",
        )

    assert res.status_code == 500
    assert "corrupt manifest" in res.get_json()["message"]


# ---------------------------------------------------------------------------
# GET /v1/runs/<run_id>/report.pdf
# ---------------------------------------------------------------------------


def test_suites_run_report_pdf_not_found(suites_client):
    res = suites_client.get("/api/v1/runs/ghost-run/report.pdf")
    assert res.status_code == 404


def test_suites_run_report_pdf_success(suites_client, suites_jail):
    run_id = "run-pdf-1"
    run_dir = suites_jail["runs"] / run_id
    run_dir.mkdir()
    trace = run_dir / "run.jsonl"
    trace.write_text(
        json.dumps({"run_id": run_id, "timestamp": "2026-07-01T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )

    pdf_path = suites_jail["suites_dir"] / f"report_{run_id}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 placeholder")

    with patch(
        "eval_runner.console.routes.suites.explain_trace",
        return_value={"confidence": 0.9},
    ):
        with patch("eval_runner.console.routes.suites.generate_run_pdf", return_value=True):
            with patch("eval_runner.console.routes.suites.send_file") as mock_sf:
                mock_sf.return_value = ("data", 200, {"Content-Type": "application/pdf"})
                res = suites_client.get(f"/api/v1/runs/{run_id}/report.pdf")

    assert res.status_code == 200


def test_suites_run_report_pdf_generation_failed(suites_client, suites_jail):
    run_id = "run-pdf-fail"
    run_dir = suites_jail["runs"] / run_id
    run_dir.mkdir()
    trace = run_dir / "run.jsonl"
    trace.write_text(json.dumps({"run_id": run_id}) + "\n", encoding="utf-8")

    with patch(
        "eval_runner.console.routes.suites.explain_trace",
        return_value={"confidence": 0.0},
    ):
        with patch("eval_runner.console.routes.suites.generate_run_pdf", return_value=False):
            res = suites_client.get(f"/api/v1/runs/{run_id}/report.pdf")

    assert res.status_code == 500


def test_suites_run_report_pdf_explain_exception(suites_client, suites_jail):
    run_id = "run-pdf-explain-exc"
    run_dir = suites_jail["runs"] / run_id
    run_dir.mkdir()
    trace = run_dir / "run.jsonl"
    trace.write_text(json.dumps({"run_id": run_id}) + "\n", encoding="utf-8")

    with patch(
        "eval_runner.console.routes.suites.explain_trace",
        side_effect=RuntimeError("explain crash"),
    ):
        with patch("eval_runner.console.routes.suites.generate_run_pdf", return_value=False):
            res = suites_client.get(f"/api/v1/runs/{run_id}/report.pdf")

    assert res.status_code == 500


def test_suites_bundle_pre_existing_staging_and_master_log_fallback(suites_client, suites_jail):
    """Verify pre-existing staging dir deletion and master log fallback."""
    suite_id = "suite-stage-test"
    # Pre-create staging dir
    staging_dir = suites_jail["suites_dir"] / f"tmp_stage_{suite_id}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "junk.txt").write_text("junk")

    run_id = "run-stage-1"
    # Set up master log but no run log to trigger fallback
    line_correct = json.dumps({"run_id": run_id, "status": "COMPLETED"})
    line_corrupt = f'{{"run_id": "{run_id}", "status": corrupt}}'
    line_other = json.dumps({"run_id": "other_run"})
    line_partial = json.dumps({"run_id": "other_run", "tags": [run_id]})
    master_log = suites_jail["runs"] / "run.jsonl"
    master_log.write_text(
        f"{line_other}\n{line_corrupt}\n{line_partial}\n{line_correct}\n", encoding="utf-8"
    )

    suite = {
        "suite_id": suite_id,
        "name": "Stage Test Suite",
        "agent_name": "Agt",
        "run_ids": [run_id],
        "created_at": "2026-07-01T00:00:00Z",
    }
    (suites_jail["suites_dir"] / f"{suite_id}.json").write_text(json.dumps(suite), encoding="utf-8")

    fake_bundle = {
        "bundle_path": str(suites_jail["suites_dir"] / f"{suite_id}_bundle.zip"),
        "manifest_path": str(suites_jail["suites_dir"] / f"{suite_id}_audit_manifest.json"),
    }
    (suites_jail["suites_dir"] / f"{suite_id}_bundle.zip").write_bytes(b"PK")
    manifest_path = suites_jail["suites_dir"] / f"{suite_id}_audit_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    with patch("eval_runner.console.routes.suites.resolve_trace_path", return_value=None):
        with patch("eval_runner.console.routes.suites.generate_bundle_pdf", return_value=True):
            with patch("eval_runner.console.routes.suites.generate_run_pdf", return_value=True):
                with patch(
                    "eval_runner.console.routes.suites.ArtifactPlugin.bundle_artifacts",
                    return_value=fake_bundle,
                ):
                    res = suites_client.post(f"/api/v1/suites/{suite_id}/bundle")

    assert res.status_code == 200
    # Staging dir should be deleted
    assert not staging_dir.exists()


def test_suites_bundle_explain_failure_and_read_trace_line_error(suites_client, suites_jail):
    """Verify explain_trace failure (148-150) and first trace line exception (161-162)."""
    suite_id = "suite-fail-test"
    run_id = "run-fail-1"
    run_dir = suites_jail["runs"] / run_id
    run_dir.mkdir()
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text("{}", encoding="utf-8")

    suite = {
        "suite_id": suite_id,
        "name": "Suite",
        "agent_name": "Agt",
        "run_ids": [run_id],
        "created_at": "2026-07-01T00:00:00Z",
    }
    (suites_jail["suites_dir"] / f"{suite_id}.json").write_text(json.dumps(suite), encoding="utf-8")

    fake_bundle = {
        "bundle_path": str(suites_jail["suites_dir"] / f"{suite_id}_bundle.zip"),
        "manifest_path": str(suites_jail["suites_dir"] / f"{suite_id}_audit_manifest.json"),
    }
    (suites_jail["suites_dir"] / f"{suite_id}_bundle.zip").write_bytes(b"PK")
    manifest_path = suites_jail["suites_dir"] / f"{suite_id}_audit_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    calls = [0]
    orig_open = open

    def mock_open(file, *args, **kwargs):
        if str(file).endswith("run.jsonl") and "runs" in str(file) and calls[0] == 0:
            calls[0] += 1
            raise OSError("Mock read first trace line error")
        return orig_open(file, *args, **kwargs)

    with patch("eval_runner.console.routes.suites.resolve_trace_path", return_value=trace_path):
        with patch(
            "eval_runner.console.routes.suites.explain_trace",
            side_effect=RuntimeError("explain error"),
        ):
            with patch("eval_runner.console.routes.suites.generate_bundle_pdf", return_value=True):
                with patch("eval_runner.console.routes.suites.generate_run_pdf", return_value=True):
                    with patch(
                        "eval_runner.console.routes.suites.ArtifactPlugin.bundle_artifacts",
                        return_value=fake_bundle,
                    ):
                        with patch("builtins.open", side_effect=mock_open):
                            res = suites_client.post(f"/api/v1/suites/{suite_id}/bundle")

    assert res.status_code == 200


def test_suites_bundle_missing_deliverables_and_copy_cert(suites_client, suites_jail):
    """Verify bundle when generated files are missing, and copy cert if it exists."""
    suite_id = "suite-cert-test"
    run_id = "run-cert-1"
    run_dir = suites_jail["runs"] / run_id
    run_dir.mkdir()
    (run_dir / "run.jsonl").write_text("{}", encoding="utf-8")

    # Set up certificate
    cert_path = suites_jail["reports"] / "certificates" / f"{run_id}_vc.json"
    cert_path.write_text("{}", encoding="utf-8")

    suite = {
        "suite_id": suite_id,
        "name": "Suite",
        "agent_name": "Agt",
        "run_ids": [run_id],
        "created_at": "2026-07-01T00:00:00Z",
    }
    (suites_jail["suites_dir"] / f"{suite_id}.json").write_text(json.dumps(suite), encoding="utf-8")

    # Return bundle results pointing to non-existent paths to test missing deliverables
    fake_bundle = {
        "bundle_path": str(suites_jail["suites_dir"] / "non_existent_zip.zip"),
        "manifest_path": str(suites_jail["suites_dir"] / "non_existent_manifest.json"),
    }

    with patch(
        "eval_runner.console.routes.suites.resolve_trace_path", return_value=run_dir / "run.jsonl"
    ):
        with patch("eval_runner.console.routes.suites.explain_trace", return_value={}):
            with patch("eval_runner.console.routes.suites.generate_bundle_pdf", return_value=True):
                with patch("eval_runner.console.routes.suites.generate_run_pdf", return_value=True):
                    with patch(
                        "eval_runner.console.routes.suites.ArtifactPlugin.bundle_artifacts",
                        return_value=fake_bundle,
                    ):
                        res = suites_client.post(f"/api/v1/suites/{suite_id}/bundle")

    assert res.status_code == 200


def test_suites_run_report_pdf_master_log_and_exceptions(suites_client, suites_jail):
    """Verify pdf report endpoint handles master log scanning and exceptions."""
    run_id = "run-pdf-master"
    line_correct = json.dumps({"run_id": run_id, "status": "COMPLETED"})
    line_corrupt = f'{{"run_id": "{run_id}", "status": corrupt}}'
    line_other = json.dumps({"run_id": "other_run"})
    line_partial = json.dumps({"run_id": "other_run", "tags": [run_id]})
    master_log = suites_jail["runs"] / "run.jsonl"
    master_log.write_text(
        f"{line_other}\n{line_corrupt}\n{line_partial}\n{line_correct}\n", encoding="utf-8"
    )

    def mock_gen(data, path):
        path.write_bytes(b"PDF")
        return True

    # Test master log scanning and unlink on success
    with patch("eval_runner.console.routes.suites.resolve_trace_path", return_value=None):
        with patch("eval_runner.console.routes.suites.explain_trace", return_value={}):
            with patch("eval_runner.console.routes.suites.generate_run_pdf", side_effect=mock_gen):
                with patch(
                    "eval_runner.console.routes.suites.send_file", return_value="pdf-stream"
                ):
                    res = suites_client.get(f"/api/v1/runs/{run_id}/report.pdf")
                    assert res.status_code == 200

    # Test master log read exception — match exact path to avoid heuristic fragility
    orig_open = open
    master_log_path = str(suites_jail["runs"] / "run.jsonl")

    def mock_open_master(file, *args, **kwargs):
        if str(file) == master_log_path:
            raise OSError("Master log read error")
        return orig_open(file, *args, **kwargs)

    with patch("eval_runner.console.routes.suites.resolve_trace_path", return_value=None):
        with patch("builtins.open", side_effect=mock_open_master):
            res = suites_client.get(f"/api/v1/runs/{run_id}/report.pdf")
            assert res.status_code == 404

    # Test PDF generation exception with temp_extracted cleanup
    with patch("eval_runner.console.routes.suites.resolve_trace_path", return_value=None):
        with patch("eval_runner.console.routes.suites.explain_trace", return_value={}):
            with patch(
                "eval_runner.console.routes.suites.generate_run_pdf",
                side_effect=RuntimeError("PDF gen crash"),
            ):
                res = suites_client.get(f"/api/v1/runs/{run_id}/report.pdf")
                assert res.status_code == 500

    # Test first trace line read exception
    trace_path = suites_jail["runs"] / "run-trace-err"
    trace_path.mkdir()
    trace_file = trace_path / "run.jsonl"
    trace_file.write_text("{}", encoding="utf-8")

    def mock_open(file, *args, **kwargs):
        if str(file).endswith("run.jsonl") and "runs" in str(file):
            raise OSError("First line read error")
        return orig_open(file, *args, **kwargs)

    with patch("eval_runner.console.routes.suites.resolve_trace_path", return_value=trace_file):
        with patch("eval_runner.console.routes.suites.explain_trace", return_value={}):
            with patch(
                "eval_runner.console.routes.suites.generate_run_pdf",
                side_effect=RuntimeError("PDF gen crash"),
            ):
                with patch("builtins.open", side_effect=mock_open):
                    res = suites_client.get("/api/v1/runs/run-trace-err/report.pdf")
                    assert res.status_code == 500


def test_suites_run_report_pdf_empty_trace(suites_client, suites_jail):
    """Verify pdf report empty trace first line read (lines 320-326 branch)."""
    run_id = "run-pdf-empty"
    run_dir = suites_jail["runs"] / run_id
    run_dir.mkdir()
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text("", encoding="utf-8")

    def mock_gen(data, path):
        path.write_bytes(b"PDF")
        return True

    with patch("eval_runner.console.routes.suites.resolve_trace_path", return_value=trace_file):
        with patch("eval_runner.console.routes.suites.explain_trace", return_value={}):
            with patch("eval_runner.console.routes.suites.generate_run_pdf", side_effect=mock_gen):
                with patch(
                    "eval_runner.console.routes.suites.send_file", return_value="pdf-stream"
                ):
                    res = suites_client.get(f"/api/v1/runs/{run_id}/report.pdf")
                    assert res.status_code == 200


def test_suites_run_report_pdf_generate_failed_temp_cleanup(suites_client, suites_jail):
    """Verify temp file cleanup on PDF generation failure (line 351)."""
    run_id = "run-pdf-fail-cleanup"
    line_correct = json.dumps({"run_id": run_id, "status": "COMPLETED"})
    line_corrupt = f'{{"run_id": "{run_id}", "status": corrupt}}'
    line_other = json.dumps({"run_id": "other_run"})
    line_partial = json.dumps({"run_id": f"other_{run_id}"})
    master_log = suites_jail["runs"] / "run.jsonl"
    master_log.write_text(
        f"{line_other}\n{line_corrupt}\n{line_partial}\n{line_correct}\n", encoding="utf-8"
    )

    with patch("eval_runner.console.routes.suites.resolve_trace_path", return_value=None):
        with patch("eval_runner.console.routes.suites.explain_trace", return_value={}):
            with patch("eval_runner.console.routes.suites.generate_run_pdf", return_value=False):
                res = suites_client.get(f"/api/v1/runs/{run_id}/report.pdf")
                assert res.status_code == 500


def test_suites_verify_save_exception(suites_client):
    """Verify temp path exists check on verify save failure (lines 268-270 branch)."""
    from io import BytesIO

    data = {"file": (BytesIO(b"{}"), "manifest.json")}
    with patch("werkzeug.datastructures.FileStorage.save", side_effect=OSError("write error")):
        res = suites_client.post(
            "/api/v1/bundles/verify", data=data, content_type="multipart/form-data"
        )
    assert res.status_code == 500
    assert res.get_json()["status"] == "error"


def test_suites_bundle_zip_exception(suites_client, suites_jail):
    """Verify zip bundle exception cleanup path (lines 236-240)."""
    suite_id = "suite-zip-fail"
    run_id = "run-zip-1"
    run_dir = suites_jail["runs"] / run_id
    run_dir.mkdir()
    (run_dir / "run.jsonl").write_text("{}", encoding="utf-8")

    suite = {
        "suite_id": suite_id,
        "name": "Suite",
        "agent_name": "Agt",
        "run_ids": [run_id],
        "created_at": "2026-07-01T00:00:00Z",
    }
    (suites_jail["suites_dir"] / f"{suite_id}.json").write_text(json.dumps(suite), encoding="utf-8")

    with patch(
        "eval_runner.console.routes.suites.resolve_trace_path", return_value=run_dir / "run.jsonl"
    ):
        with patch("eval_runner.console.routes.suites.explain_trace", return_value={}):
            with patch("eval_runner.console.routes.suites.generate_bundle_pdf", return_value=True):
                with patch("eval_runner.console.routes.suites.generate_run_pdf", return_value=True):
                    with patch(
                        "eval_runner.console.routes.suites.ArtifactPlugin.bundle_artifacts",
                        side_effect=RuntimeError("zip failed"),
                    ):
                        res = suites_client.post(f"/api/v1/suites/{suite_id}/bundle")
    assert res.status_code == 500
    assert "zip failed" in res.get_json()["error"]


def test_suites_bundle_master_log_read_error(suites_client, suites_jail):
    """Verify master log read exception in bundle logic (lines 132-133)."""
    suite_id = "suite-read-err"
    run_id = "run-read-1"
    master_log = suites_jail["runs"] / "run.jsonl"
    master_log.write_text("{}", encoding="utf-8")

    suite = {
        "suite_id": suite_id,
        "name": "Suite",
        "agent_name": "Agt",
        "run_ids": [run_id],
        "created_at": "2026-07-01T00:00:00Z",
    }
    (suites_jail["suites_dir"] / f"{suite_id}.json").write_text(json.dumps(suite), encoding="utf-8")

    orig_open = open

    def mock_open(file, *args, **kwargs):
        if str(file).endswith("run.jsonl") and "tmp_stage" not in str(file):
            raise OSError("Master log read error")
        return orig_open(file, *args, **kwargs)

    fake_bundle = {
        "bundle_path": str(suites_jail["root"] / f"{suite_id}_bundle.zip"),
        "manifest_path": str(suites_jail["root"] / f"{suite_id}_audit_manifest.json"),
    }
    (suites_jail["root"] / f"{suite_id}_bundle.zip").write_bytes(b"PK")
    (suites_jail["root"] / f"{suite_id}_audit_manifest.json").write_text("{}", encoding="utf-8")

    with patch("eval_runner.console.routes.suites.resolve_trace_path", return_value=None):
        with patch("builtins.open", side_effect=mock_open):
            with patch(
                "eval_runner.console.routes.suites.ArtifactPlugin.bundle_artifacts",
                return_value=fake_bundle,
            ):
                res = suites_client.post(f"/api/v1/suites/{suite_id}/bundle")
    assert res.status_code == 200


def test_suites_bundle_generate_pdf_false(suites_client, suites_jail):
    """Verify false branch of generate_run_pdf and generate_bundle_pdf."""
    suite_id = "suite-pdf-false"
    run_id = "run-pdf-false-1"
    run_dir = suites_jail["runs"] / run_id
    run_dir.mkdir()
    (run_dir / "run.jsonl").write_text("{}", encoding="utf-8")

    suite = {
        "suite_id": suite_id,
        "name": "Suite",
        "agent_name": "Agt",
        "run_ids": [run_id],
        "created_at": "2026-07-01T00:00:00Z",
    }
    (suites_jail["suites_dir"] / f"{suite_id}.json").write_text(json.dumps(suite), encoding="utf-8")

    fake_bundle = {
        "bundle_path": str(suites_jail["root"] / f"{suite_id}_bundle.zip"),
        "manifest_path": str(suites_jail["root"] / f"{suite_id}_audit_manifest.json"),
    }
    (suites_jail["root"] / f"{suite_id}_bundle.zip").write_bytes(b"PK")
    (suites_jail["root"] / f"{suite_id}_audit_manifest.json").write_text("{}", encoding="utf-8")

    with patch(
        "eval_runner.console.routes.suites.resolve_trace_path", return_value=run_dir / "run.jsonl"
    ):
        with patch("eval_runner.console.routes.suites.explain_trace", return_value={}):
            with patch("eval_runner.console.routes.suites.generate_run_pdf", return_value=False):
                with patch(
                    "eval_runner.console.routes.suites.generate_bundle_pdf", return_value=False
                ):
                    with patch(
                        "eval_runner.console.routes.suites.ArtifactPlugin.bundle_artifacts",
                        return_value=fake_bundle,
                    ):
                        res = suites_client.post(f"/api/v1/suites/{suite_id}/bundle")
    assert res.status_code == 200


def test_suites_bundle_mkdir_exception(suites_client, suites_jail):
    """Verify staging directory mkdir failure exception block (lines 238->240 branch)."""
    suite_id = "suite-mkdir-fail"
    run_id = "run-mkdir-1"
    run_dir = suites_jail["runs"] / run_id
    run_dir.mkdir()
    (run_dir / "run.jsonl").write_text("{}", encoding="utf-8")

    suite = {
        "suite_id": suite_id,
        "name": "Suite",
        "agent_name": "Agt",
        "run_ids": [run_id],
        "created_at": "2026-07-01T00:00:00Z",
    }
    (suites_jail["suites_dir"] / f"{suite_id}.json").write_text(json.dumps(suite), encoding="utf-8")

    with patch(
        "eval_runner.console.routes.suites.resolve_trace_path", return_value=run_dir / "run.jsonl"
    ):
        with patch("pathlib.Path.mkdir", side_effect=OSError("mkdir error")):
            res = suites_client.post(f"/api/v1/suites/{suite_id}/bundle")
    assert res.status_code == 500
    assert "mkdir error" in res.get_json()["error"]


def test_suites_bundle_empty_trace_first_line(suites_client, suites_jail):
    """Cover false branch of `if first_line:` (line 158->164) in bundle_suite loop.

    When the trace file is empty, readline() returns '' which is falsy, so the
    timestamp stays as the default UTC string and we skip JSON parsing.
    """
    suite_id = "suite-empty-trace"
    run_id = "run-empty-trace-1"
    run_dir = suites_jail["runs"] / run_id
    run_dir.mkdir()
    # Write an empty trace file so readline() returns ""
    (run_dir / "run.jsonl").write_text("", encoding="utf-8")

    suite = {
        "suite_id": suite_id,
        "name": "EmptySuite",
        "agent_name": "Agt",
        "run_ids": [run_id],
        "created_at": "2026-07-01T00:00:00Z",
    }
    (suites_jail["suites_dir"] / f"{suite_id}.json").write_text(json.dumps(suite), encoding="utf-8")

    fake_bundle = {
        "bundle_path": str(suites_jail["root"] / f"{suite_id}_bundle.zip"),
        "manifest_path": str(suites_jail["root"] / f"{suite_id}_manifest.json"),
    }
    (suites_jail["root"] / f"{suite_id}_bundle.zip").write_bytes(b"PK")
    (suites_jail["root"] / f"{suite_id}_manifest.json").write_text("{}", encoding="utf-8")

    with patch(
        "eval_runner.console.routes.suites.resolve_trace_path",
        return_value=run_dir / "run.jsonl",
    ):
        with patch("eval_runner.console.routes.suites.explain_trace", return_value={}):
            with patch("eval_runner.console.routes.suites.generate_run_pdf", return_value=False):
                with patch(
                    "eval_runner.console.routes.suites.generate_bundle_pdf", return_value=False
                ):
                    with patch(
                        "eval_runner.console.routes.suites.ArtifactPlugin.bundle_artifacts",
                        return_value=fake_bundle,
                    ):
                        res = suites_client.post(f"/api/v1/suites/{suite_id}/bundle")
    assert res.status_code == 200


def test_suites_verify_zip_missing_manifest(suites_client):
    """Test verify_bundle with a ZIP that lacks audit_manifest.json."""
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("other.txt", "content")
    zip_bytes = zip_buf.getvalue()

    res = suites_client.post(
        "/api/v1/bundles/verify",
        data={"file": (BytesIO(zip_bytes), "bundle.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    assert res.get_json()["is_valid"] is False
    assert "audit_manifest.json not found" in res.get_json()["error"]


def test_suites_verify_zip_missing_files(suites_client):
    """Test verify_bundle with a ZIP where a file listed in manifest is missing."""
    manifest = {"files": [{"name": "missing.txt", "file_hash": "123"}]}
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("audit_manifest.json", json.dumps(manifest))
    zip_bytes = zip_buf.getvalue()

    res = suites_client.post(
        "/api/v1/bundles/verify",
        data={"file": (BytesIO(zip_bytes), "bundle.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    assert res.get_json()["is_valid"] is False
    assert res.get_json()["details"][0]["status"] == "missing"


def test_suites_verify_zip_mismatched_hash(suites_client):
    """Test verify_bundle with a ZIP where a file hash mismatch is detected."""
    manifest = {"files": [{"name": "file.txt", "file_hash": "wrong_hash"}]}
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("audit_manifest.json", json.dumps(manifest))
        z.writestr("file.txt", "actual content")
    zip_bytes = zip_buf.getvalue()

    res = suites_client.post(
        "/api/v1/bundles/verify",
        data={"file": (BytesIO(zip_bytes), "bundle.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    assert res.get_json()["is_valid"] is False
    assert res.get_json()["details"][0]["status"] == "mismatch"


def test_suites_verify_zip_valid_signature_success(suites_client):
    """Test verify_bundle with correct files, hashes and valid Ed25519 signature."""
    import base64
    import hashlib

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    # Generate key
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )

    file_content = b"correct content"
    expected_hash = hashlib.sha3_256(file_content).hexdigest()

    manifest = {"files": [{"name": "file.txt", "file_hash": expected_hash}]}

    # Generate signature on manifest excluding signature/public_key keys
    manifest_json = json.dumps(manifest, sort_keys=True)
    sig_bytes = private_key.sign(manifest_json.encode())

    # Add key and signature to manifest
    manifest["signature_ed25519"] = base64.b64encode(sig_bytes).decode()
    manifest["public_key"] = base64.b64encode(pub_bytes).decode()

    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("audit_manifest.json", json.dumps(manifest))
        z.writestr("file.txt", file_content)
    zip_bytes = zip_buf.getvalue()

    res = suites_client.post(
        "/api/v1/bundles/verify",
        data={"file": (BytesIO(zip_bytes), "bundle.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    assert res.get_json()["is_valid"] is True
    assert res.get_json()["details"][0]["status"] == "valid"


def test_suites_verify_zip_signature_fail(suites_client):
    """Test verify_bundle with correct files/hashes but signature validation fails."""
    import base64
    import hashlib

    file_content = b"correct content"
    expected_hash = hashlib.sha3_256(file_content).hexdigest()

    manifest = {
        "files": [{"name": "file.txt", "file_hash": expected_hash}],
        "signature_ed25519": base64.b64encode(b"wrong_sig_value").decode(),
        "public_key": base64.b64encode(b"wrong_pub_key_value").decode(),
    }

    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("audit_manifest.json", json.dumps(manifest))
        z.writestr("file.txt", file_content)
    zip_bytes = zip_buf.getvalue()

    res = suites_client.post(
        "/api/v1/bundles/verify",
        data={"file": (BytesIO(zip_bytes), "bundle.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    assert res.get_json()["is_valid"] is False


def test_suites_verify_zip_corrupt_zip_error(suites_client):
    """Test verify_bundle with corrupt zip bytes triggers 500 error."""
    res = suites_client.post(
        "/api/v1/bundles/verify",
        data={"file": (BytesIO(b"corrupt-zip-file-data"), "bundle.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 500
    assert "Failed to parse ZIP bundle" in res.get_json()["message"]
