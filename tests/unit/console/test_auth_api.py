from unittest.mock import MagicMock, patch

import jwt
import pytest
from flask import Flask, jsonify

from eval_runner.console.auth import SECRET_KEY, auth_bp, generate_handoff_token, handoff_required


@pytest.fixture
def app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(auth_bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_generate_handoff_token():
    """Test token generation and payload structure."""
    token = generate_handoff_token()
    decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"], audience="agentv-plugin")

    assert decoded["sub"] == "admin-user"
    assert decoded["aud"] == "agentv-plugin"
    assert decoded["scope"] == "console-handoff"
    assert "exp" in decoded


def test_handoff_required_decorator(app):
    """Test the handoff_required decorator with varied inputs."""

    @app.route("/protected")
    @handoff_required
    def protected():
        return jsonify({"status": "ok"})

    client = app.test_client()

    # 1. Missing token
    resp = client.get("/protected")
    assert resp.status_code == 401
    assert "Handoff token required" in resp.json["error"]

    # 2. Invalid token
    resp = client.get("/protected?token=trash")
    assert resp.status_code == 401
    assert "Invalid token" in resp.json["error"]

    # 3. Valid token
    token = generate_handoff_token()
    resp = client.get(f"/protected?token={token}")
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"

    # 4. Valid token in header
    resp = client.get("/protected", headers={"X-Handoff-Token": token})
    assert resp.status_code == 200


def test_handoff_token_expired(app):
    """Test expired JWT handling."""

    @app.route("/protected_expired")
    @handoff_required
    def protected():
        return jsonify({"status": "ok"})

    client = app.test_client()

    # Generate token that expired 10s ago
    from datetime import UTC, datetime, timedelta

    payload = {
        "exp": datetime.now(UTC) - timedelta(seconds=10),
        "iat": datetime.now(UTC),
        "sub": "admin-user",
        "aud": "agentv-plugin",
    }
    expired_token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    resp = client.get(f"/protected_expired?token={expired_token}")
    assert resp.status_code == 401
    assert "Token expired" in resp.json["error"]


def test_handoff_endpoint(client):
    """Test the /handoff endpoint for token retrieval."""
    resp = client.get("/api/auth/handoff")
    assert resp.status_code == 200
    assert "token" in resp.json
    token = resp.json["token"]
    decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"], audience="agentv-plugin")
    assert decoded["aud"] == "agentv-plugin"


def test_auth_me_endpoint(client):
    """Test the /api/auth/me endpoint for server-authoritative session."""
    with patch("eval_runner.config.ENABLE_DEMO", True):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json
        assert data["authenticated"] is True
        assert "user" in data
        assert "role" in data["user"]
        assert "permissions" in data["user"]


@patch("eval_runner.console.auth_manager.get_auth_provider")
def test_login_success(mock_get_provider, client):
    """Test successful login via PBAC provider."""
    mock_provider = MagicMock()
    mock_provider.authenticate.return_value = {
        "name": "Najeed",
        "id": "admin",
        "permissions": ["all"],
    }
    mock_get_provider.return_value = mock_provider

    resp = client.post("/api/auth/login", json={"apiKey": "valid-key"})
    assert resp.status_code == 200
    assert resp.json["status"] == "success"
    assert resp.json["user"]["name"] == "Najeed"


def test_login_missing_key(client):
    """Test login with missing API key."""
    resp = client.post("/api/auth/login", json={})
    assert resp.status_code == 400
    assert "Missing API Key" in resp.json["error"]


@patch("eval_runner.console.auth_manager.get_auth_provider")
def test_login_unauthorized(mock_get_provider, client):
    """Test login with invalid API key."""
    mock_provider = MagicMock()
    mock_provider.authenticate.return_value = None
    mock_get_provider.return_value = mock_provider

    resp = client.post("/api/auth/login", json={"apiKey": "wrong-key"})
    assert resp.status_code == 401
    assert "Invalid API Key" in resp.json["error"]


def test_auth_secret_and_token_branches():
    """Test dynamic JWT secret resolution and handoff token generation."""
    from eval_runner import config
    from eval_runner.console.auth import generate_handoff_token, get_jwt_secret

    with patch.object(config, "JWT_SECRET", "custom_secret_123", create=True):
        assert get_jwt_secret() == "custom_secret_123"

    with (
        patch.object(config, "JWT_SECRET", None, create=True),
        patch.dict("os.environ", {"JWT_SECRET": "env_secret_456"}),
    ):
        assert get_jwt_secret() == "env_secret_456"

    tok = generate_handoff_token("user-1", "admin", "custom-plugin")
    assert isinstance(tok, str)
