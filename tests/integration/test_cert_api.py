import pytest
import json
import os
from pathlib import Path
from eval_runner.verifier import TraceVerifier
from eval_runner import config
from eval_runner.console.app import create_app

@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_public_certificate_endpoint(client, tmp_path):
    """
    Integration Test: Verify that the /api/v1/certificates endpoint is public 
    and returns a valid, signed Verification Certificate (VC).
    """
    # 1. Setup - Create a real signed run
    trace_run_id = "run_999_integration"
    trace_path = tmp_path / f"{trace_run_id}.jsonl"
    trace_path.write_bytes(b"integration test trace data")
    
    # Setup key pair
    keys_dir = tmp_path / "keys"
    TraceVerifier.generate_key_pair(output_dir=str(keys_dir))
    private_key_path = keys_dir / "private_key.pem"
    
    # Setup reports dir
    original_reports = config.REPORTS_DIR
    original_runs = config.RUN_LOG_DIR
    config.REPORTS_DIR = tmp_path / "reports"
    config.RUN_LOG_DIR = tmp_path
    
    try:
        # Sign the trace
        TraceVerifier.sign_trace(
            trace_path=str(trace_path),
            private_key_path=str(private_key_path),
            fingerprint_id="dna_integration_hardened"
        )
        
        # 2. Test API Retrieval (No Auth Headers)
        response = client.get(f"/api/v1/certificates/{trace_run_id}")
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert data["run_id"] == trace_run_id
        assert data["harness_version"] == "1.2.3"
        assert data["behavioral_fingerprint_id"] == "dna_integration_hardened"
        assert "signature_ed25519" in data
        assert data["signing_algorithm"] == "ED25519"
        
        response_invalid = client.get("/api/v1/certificates/non_existent_run")
        assert response_invalid.status_code == 404
        assert "error" in response_invalid.get_json()
        
    finally:
        config.REPORTS_DIR = original_reports
        config.RUN_LOG_DIR = original_runs

def test_certificate_fallback_logic(client, tmp_path):
    """Line 108-111: Verify that the API falls back to both run_ID and ID_manifest formats."""
    # 1. Direct manifest (ID_manifest.json)
    trace_run_id = "run_direct"
    sidecar_path = tmp_path / f"{trace_run_id}_manifest.json"
    sidecar_path.write_text(json.dumps({"run_id": trace_run_id, "status": "success"}))
    
    original_runs = config.RUN_LOG_DIR
    config.RUN_LOG_DIR = tmp_path
    
    try:
        response = client.get(f"/api/v1/certificates/{trace_run_id}")
        assert response.status_code == 200
        assert response.get_json()["run_id"] == trace_run_id
        
        # 2. Prefix manifest (run_ID_manifest.json)
        prefix_run_id = "prefixed"
        prefix_path = tmp_path / f"run_{prefix_run_id}_manifest.json"
        prefix_path.write_text(json.dumps({"run_id": prefix_run_id, "status": "success"}))
        
        response_prefix = client.get(f"/api/v1/certificates/{prefix_run_id}")
        assert response_prefix.status_code == 200
        assert response_prefix.get_json()["run_id"] == prefix_run_id
    finally:
        config.RUN_LOG_DIR = original_runs

def test_certificate_api_error_handling(client, tmp_path):
    """Line 104-105 & 116-117: Verify 500 error when files are corrupt/unreadable."""
    trace_run_id = "corrupt"
    cert_dir = tmp_path / "reports" / "certificates"
    cert_dir.mkdir(parents=True, exist_ok=True)
    
    cert_path = cert_dir / f"{trace_run_id}_vc.json"
    cert_path.write_text("{invalid json}")
    
    original_reports = config.REPORTS_DIR
    config.REPORTS_DIR = tmp_path / "reports"
    
    try:
        # Should return 500 on json parse error
        response = client.get(f"/api/v1/certificates/{trace_run_id}")
        assert response.status_code == 500
        assert "error" in response.get_json()
    finally:
        config.REPORTS_DIR = original_reports
