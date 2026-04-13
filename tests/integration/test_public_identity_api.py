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


def test_public_identity_resolution(client, tmp_path, monkeypatch):
    """
    Integration Test: Verify that the /v1/identity/<id>/public_key endpoint
    is public and correctly resolves keys.
    """
    # 1. Setup - Create an identity
    identity_id = "public-test-id"
    keys_dir = tmp_path / "keys" / identity_id
    TraceVerifier.generate_key_pair(output_dir=str(keys_dir))

    # Configure Environment
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "keys")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    # 2. Test API Retrieval (Without Auth Headers)
    # The /v1/ namespace should be unprotected in trust_bp
    response = client.get(f"/v1/identity/{identity_id}/public_key")

    assert response.status_code == 200
    data = response.get_json()

    assert data["identity_id"] == identity_id
    assert "public_key" in data
    assert "BEGIN PUBLIC KEY" in data["public_key"]


def test_public_identity_not_found(client, tmp_path, monkeypatch):
    """Verify 404 for non-existent identities."""
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "keys")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    response = client.get("/v1/identity/missing_identity/public_key")
    assert response.status_code == 404
