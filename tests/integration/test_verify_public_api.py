import pytest

from eval_runner import config
from eval_runner.console.app import create_app
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.verifier import TraceVerifier


@pytest.fixture
def app_and_store(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    run_store = LocalFileRunStore(runs_dir)

    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "keys")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")

    app = create_app(run_store=run_store)
    app.config["TESTING"] = True
    return app, run_store


@pytest.fixture
def client(app_and_store):
    app, _ = app_and_store
    with app.test_client() as client:
        yield client


def test_public_verify_endpoint_v3(app_and_store, client, tmp_path):
    """
    Integration Test: Verify that the /v1/verify/<run_id> endpoint correctly
    verifies a trace within the Run ID vault using provider-native verification.
    """
    _, run_store = app_and_store
    run_id = "v3-verify-it"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text('{"event": "test"}\n', encoding="utf-8")

    identity_id = "system_id"
    keys_dir = tmp_path / "keys" / identity_id
    TraceVerifier.generate_key_pair(output_dir=str(keys_dir))

    scenario = {
        "id": "v3-verify-scenario",
        "version": "1.0.0",
        "required_oracle_ids": ["fixture:direct_oracle"],
    }
    import json

    (run_dir / "scenario_resolved.json").write_text(json.dumps(scenario), encoding="utf-8")
    run_store.create_run(run_id, "v3-verify-scenario")

    from tests.conftest import append_authoritative_finalization

    append_authoritative_finalization(trace_path, run_id, run_dir)
    trace_bytes = run_store.get_trace_bytes(run_id) or trace_path.read_bytes()

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        execution_mode="live",
        run_store=run_store,
        identity_id=identity_id,
        scenario_data=scenario,
    )
    run_store.save_run_manifest(run_id, manifest)
    run_store.update_run_status(run_id, "SEALED")

    response = client.get(f"/v1/verify/{run_id}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["run_id"] == run_id
    assert data["verified"] is True
    assert "ED25519" in data["method"]

    # Tampered trace
    trace_path.write_text('{"event": "tampered"}\n', encoding="utf-8")
    response_tampered = client.get(f"/v1/verify/{run_id}")
    assert response_tampered.status_code == 200
    assert response_tampered.get_json()["verified"] is False

    # Missing run
    response_missing = client.get("/v1/verify/missing_run")
    assert response_missing.status_code == 404
