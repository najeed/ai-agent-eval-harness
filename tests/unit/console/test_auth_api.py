from unittest.mock import MagicMock, patch

import jwt
import pytest
from flask import Flask, jsonify

from eval_runner.console.auth import (
    auth_bp,
    generate_handoff_token,
    get_jwt_secret,
    handoff_required,
)


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
    decoded = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"], audience="agentv-plugin")

    assert decoded["sub"] == "admin-user"
    assert decoded["aud"] == "agentv-plugin"
    assert decoded["scope"] == "console-handoff"
    assert "exp" in decoded


def test_handoff_required_decorator(app):
    """Verify handoff_required enforces token presence and validity (extension API contract)."""

    @app.route("/protected-ext")
    @handoff_required
    def protected():
        return jsonify({"status": "ok"})

    client = app.test_client()

    # 1. Missing token → 401
    resp = client.get("/protected-ext")
    assert resp.status_code == 401
    assert "Handoff token required" in resp.json["error"]

    # 2. Invalid token → 401
    resp = client.get("/protected-ext?token=trash")
    assert resp.status_code == 401
    assert "Invalid token" in resp.json["error"]

    # 3. Valid token via query param → 200
    token = generate_handoff_token()
    resp = client.get(f"/protected-ext?token={token}")
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"

    # 4. Valid token via header → 200
    resp = client.get("/protected-ext", headers={"X-Handoff-Token": token})
    assert resp.status_code == 200


def test_handoff_token_expired(app):
    """Test expired JWT rejection by handoff_required."""

    @app.route("/protected-expired-ext")
    @handoff_required
    def protected_expired():
        return jsonify({"status": "ok"})

    client = app.test_client()
    from datetime import UTC, datetime, timedelta

    payload = {
        "exp": datetime.now(UTC) - timedelta(seconds=10),
        "iat": datetime.now(UTC),
        "sub": "admin-user",
        "aud": "agentv-plugin",
    }
    expired_token = jwt.encode(payload, get_jwt_secret(), algorithm="HS256")
    resp = client.get(f"/protected-expired-ext?token={expired_token}")
    assert resp.status_code == 401
    assert "Token expired" in resp.json["error"]


def test_handoff_endpoint_unauthenticated(client):
    """Anonymous/unauthenticated handoff request must be rejected with 401."""
    resp = client.get("/api/auth/handoff")
    assert resp.status_code == 401
    assert "Unauthorized" in resp.json["error"]


def test_handoff_endpoint_unauthorized_permission(client):
    """Authenticated user without EXTENSIONS_RUN permission must be rejected with 403."""
    with client.session_transaction() as sess:
        sess["user"] = {"id": "viewer-user", "name": "Viewer", "permissions": ["runs:read"]}

    resp = client.post("/api/auth/handoff", json={"plugin_id": "my-extension"})
    assert resp.status_code == 403
    assert "Forbidden" in resp.json["error"]


def test_handoff_endpoint_authenticated_success(client):
    """Authenticated operator with EXTENSIONS_RUN gets a cryptographically signed token."""
    from eval_runner.console.auth_manager import Permission

    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "operator-1",
            "name": "Operator",
            "permissions": [Permission.EXTENSIONS_RUN],
        }

    resp = client.post("/api/auth/handoff", json={"plugin_id": "my-extension"})
    assert resp.status_code == 200
    assert "token" in resp.json
    token = resp.json["token"]
    decoded = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"], audience="agentv-plugin")
    assert decoded["aud"] == "agentv-plugin"
    assert decoded["plugin_id"] == "my-extension"
    assert decoded["sub"] == "operator-1"
    assert decoded["scope"] == "console-handoff"
    assert resp.json["expires_in"] == 900


def test_handoff_endpoint_production_rejects_get(client, monkeypatch):
    """In production, GET /api/auth/handoff must be rejected with 405 (POST required)."""
    from eval_runner.console.auth_manager import Permission

    monkeypatch.setenv("AGENTV_ENV", "production")
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "operator-1",
            "name": "Operator",
            "permissions": [Permission.EXTENSIONS_RUN],
        }

    resp = client.get("/api/auth/handoff")
    assert resp.status_code == 405
    assert "POST required" in resp.json["error"]


def test_handoff_endpoint_invalid_plugin_id(client):
    """Invalid plugin_id format must be rejected with 400."""
    from eval_runner.console.auth_manager import Permission

    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "operator-1",
            "name": "Operator",
            "permissions": [Permission.EXTENSIONS_RUN],
        }

    resp = client.post("/api/auth/handoff", json={"plugin_id": "../../malicious/path"})
    assert resp.status_code == 400
    assert "Invalid plugin_id format" in resp.json["error"]


def test_handoff_required_production_rejects_query_token(app, monkeypatch):
    """In production, query-string token in handoff_required must be rejected."""
    monkeypatch.setenv("AGENTV_ENV", "production")

    @app.route("/protected-prod-ext")
    @handoff_required
    def protected_prod():
        return jsonify({"status": "ok"})

    client = app.test_client()
    token = generate_handoff_token()
    resp = client.get(f"/protected-prod-ext?token={token}")
    assert resp.status_code == 400
    assert "Query parameter tokens are disabled in production" in resp.json["error"]


def test_handoff_required_plugin_binding_and_scope(app):
    """handoff_required validates plugin_id binding and scope."""

    @app.route("/protected-plugin-ext")
    @handoff_required(plugin_id="expected-plugin")
    def protected_plugin():
        return jsonify({"status": "ok"})

    client = app.test_client()

    # Mismatched plugin token -> 403
    token_wrong_plugin = generate_handoff_token(plugin_id="different-plugin")
    resp = client.get("/protected-plugin-ext", headers={"X-Handoff-Token": token_wrong_plugin})
    assert resp.status_code == 403
    assert "PluginIdMismatch" in resp.json["error"]

    # Matching plugin token -> 200
    token_correct = generate_handoff_token(plugin_id="expected-plugin")
    resp = client.get("/protected-plugin-ext", headers={"X-Handoff-Token": token_correct})
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"


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


@patch("eval_runner.console.auth_manager.get_auth_provider")
def test_login_rate_limiting(mock_get_provider, client):
    """Test that failed login attempts from an IP are rate limited to 10 per 60s."""
    from eval_runner.console.auth import _FAILED_LOGIN_ATTEMPTS, _LOGIN_ATTEMPT_LOCK

    with _LOGIN_ATTEMPT_LOCK:
        _FAILED_LOGIN_ATTEMPTS.clear()

    mock_provider = MagicMock()
    mock_provider.authenticate.return_value = None
    mock_get_provider.return_value = mock_provider

    # 10 failed attempts should be allowed (returning 401)
    for _ in range(10):
        resp = client.post("/api/auth/login", json={"apiKey": "bad-key"})
        assert resp.status_code == 401

    # 11th attempt must be rate-limited with HTTP 429
    resp_blocked = client.post("/api/auth/login", json={"apiKey": "bad-key"})
    assert resp_blocked.status_code == 429
    assert "Too many failed login attempts" in resp_blocked.json["error"]
    assert "retry_after_seconds" in resp_blocked.json

    # A valid authentication resets the tracker
    mock_provider.authenticate.return_value = {
        "name": "Operator",
        "id": "op-1",
        "permissions": ["*"],
    }
    with _LOGIN_ATTEMPT_LOCK:
        _FAILED_LOGIN_ATTEMPTS.clear()

    resp_valid = client.post("/api/auth/login", json={"apiKey": "valid-key"})
    assert resp_valid.status_code == 200
