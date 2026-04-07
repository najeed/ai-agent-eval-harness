import json
import pytest
from eval_runner import config
from eval_runner.console.app import create_app
from eval_runner.verifier import TraceVerifier

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_public_verify_endpoint(client, tmp_path):
    """
    Integration Test: Verify that the /api/v1/verify/<run_id> endpoint is public
    and correctly verifies a trace against its manifest.
    """
    # 1. Setup - Create a real signed run in temp dir
    trace_run_id = "run_verify_test"
    trace_path = tmp_path / f"{trace_run_id}.jsonl"
    trace_path.write_text('{"event": "test"}', encoding="utf-8")

    # Setup reports dir
    original_reports = config.REPORTS_DIR
    original_runs = config.RUN_LOG_DIR
    config.REPORTS_DIR = tmp_path / "reports"
    config.RUN_LOG_DIR = tmp_path

    try:
        # Sign the trace (generates manifest)
        TraceVerifier.sign_trace(trace_path=str(trace_path))

        # 2. Test API Verification (No Auth Headers)
        response = client.get(f"/api/v1/verify/{trace_run_id}")
        assert response.status_code == 200
        data = response.get_json()
        assert data["run_id"] == trace_run_id
        assert data["verified"] is True
        assert "SHA-256" in data["method"]

        # 3. Test tampered trace
        trace_path.write_text('{"event": "tampered"}', encoding="utf-8")
        response_tampered = client.get(f"/api/v1/verify/{trace_run_id}")
        assert response_tampered.status_code == 200
        assert response_tampered.get_json()["verified"] is False

        # 4. Test non-existent run
        response_missing = client.get("/api/v1/verify/missing_run")
        assert response_missing.status_code == 404

    finally:
        config.REPORTS_DIR = original_reports
        config.RUN_LOG_DIR = original_runs
