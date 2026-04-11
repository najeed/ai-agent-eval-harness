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


def test_public_certificate_endpoint_v3(client, tmp_path, monkeypatch):
    """
    Integration Test: Verify that the /v1/certificates endpoint is public
    and returns a valid, signed VC v3.0.0.
    """
    # 1. Setup - Create a real vault-aligned run
    run_id = "run-v3-integration"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    trace_path = run_dir / "run.jsonl"
    trace_path.write_bytes(b"integration test trace data v3")

    # Setup identity
    identity_id = "it_identity"
    keys_dir = tmp_path / "keys" / identity_id
    TraceVerifier.generate_key_pair(output_dir=str(keys_dir))

    # Configure Environment
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "keys")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")

    # 2. Sign the trace
    TraceVerifier.sign_trace(trace_path=str(trace_path), identity_id=identity_id, run_id=run_id)

    # 3. Test API Retrieval (New /v1/ Path)
    response = client.get(f"/v1/certificates/{run_id}")

    assert response.status_code == 200
    data = response.get_json()

    assert data["run_id"] == run_id
    assert data["vc_version"] == "3.0.0"
    assert "provenance_chain" in data
    assert data["provenance_chain"][0]["identity"] == identity_id

    # 4. Error Handling
    response_invalid = client.get("/v1/certificates/non_existent_run")
    assert response_invalid.status_code == 404


def test_certificate_vault_resolution(client, tmp_path, monkeypatch):
    """Verify that the API resolves manifests from the Run ID vault."""
    run_id = "vault-resolved"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)

    # Create manifest directly in vault
    manifest_data = {
        "vc_version": "3.0.0",
        "run_id": run_id,
        "status": "success",
        "provenance_chain": [],  # Minimal for retrieval test
    }
    manifest_path = run_dir / "run_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest_data, f)

    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    response = client.get(f"/v1/certificates/{run_id}")
    assert response.status_code == 200
    assert response.get_json()["run_id"] == run_id


def test_certificate_api_error_handling(client, tmp_path, monkeypatch):
    """Verify 500 error when files are corrupt."""
    run_id = "corrupt-v3"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)

    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text("{invalid json}")

    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    response = client.get(f"/v1/certificates/{run_id}")
    assert response.status_code == 500
