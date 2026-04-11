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


def test_public_verify_endpoint_v3(client, tmp_path, monkeypatch):
    """
    Integration Test: Verify that the /v1/verify/<run_id> endpoint correctly
    verifies a trace within the Run ID vault.
    """
    # 1. Setup - Create a real vault-aligned run
    run_id = "v3-verify-it"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text('{"event": "test"}', encoding="utf-8")

    # Setup identity
    identity_id = "system_id"
    keys_dir = tmp_path / "keys" / identity_id
    TraceVerifier.generate_key_pair(output_dir=str(keys_dir))

    # Configure Environment
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "keys")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")

    # 2. Sign the trace
    TraceVerifier.sign_trace(trace_path=str(trace_path), run_id=run_id)

    # 3. Test API Verification (New /v1/ Path)
    response = client.get(f"/v1/verify/{run_id}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["run_id"] == run_id
    assert data["verified"] is True
    assert "ED25519" in data["method"]

    # 4. Test tampered trace
    trace_path.write_text('{"event": "tampered"}', encoding="utf-8")
    response_tampered = client.get(f"/v1/verify/{run_id}")
    assert response_tampered.status_code == 200
    assert response_tampered.get_json()["verified"] is False

    # 5. Test non-existent run
    response_missing = client.get("/v1/verify/missing_run")
    assert response_missing.status_code == 404
