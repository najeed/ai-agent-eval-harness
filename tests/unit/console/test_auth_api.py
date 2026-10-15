from unittest.mock import MagicMock, patch

import jwt
import pytest
from flask import Flask, jsonify, request

from eval_runner.console.auth import (
    auth_bp,
    generate_handoff_token,
    get_jwt_secret,
    handoff_required,
)
from eval_runner.console.auth_manager import (
    Permission,
    StaticKeyProvider,
    require_permission,
    require_sse_permission,
)
from eval_runner.console.routes.runs import run_bp
from eval_runner.reference.auth import SimpleAPIKeyAuthBackend


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


def test_configured_backend_wildcard_permissions_survive_me_handoff_and_extension_gate(
    app, client, monkeypatch
):
    """A backend wildcard is a provider claim, not Core's finite admin list."""
    backend = SimpleAPIKeyAuthBackend(master_key="configured-backend-root")
    backend.register_key(
        key="configured-wildcard",
        principal_id="configured-admin",
        roles=["configured-admin"],
        permissions=["*"],
    )
    provider = StaticKeyProvider("legacy-root-key", backend=backend)
    principal = provider.authenticate("configured-wildcard")
    assert principal is not None
    assert principal["permissions"] == ["*"]

    @app.route("/generic-extension-permission")
    @require_permission("enterprise.triage.read")
    def generic_extension_permission():
        return jsonify({"authorized": True})

    with client.session_transaction() as sess:
        sess["user"] = principal

    # /me reads the stored verified claim without replacing it.
    assert client.get("/api/auth/me").json["user"]["permissions"] == ["*"]
    monkeypatch.delenv("AGENTV_TEST_AUTH_BYPASS", raising=False)
    with patch("eval_runner.console.auth_manager.get_auth_provider", return_value=provider):
        handoff = client.post("/api/auth/handoff", json={"plugin_id": "generic-extension"})
        assert handoff.status_code == 200
        decoded = jwt.decode(
            handoff.json["token"], get_jwt_secret(), algorithms=["HS256"], audience="agentv-plugin"
        )
        assert decoded["permissions"] == ["*"]
        assert client.get("/generic-extension-permission").json == {"authorized": True}


def test_configured_backend_limited_permissions_and_static_root_are_distinct(
    app, client, monkeypatch
):
    """Configured claims remain exact; only legacy static-root expands to Core permissions."""
    backend = SimpleAPIKeyAuthBackend(master_key="configured-backend-root")
    backend.register_key(
        key="configured-limited",
        principal_id="configured-limited-user",
        permissions=[Permission.EXTENSIONS_RUN, "enterprise.reports.read"],
    )
    provider = StaticKeyProvider("legacy-root-key", backend=backend)
    principal = provider.authenticate("configured-limited")
    assert principal is not None
    assert principal["permissions"] == [Permission.EXTENSIONS_RUN, "enterprise.reports.read"]
    assert provider.has_permission(principal, "enterprise.triage.read") is False

    @app.route("/limited-extension-permission")
    @require_permission("enterprise.triage.read")
    def limited_extension_permission():
        return jsonify({"authorized": True})

    with client.session_transaction() as sess:
        sess["user"] = principal
    assert client.get("/api/auth/me").json["user"]["permissions"] == principal["permissions"]
    monkeypatch.delenv("AGENTV_TEST_AUTH_BYPASS", raising=False)
    with patch("eval_runner.console.auth_manager.get_auth_provider", return_value=provider):
        assert client.get("/limited-extension-permission").status_code == 403

    static_root = StaticKeyProvider("legacy-static-root").authenticate("legacy-static-root")
    assert static_root is not None
    assert static_root["type"] == "static-root"
    assert static_root["permissions"] == Permission.ADMIN()
    assert "*" not in static_root["permissions"]


def test_handoff_propagates_only_verified_principal_context(client):
    """Request data cannot override the session's verified identity or tenant scope."""
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "operator-1",
            "email": "operator@example.com",
            "roles": ["operator"],
            "permissions": [Permission.EXTENSIONS_RUN],
            "org_id": "org-verified",
            "tenant_id": "tenant-verified",
            "workspace_id": "workspace-verified",
            "active_environment": "prod",
        }

    response = client.post(
        "/api/auth/handoff",
        json={
            "plugin_id": "my-extension",
            "roles": ["admin"],
            "permissions": ["*"],
            "tenant_id": "tenant-attacker",
            "workspace_id": "workspace-attacker",
        },
        headers={"X-Tenant-Id": "tenant-header-attacker"},
    )
    assert response.status_code == 200
    decoded = jwt.decode(
        response.json["token"], get_jwt_secret(), algorithms=["HS256"], audience="agentv-plugin"
    )
    assert decoded["sub"] == "operator-1"
    assert decoded["roles"] == ["operator"]
    assert decoded["permissions"] == [Permission.EXTENSIONS_RUN]
    assert decoded["org_id"] == "org-verified"
    assert decoded["tenant_id"] == "tenant-verified"
    assert decoded["workspace_id"] == "workspace-verified"
    assert decoded["active_environment"] == "prod"


def test_sse_contract_uses_session_and_rejects_url_credentials_and_tenant_context(app, monkeypatch):
    """EventSource-style session auth retains replay headers but refuses URL secrets/context."""
    monkeypatch.delenv("AGENTV_TEST_AUTH_BYPASS", raising=False)

    @app.route("/events")
    @require_sse_permission(Permission.RUNS_READ)
    def events():
        return jsonify({"last_event_id": request.headers.get("Last-Event-ID")})

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user"] = {"id": "viewer", "permissions": [Permission.RUNS_READ]}

    good = client.get("/events", headers={"Last-Event-ID": "42"})
    assert good.status_code == 200
    assert good.json["last_event_id"] == "42"
    assert client.get("/events?token=secret").status_code == 400
    assert client.get("/events?tenant_id=other-tenant").status_code == 400


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
    # A real production deployment always has a stable signing secret.
    # Provide one alongside AGENTV_ENV=production so get_jwt_secret() doesn't
    # raise before we reach the query-token rejection logic under test.
    monkeypatch.setenv("JWT_SECRET", "stable-test-secret-for-production-mode")
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


def test_auth_me_returns_allowlisted_verified_context_without_secrets(client):
    """The context read model is session-authoritative and credential-free."""
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "operator-1",
            "email": "operator@example.com",
            "name": "Operator",
            "roles": ["operator"],
            "permissions": [Permission.RUNS_READ],
            "org_id": "org-verified",
            "tenant_id": "tenant-verified",
            "workspace_id": "workspace-verified",
            "active_environment": "production",
            "access_token": "must-not-leak",
            "api_key": "must-not-leak",
        }

    response = client.get(
        "/api/auth/me?tenant_id=tenant-attacker",
        headers={"X-Tenant-Id": "tenant-header-attacker"},
    )
    assert response.status_code == 200
    body = response.json
    assert body["authenticated"] is True
    assert body["context_version"] == "2"
    assert body["context"] == {
        "org_id": "org-verified",
        "tenant_id": "tenant-verified",
        "workspace_id": "workspace-verified",
        "active_environment": "production",
    }
    assert body["user"]["email"] == "operator@example.com"
    assert body["user"]["roles"] == ["operator"]
    assert body["user"]["tenant_id"] == "tenant-verified"
    assert "access_token" not in body["user"]
    assert "api_key" not in body["user"]


def test_auth_me_unauthenticated_response_remains_compatible(client, monkeypatch):
    monkeypatch.setattr("eval_runner.config.ENABLE_DEMO", False)
    monkeypatch.setenv("DEV_PERSONA_SIMULATOR", "false")
    response = client.get("/api/auth/me", environ_base={"REMOTE_ADDR": "192.0.2.1"})
    assert response.status_code == 200
    assert response.json == {"authenticated": False, "user": None, "is_dev_mode": False}


@patch("eval_runner.console.auth_manager.get_auth_provider")
def test_auth_me_bearer_principal_exposes_normalized_oidc_context(mock_get_provider, client):
    provider = MagicMock()
    provider.verify_token.return_value = {
        "id": "oidc-operator",
        "email": "oidc@example.com",
        "roles": ["auditor"],
        "permissions": [Permission.CERTIFY_WRITE],
        "org_id": "org-oidc",
        "tenant_id": "tenant-oidc",
        "workspace_id": "workspace-oidc",
        "active_environment": "staging",
        "type": "oidc-sso",
    }
    mock_get_provider.return_value = provider

    response = client.get("/api/auth/me", headers={"Authorization": "Bearer verified-oidc-token"})
    assert response.status_code == 200
    assert response.json["user"]["role"] == "Compliance Auditor"
    assert response.json["user"]["roles"] == ["auditor"]
    assert response.json["context"]["tenant_id"] == "tenant-oidc"
    provider.verify_token.assert_called_once_with("verified-oidc-token")


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


def test_context_switch_is_entitlement_authorized_and_revokes_stale_handoff(client):
    @client.application.route("/stale-handoff")
    @handoff_required
    def stale_handoff():
        return jsonify({"ok": True})

    user = {
        "id": "operator",
        "permissions": [Permission.EXTENSIONS_RUN],
        "roles": ["configured-role"],
        "context_version": "2",
        "context": {
            "org_id": "org-a",
            "tenant_id": "tenant-a",
            "workspace_id": "ws-a",
            "active_environment": "staging",
        },
        "authorized_contexts": [
            {
                "org_id": "org-a",
                "tenant_id": "tenant-a",
                "workspace_id": "ws-a",
                "environments": ["staging", "sandbox"],
            },
            {
                "org_id": "org-b",
                "tenant_id": "tenant-b",
                "workspace_id": "ws-b",
                "environments": ["production"],
            },
        ],
    }
    with client.session_transaction() as sess:
        sess["user"] = user
    old = client.post("/api/auth/handoff", json={"plugin_id": "extension"}).json["token"]
    assert (
        client.post(
            "/api/auth/context", json={"workspace_id": "ws-b", "active_environment": "staging"}
        ).status_code
        == 403
    )
    assert client.get("/api/auth/me").json["context"]["tenant_id"] == "tenant-a"
    assert (
        client.post(
            "/api/auth/context",
            json={
                "workspace_id": "ws-b",
                "active_environment": "production",
                "tenant_id": "attacker",
            },
        ).status_code
        == 400
    )
    changed = client.post(
        "/api/auth/context", json={"workspace_id": "ws-b", "active_environment": "production"}
    )
    assert changed.status_code == 200
    assert changed.json["context"]["tenant_id"] == "tenant-b"

    assert client.get("/stale-handoff", headers={"X-Handoff-Token": old}).status_code == 401
    new = client.post("/api/auth/handoff", json={"plugin_id": "extension"}).json["token"]
    decoded = jwt.decode(new, get_jwt_secret(), algorithms=["HS256"], audience="agentv-plugin")
    assert decoded["tenant_id"] == "tenant-b"
    assert decoded["roles"] == ["configured-role"]


def test_malformed_entitlements_fail_closed(client):
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "bad",
            "permissions": [],
            "context_version": "2",
            "context": {},
            "authorized_contexts": [],
        }
    assert client.get("/api/auth/me").status_code == 403


def test_duplicate_entitlement_tuple_fails_closed(client):
    context = {"org_id": "o", "tenant_id": "t", "workspace_id": "w", "active_environment": "dev"}
    entry = {"org_id": "o", "tenant_id": "t", "workspace_id": "w", "environments": ["dev"]}
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "bad",
            "permissions": [],
            "context_version": "2",
            "context": context,
            "authorized_contexts": [entry, dict(entry)],
        }
    assert client.get("/api/auth/me").status_code == 403


def test_cross_tenant_run_read_is_non_enumerating(client, app, tmp_path, monkeypatch):
    """A verified tenant cannot learn whether another tenant's run exists."""
    app.register_blueprint(run_bp)
    run_dir = tmp_path / "cross-tenant-run"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text(
        '{"metadata":{"runtime_context":{"org_id":"other-org","tenant_id":"other-tenant","workspace_id":"other-workspace","active_environment":"production"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("eval_runner.console.routes.runs.config.RUN_LOG_DIR", tmp_path)
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "operator",
            "permissions": [Permission.RUNS_READ],
            "context_version": "2",
            "context": {
                "org_id": "org",
                "tenant_id": "tenant",
                "workspace_id": "workspace",
                "active_environment": "staging",
            },
            "authorized_contexts": [
                {
                    "org_id": "org",
                    "tenant_id": "tenant",
                    "workspace_id": "workspace",
                    "environments": ["staging"],
                }
            ],
        }
    response = client.get(
        "/v1/runs/cross-tenant-run?tenant_id=other-tenant", headers={"X-Tenant-Id": "other-tenant"}
    )
    assert response.status_code == 404


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


def test_has_configured_authorization_backend_and_service_credentials(monkeypatch):
    """
    Verifies configured authorization backend detection and service credential resolution
    across StaticKeyProvider and environment/backend delegations.
    """
    from eval_runner.console.auth_manager import (
        StaticKeyProvider,
        has_configured_authorization_backend,
        register_authorization_backend,
    )
    from eval_runner.reference.auth import SimpleAPIKeyAuthBackend

    try:
        # Reset any globally registered backend
        register_authorization_backend(None)
        monkeypatch.delenv("AGENTV_AUTHORIZATION_BACKEND_FACTORY", raising=False)
        assert has_configured_authorization_backend() is False

        # Factory env var triggers detection
        monkeypatch.setenv("AGENTV_AUTHORIZATION_BACKEND_FACTORY", "some.package:factory")
        assert has_configured_authorization_backend() is True

        monkeypatch.delenv("AGENTV_AUTHORIZATION_BACKEND_FACTORY", raising=False)
        backend = SimpleAPIKeyAuthBackend(master_key="backend-srv-key-42")
        register_authorization_backend(backend)
        assert has_configured_authorization_backend() is True

        # StaticKeyProvider with configured backend
        provider_with_backend = StaticKeyProvider("fallback-static-key", backend=backend)
        assert provider_with_backend.get_service_credential() == "backend-srv-key-42"

        # StaticKeyProvider without configured backend falls back to key / env
        monkeypatch.delenv("SERVICE_API_KEY", raising=False)
        monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
        provider_plain = StaticKeyProvider("my-static-key")
        assert provider_plain.get_service_credential() == "my-static-key"
    finally:
        register_authorization_backend(None)


def test_get_jwt_secret_fallbacks_and_module_getattr(monkeypatch):
    import eval_runner.console.auth as auth_mod
    from eval_runner import config

    # 1. SERVICE_API_KEY fallback
    monkeypatch.setattr(config, "JWT_SECRET", None)
    monkeypatch.setattr(config, "DASHBOARD_API_KEY", None)
    monkeypatch.setattr(config, "SERVICE_API_KEY", "service-key-123")
    assert auth_mod.get_jwt_secret() == "service-key-123"

    # 2. Production fail-loud when no secrets configured
    monkeypatch.setattr(config, "SERVICE_API_KEY", None)
    monkeypatch.setattr(config, "is_production", lambda: True)
    with pytest.raises(RuntimeError, match="requires a stable signing secret"):
        auth_mod.get_jwt_secret()

    # 3. Ephemeral secret warning when not production
    monkeypatch.setattr(config, "is_production", lambda: False)
    ephemeral = auth_mod.get_jwt_secret()
    assert ephemeral == auth_mod._EPHEMERAL_SECRET

    # 4. __getattr__ module property access
    monkeypatch.setattr(config, "JWT_SECRET", "test-secret-456")
    assert auth_mod.SECRET_KEY == "test-secret-456"
    with pytest.raises(AttributeError, match="has no attribute 'UNKNOWN_ATTR'"):
        _ = auth_mod.UNKNOWN_ATTR


def test_require_handoff_token_bearer_and_scope_validation(app):
    from eval_runner.console.auth import generate_handoff_token, handoff_required

    @app.route("/api/test/scoped-handoff")
    @handoff_required(scope="operator-gate")
    def scoped_handoff():
        return jsonify({"status": "ok"})

    client = app.test_client()

    # Bearer header with wrong scope
    token_wrong_scope = generate_handoff_token(sub="op-1")
    resp_wrong = client.get(
        "/api/test/scoped-handoff",
        headers={"Authorization": f"Bearer {token_wrong_scope}"},
    )
    assert resp_wrong.status_code == 403
    assert "Invalid token scope" in resp_wrong.json["error"]

    # Bearer header with matching scope
    import datetime

    from eval_runner.console.auth import get_jwt_secret

    now = datetime.datetime.now(datetime.UTC)
    token_valid = jwt.encode(
        {
            "exp": now + datetime.timedelta(seconds=900),
            "iat": now,
            "sub": "op-1",
            "aud": "agentv-plugin",
            "plugin_id": "control-plane",
            "scope": "operator-gate",
            "jti": "custom-jti-123",
        },
        get_jwt_secret(),
        algorithm="HS256",
    )
    resp_valid = client.get(
        "/api/test/scoped-handoff",
        headers={"Authorization": f"Bearer {token_valid}"},
    )
    assert resp_valid.status_code == 200

    # In dev mode, query parameter when header is also passed
    resp_both = client.get(
        f"/api/test/scoped-handoff?token={token_wrong_scope}",
        headers={"X-Handoff-Token": token_valid},
    )
    assert resp_both.status_code == 200


def test_handoff_token_endpoint_bearer_and_api_key_credentials(client, monkeypatch):
    from eval_runner.console.auth_manager import (
        Permission,
    )

    valid_user = {
        "id": "operator-user",
        "permissions": [Permission.EXTENSIONS_RUN],
        "roles": ["Operator"],
        "context_version": "2",
        "org_id": "test-org",
        "tenant_id": "test-tenant",
        "workspace_id": "test-ws",
        "active_environment": "dev",
        "authorized_contexts": [
            {
                "org_id": "test-org",
                "tenant_id": "test-tenant",
                "workspace_id": "test-ws",
                "environments": ["dev"],
            }
        ],
    }

    mock_provider = MagicMock()
    mock_provider.verify_token.return_value = valid_user
    mock_provider.authenticate.return_value = valid_user
    mock_provider.has_permission.return_value = True
    monkeypatch.setattr("eval_runner.console.auth_manager.get_auth_provider", lambda: mock_provider)

    # 1. Authenticate with Authorization: Bearer token
    resp_bearer = client.post(
        "/api/auth/handoff",
        headers={"Authorization": "Bearer sample-bearer-token"},
        json={"plugin_id": "control-plane"},
    )
    assert resp_bearer.status_code == 200
    assert "token" in resp_bearer.json

    # 2. Authenticate with X-API-Key
    resp_key = client.post(
        "/api/auth/handoff",
        headers={"X-API-Key": "sample-api-key"},
        json={"plugin_id": "control-plane"},
    )
    assert resp_key.status_code == 200

    # 3. Principal with invalid entitlements
    invalid_ent_provider = MagicMock()
    invalid_ent_provider.authenticate.return_value = {
        "id": "bad-ent",
        "permissions": [Permission.EXTENSIONS_RUN],
        "authorized_contexts": "not-a-list",
    }
    monkeypatch.setattr(
        "eval_runner.console.auth_manager.get_auth_provider",
        lambda: invalid_ent_provider,
    )
    resp_inv = client.post(
        "/api/auth/handoff",
        headers={"X-API-Key": "any-key"},
    )
    assert resp_inv.status_code == 403


def test_auth_me_api_key_header_and_role_derivation(client, monkeypatch):
    from eval_runner.console.auth_manager import (
        Permission,
    )

    api_key = "api-designer-key"
    mock_designer_provider = MagicMock()
    mock_designer_provider.authenticate.return_value = {
        "id": "designer-user",
        # Pass permissions as string and roles as string to test normalization
        "permissions": str(Permission.SCENARIOS_WRITE),
        "roles": "DesignerRole",
        "context_version": "2",
        "org_id": "test-org",
        "tenant_id": "test-tenant",
        "workspace_id": "test-ws",
        "active_environment": "dev",
        "authorized_contexts": [
            {
                "org_id": "test-org",
                "tenant_id": "test-tenant",
                "workspace_id": "test-ws",
                "environments": ["dev"],
            }
        ],
    }
    monkeypatch.setattr(
        "eval_runner.console.auth_manager.get_auth_provider",
        lambda: mock_designer_provider,
    )

    resp = client.get("/api/auth/me", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    data = resp.json
    assert data["authenticated"] is True
    assert data["user"]["role"] == "Scenario Designer"
    assert data["user"]["roles"] == ["DesignerRole"]


def test_auth_context_and_logout_edge_cases(client, monkeypatch):
    # 1. Context switch without active session
    resp_unauth = client.post(
        "/api/auth/context",
        json={"workspace_id": "ws-1", "active_environment": "dev"},
    )
    assert resp_unauth.status_code == 401

    # 2. Context switch with non-string identifiers
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "usr-1",
            "context_version": "2",
            "org_id": "org-1",
            "tenant_id": "tenant-1",
            "workspace_id": "ws-1",
            "active_environment": "dev",
            "authorized_contexts": [
                {
                    "org_id": "org-1",
                    "tenant_id": "tenant-1",
                    "workspace_id": "ws-1",
                    "environments": ["dev"],
                }
            ],
        }

    resp_bad_type = client.post(
        "/api/auth/context",
        json={"workspace_id": 12345, "active_environment": "dev"},
    )
    assert resp_bad_type.status_code == 400

    # 3. Context switch with invalid entitlement structure in session
    with client.session_transaction() as sess:
        sess["user"] = {"id": "usr-bad", "authorized_contexts": 99999}
    resp_bad_ent = client.post(
        "/api/auth/context",
        json={"workspace_id": "ws-1", "active_environment": "dev"},
    )
    assert resp_bad_ent.status_code == 403

    # 4. Logout endpoint
    resp_logout = client.post("/api/auth/logout")
    assert resp_logout.status_code == 200
    assert resp_logout.json["status"] == "success"

    # 5. Login endpoint with invalid entitlements
    mock_bad_login_provider = MagicMock()
    mock_bad_login_provider.authenticate.return_value = {
        "id": "bad-ent-user",
        "authorized_contexts": "non-list-structure",
    }
    monkeypatch.setattr(
        "eval_runner.console.auth_manager.get_auth_provider",
        lambda: mock_bad_login_provider,
    )
    resp_bad_login = client.post("/api/auth/login", json={"apiKey": "bad-key"})
    assert resp_bad_login.status_code == 403


class TestAuthManagerExhaustiveCoverage:
    def test_normalize_entitlements_validation_branches(self):
        from eval_runner.console.auth_manager import normalize_entitlements

        # 1. Missing active context fields
        with pytest.raises(ValueError, match="invalid active entitlement context"):
            normalize_entitlements(
                {
                    "context_version": "2",
                    "context": {"org_id": "org1", "tenant_id": "ten1"},
                    "authorized_contexts": [
                        {
                            "org_id": "org1",
                            "tenant_id": "ten1",
                            "workspace_id": "ws1",
                            "environments": ["dev"],
                        }
                    ],
                }
            )

        # 2. Malformed entry keys in authorized_contexts
        with pytest.raises(ValueError, match="malformed authorized context"):
            normalize_entitlements(
                {
                    "context_version": "2",
                    "context": {
                        "org_id": "org1",
                        "tenant_id": "ten1",
                        "workspace_id": "ws1",
                        "active_environment": "dev",
                    },
                    "authorized_contexts": [
                        {
                            "org_id": "org1",
                            "tenant_id": "ten1",
                        }
                    ],
                }
            )

        # 3. Active environment not in authorized list
        with pytest.raises(ValueError, match="active context is not authorized"):
            normalize_entitlements(
                {
                    "context_version": "2",
                    "context": {
                        "org_id": "org1",
                        "tenant_id": "ten1",
                        "workspace_id": "ws1",
                        "active_environment": "prod",
                    },
                    "authorized_contexts": [
                        {
                            "org_id": "org1",
                            "tenant_id": "ten1",
                            "workspace_id": "ws1",
                            "environments": ["dev"],
                        }
                    ],
                }
            )

    def test_auth_manager_base_get_service_credential_default(self):
        from eval_runner.console.auth_manager import AuthManager

        class DummyManager(AuthManager):
            def authenticate(self, credentials: str):
                return None

            def verify_token(self, token: str):
                return None

            def has_permission(self, user: dict, permission_node: str):
                return False

        assert DummyManager().get_service_credential() is None

    def test_static_key_provider_demo_identities_file(self, tmp_path, monkeypatch):
        import json

        from eval_runner import config
        from eval_runner.console.auth_manager import StaticKeyProvider
        from eval_runner.reference.auth import SimpleAPIKeyAuthBackend

        monkeypatch.setattr(config, "ENABLE_DEMO", True)

        # 1. Successful parsing and registration
        demo_file = tmp_path / "demo_identities.json"
        demo_file.write_text(
            json.dumps(
                {
                    "principals": [
                        {
                            "api_key": "demo-operator-key",
                            "id": "demo-op",
                            "name": "Demo Operator",
                            "roles": ["Operator"],
                            "permissions": ["extensions:run"],
                            "org_id": "demo-org",
                            "tenant_id": "demo-tenant",
                            "workspace_id": "demo-ws",
                            "active_environment": "dev",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("AGENTV_DEMO_IDENTITIES_FILE", str(demo_file))

        backend = SimpleAPIKeyAuthBackend()
        provider = StaticKeyProvider("master-key", backend=backend)
        authenticated = provider.authenticate("demo-operator-key")
        assert authenticated is not None
        assert authenticated["id"] == "demo-op"
        assert authenticated["roles"] == ["Operator"]

        # 2. Corrupted fixture raises RuntimeError
        bad_file = tmp_path / "bad_identities.json"
        bad_file.write_text("NOT_VALID_JSON", encoding="utf-8")
        monkeypatch.setenv("AGENTV_DEMO_IDENTITIES_FILE", str(bad_file))
        with pytest.raises(RuntimeError, match="Invalid demo identity fixture"):
            StaticKeyProvider("master-key", backend=SimpleAPIKeyAuthBackend())

    def test_load_configured_authorization_backend_errors_and_success(self, monkeypatch):
        from eval_runner.console.auth_manager import (
            _load_configured_authorization_backend,
            get_auth_provider,
        )
        from eval_runner.reference.auth import SimpleAPIKeyAuthBackend

        # 1. Invalid spec format (no colon)
        with pytest.raises(RuntimeError, match="must be 'package.module:factory'"):
            _load_configured_authorization_backend("no_colon_spec")

        # 2. Missing module
        with pytest.raises(RuntimeError, match="Unable to load"):
            _load_configured_authorization_backend("nonexistent.module:factory")

        # 3. Not callable factory
        with pytest.raises(RuntimeError, match="is not callable"):
            _load_configured_authorization_backend(
                "eval_runner.console.auth_manager:CONTEXT_VERSION"
            )

        # 4. Factory requiring arguments
        def bad_factory(arg1):
            return SimpleAPIKeyAuthBackend()

        import sys

        sys.modules["test_factory_mod"] = MagicMock(bad_factory=bad_factory)
        try:
            with pytest.raises(RuntimeError, match="must be callable with no arguments"):
                _load_configured_authorization_backend("test_factory_mod:bad_factory")
        finally:
            sys.modules.pop("test_factory_mod", None)

        # 5. Factory returning non-AuthorizationBackend
        sys.modules["test_factory_mod2"] = MagicMock(factory_obj=lambda: "not_a_backend")
        try:
            with pytest.raises(RuntimeError, match="must return an AuthorizationBackend"):
                _load_configured_authorization_backend("test_factory_mod2:factory_obj")
        finally:
            sys.modules.pop("test_factory_mod2", None)

        # 6. Success via get_auth_provider() env var
        sys.modules["test_valid_factory_mod"] = MagicMock(
            create_backend=lambda: SimpleAPIKeyAuthBackend(master_key="srv-key-999")
        )
        try:
            monkeypatch.setenv(
                "AGENTV_AUTHORIZATION_BACKEND_FACTORY",
                "test_valid_factory_mod:create_backend",
            )
            provider = get_auth_provider()
            assert provider.get_service_credential() == "srv-key-999"
        finally:
            sys.modules.pop("test_valid_factory_mod", None)

    def test_require_permission_binding_and_logging_branches(self, app, monkeypatch):
        from eval_runner.console.auth_manager import (
            Permission,
            require_permission,
        )

        monkeypatch.delenv("AGENTV_TEST_AUTH_BYPASS", raising=False)

        @app.route("/api/test/perm-check")
        @require_permission(Permission.RUNS_WRITE)
        def perm_check():
            return jsonify({"status": "granted"})

        client = app.test_client()

        # 1. Bearer token invalid logging branch
        resp_bad_bearer = client.get(
            "/api/test/perm-check",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp_bad_bearer.status_code == 401

        # 2. Bearer token user with invalid entitlements
        mock_bad_ent_provider = MagicMock()
        mock_bad_ent_provider.verify_token.return_value = {
            "id": "bad-ent",
            "permissions": [Permission.RUNS_WRITE],
            "authorized_contexts": "invalid-contexts-shape",
        }
        with patch(
            "eval_runner.console.auth_manager.get_auth_provider",
            lambda: mock_bad_ent_provider,
        ):
            resp_token_bad_ent = client.get(
                "/api/test/perm-check",
                headers={"Authorization": "Bearer some-token"},
            )
            assert resp_token_bad_ent.status_code == 403

        # 3. API key user with invalid entitlements
        mock_bad_key_provider = MagicMock()
        mock_bad_key_provider.authenticate.return_value = {
            "id": "bad-key-ent",
            "permissions": [Permission.RUNS_WRITE],
            "authorized_contexts": "invalid-contexts-shape",
        }
        with patch(
            "eval_runner.console.auth_manager.get_auth_provider",
            lambda: mock_bad_key_provider,
        ):
            resp_key_bad_ent = client.get(
                "/api/test/perm-check",
                headers={"X-API-Key": "some-key"},
            )
            assert resp_key_bad_ent.status_code == 403

        # 4. Session user with invalid entitlements -> 403
        with client.session_transaction() as sess:
            sess["user"] = {
                "id": "bad-sess-user",
                "permissions": [Permission.RUNS_WRITE],
                "authorized_contexts": "not-a-valid-list",
            }
        resp_sess_bad_ent = client.get("/api/test/perm-check")
        assert resp_sess_bad_ent.status_code == 403

        # Clear session cookie so subsequent tests test bearer/api_key directly
        with client.session_transaction() as sess:
            sess.clear()

        # 5. Bearer token valid user with valid permissions -> 200
        mock_ok_token_provider = MagicMock()
        mock_ok_token_provider.verify_token.return_value = {
            "id": "good-token-user",
            "permissions": [Permission.RUNS_WRITE],
        }
        mock_ok_token_provider.has_permission.return_value = True
        with patch(
            "eval_runner.console.auth_manager.get_auth_provider",
            lambda: mock_ok_token_provider,
        ):
            resp = client.get(
                "/api/test/perm-check",
                headers={"Authorization": "Bearer good-token"},
            )
            assert resp.status_code == 200
            assert resp.get_json() == {"status": "granted"}

        # 6. Bearer token user with missing permissions -> 403
        mock_noperm_token_provider = MagicMock()
        mock_noperm_token_provider.verify_token.return_value = {
            "id": "noperm-token-user",
            "permissions": ["scenarios:read"],
        }
        mock_noperm_token_provider.has_permission.return_value = False
        with patch(
            "eval_runner.console.auth_manager.get_auth_provider",
            lambda: mock_noperm_token_provider,
        ):
            resp = client.get(
                "/api/test/perm-check",
                headers={"Authorization": "Bearer noperm-token"},
            )
            assert resp.status_code == 403

        # 7. API key valid user with valid permissions -> 200
        mock_ok_key_provider = MagicMock()
        mock_ok_key_provider.authenticate.return_value = {
            "id": "good-key-user",
            "permissions": [Permission.RUNS_WRITE],
        }
        mock_ok_key_provider.has_permission.return_value = True
        with patch(
            "eval_runner.console.auth_manager.get_auth_provider",
            lambda: mock_ok_key_provider,
        ):
            resp = client.get(
                "/api/test/perm-check",
                headers={"X-API-Key": "good-key"},
            )
            assert resp.status_code == 200
            assert resp.get_json() == {"status": "granted"}

        # 8. API key valid user with missing permissions -> 403
        mock_noperm_key_provider = MagicMock()
        mock_noperm_key_provider.authenticate.return_value = {
            "id": "noperm-key-user",
            "permissions": ["scenarios:read"],
        }
        mock_noperm_key_provider.has_permission.return_value = False
        with patch(
            "eval_runner.console.auth_manager.get_auth_provider",
            lambda: mock_noperm_key_provider,
        ):
            resp = client.get(
                "/api/test/perm-check",
                headers={"X-API-Key": "noperm-key"},
            )
            assert resp.status_code == 403

        # 9. API key invalid (>8 chars hint) -> 401
        mock_none_key_provider = MagicMock()
        mock_none_key_provider.authenticate.return_value = None
        with patch(
            "eval_runner.console.auth_manager.get_auth_provider",
            lambda: mock_none_key_provider,
        ):
            resp_long_key = client.get(
                "/api/test/perm-check",
                headers={"X-API-Key": "1234567890abcdef"},
            )
            assert resp_long_key.status_code == 401

            # API key invalid (<=8 chars hint) -> 401
            resp_short_key = client.get(
                "/api/test/perm-check",
                headers={"X-API-Key": "short"},
            )
            assert resp_short_key.status_code == 401

        # 10. No session, no bearer, no api key -> 401
        mock_empty_provider = MagicMock()
        with patch(
            "eval_runner.console.auth_manager.get_auth_provider",
            lambda: mock_empty_provider,
        ):
            resp_empty = client.get("/api/test/perm-check")
            assert resp_empty.status_code == 401

    def test_context_allows_record_combinations(self):
        from eval_runner.console.auth_manager import context_allows_record

        # None context allows any record
        assert context_allows_record({"some": "record"}, None) is True

        target_ctx = {
            "org_id": "org-1",
            "tenant_id": "ten-1",
            "workspace_id": "ws-1",
            "active_environment": "dev",
        }

        # Matching top-level context
        rec_match = {"context": target_ctx}
        assert context_allows_record(rec_match, target_ctx) is True

        # Mismatch top-level context
        rec_mismatch = {"context": {**target_ctx, "active_environment": "prod"}}
        assert context_allows_record(rec_mismatch, target_ctx) is False

        # Matching metadata.runtime_context
        rec_meta = {"metadata": {"runtime_context": target_ctx}}
        assert context_allows_record(rec_meta, target_ctx) is True

        # Mismatch metadata.runtime_context
        rec_meta_mismatch = {
            "metadata": {"runtime_context": {**target_ctx, "workspace_id": "ws-2"}}
        }
        assert context_allows_record(rec_meta_mismatch, target_ctx) is False

    def test_static_key_provider_attributes_and_debug_logging(self, tmp_path, monkeypatch):
        import json

        from agentv_runtime.interfaces import AuthPrincipal
        from eval_runner import config
        from eval_runner.console.auth_manager import (
            StaticKeyProvider,
            get_auth_provider,
            register_authorization_backend,
        )
        from eval_runner.reference.auth import SimpleAPIKeyAuthBackend

        monkeypatch.setenv("DEBUG", "true")

        # 1. Non-SimpleAPIKeyAuthBackend with demo fixture returns immediately
        monkeypatch.setattr(config, "ENABLE_DEMO", True)
        mock_file = tmp_path / "mock_demo.json"
        mock_file.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("AGENTV_DEMO_IDENTITIES_FILE", str(mock_file))
        provider_other_backend = StaticKeyProvider("key", backend=MagicMock())
        assert provider_other_backend.key == "key"

        # 2. Demo file invalid schemas
        bad_f1 = tmp_path / "bad1.json"
        bad_f1.write_text(json.dumps({"principals": "not-a-list"}), encoding="utf-8")
        monkeypatch.setenv("AGENTV_DEMO_IDENTITIES_FILE", str(bad_f1))
        with pytest.raises(RuntimeError, match="Invalid demo identity fixture"):
            StaticKeyProvider("key", backend=SimpleAPIKeyAuthBackend())

        bad_f2 = tmp_path / "bad2.json"
        bad_f2.write_text(json.dumps({"principals": ["not-a-dict"]}), encoding="utf-8")
        monkeypatch.setenv("AGENTV_DEMO_IDENTITIES_FILE", str(bad_f2))
        with pytest.raises(RuntimeError, match="Invalid demo identity fixture"):
            StaticKeyProvider("key", backend=SimpleAPIKeyAuthBackend())

        bad_f3 = tmp_path / "bad3.json"
        bad_f3.write_text(
            json.dumps(
                {"principals": [{"api_key": "k", "id": "i", "permissions": "str", "roles": []}]}
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("AGENTV_DEMO_IDENTITIES_FILE", str(bad_f3))
        with pytest.raises(RuntimeError, match="Invalid demo identity fixture"):
            StaticKeyProvider("key", backend=SimpleAPIKeyAuthBackend())

        # Clear demo identities file so subsequent instantiations succeed
        monkeypatch.delenv("AGENTV_DEMO_IDENTITIES_FILE", raising=False)

        # 3. Authenticate with empty string credentials
        assert provider_other_backend.authenticate("") is None

        # 4. Authenticate root-admin key fallback when backend does not recognize the key
        backend_none = MagicMock()
        backend_none.validate_token.return_value = None
        prov_fallback = StaticKeyProvider("root-secret-key", backend=backend_none)
        fallback_user = prov_fallback.authenticate("root-secret-key")
        assert fallback_user is not None
        assert fallback_user["type"] == "static-root"
        assert fallback_user["id"] == "root-admin"

        # 5. Principal with direct claim attributes, roles, and metadata claims
        mock_backend = MagicMock()
        mock_p = AuthPrincipal(
            principal_id="attr-user",
            permissions=["extensions:run"],
            roles=["custom-role"],
            metadata={
                "name": "Custom Name",
                "email": "user@example.com",
                "role": "custom-role",
                "roles": ["custom-role"],
                "org_id": "org-attr",
                "tenant_id": "tenant-attr",
                "workspace_id": "ws-attr",
                "active_environment": "stage",
                "context_version": "1",
                "context": {"env": "stage"},
                "authorized_contexts": [{"env": "stage"}],
            },
        )
        mock_p.context_version = "2"
        mock_backend.validate_token.return_value = mock_p
        mock_backend.check_permission.return_value = True

        provider = StaticKeyProvider("master-key", backend=mock_backend)
        user = provider.authenticate("some-key")
        assert user is not None
        assert user["roles"] == ["custom-role"]
        assert user["name"] == "Custom Name"
        assert user["email"] == "user@example.com"
        assert user["org_id"] == "org-attr"
        assert user["tenant_id"] == "tenant-attr"
        assert user["workspace_id"] == "ws-attr"
        assert user["active_environment"] == "stage"
        assert user["context_version"] == "2"

        # Principal without roles exercises roles branch
        mock_p_noroles = AuthPrincipal(principal_id="noroles", permissions=["*"], roles=None)
        mock_backend.validate_token.return_value = mock_p_noroles
        u_noroles = provider.authenticate("any-key")
        assert "roles" not in u_noroles

        # Check has_permission returning True (debug skip branch)
        assert provider.has_permission(user, "extensions:run") is True

        # Check has_permission denied with DEBUG=true triggers print logging
        mock_backend.check_permission.return_value = False
        denied_principal = {"id": "attr-user", "permissions": ["other:perm"]}
        assert provider.has_permission(denied_principal, "extensions:run") is False

        # Check has_permission denied with DEBUG=false skips print logging
        monkeypatch.setenv("DEBUG", "false")
        assert provider.has_permission(denied_principal, "extensions:run") is False
        monkeypatch.setenv("DEBUG", "true")

        # 6. get_service_credential with configured backend returning None
        # falls through to static key
        backend_no_cred = MagicMock()
        backend_no_cred.get_service_credential.return_value = None
        provider_no_cred = StaticKeyProvider("fallback-static-key", backend=backend_no_cred)
        assert provider_no_cred.get_service_credential() == "fallback-static-key"

        # 7. get_auth_provider with factory spec in environment
        monkeypatch.setenv(
            "AGENTV_AUTHORIZATION_BACKEND_FACTORY",
            "eval_runner.reference.auth:SimpleAPIKeyAuthBackend",
        )
        prov = get_auth_provider()
        assert isinstance(prov, StaticKeyProvider)
        assert prov._uses_configured_backend is True

        # 8. get_auth_provider with registered backend skips factory lookup
        registered_mock = MagicMock()
        register_authorization_backend(registered_mock)
        reg_prov = get_auth_provider()
        assert reg_prov.backend == registered_mock
        register_authorization_backend(None)

    def test_oidc_jwt_verification_exhaustive_branches(self, monkeypatch):
        jwks_url = "https://auth.example.com/.well-known/jwks.json"
        monkeypatch.setattr("eval_runner.config.OIDC_JWKS_URL", jwks_url)
        monkeypatch.setattr("eval_runner.config.OIDC_AUDIENCE", None)
        monkeypatch.setattr("eval_runner.config.OIDC_ISSUER", None)
        provider = StaticKeyProvider("master-key-123")

        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.return_value = MagicMock()

        # A0. Audience and issuer absent (falsy)
        with (
            patch("jwt.PyJWKClient", return_value=mock_jwks_client),
            patch("jwt.decode", return_value={"sub": "user-no-aud"}),
        ):
            user_no_aud = provider.verify_token("token-no-aud")
            assert user_no_aud is not None

        monkeypatch.setattr("eval_runner.config.OIDC_AUDIENCE", "agentv-service")
        monkeypatch.setattr("eval_runner.config.OIDC_ISSUER", "https://auth.example.com")

        # A. permissions as string
        payload_str_perms = {
            "sub": "user-str-perms",
            "permissions": "scenarios:read runs:read",
        }
        with (
            patch("jwt.PyJWKClient", return_value=mock_jwks_client),
            patch("jwt.decode", return_value=payload_str_perms),
        ):
            user_a = provider.verify_token("token-a")
            assert user_a["permissions"] == ["scenarios:read", "runs:read"]

        # B. roles as string and admin mapping
        payload_str_role = {
            "sub": "user-str-role",
            "roles": "admin",
        }
        with (
            patch("jwt.PyJWKClient", return_value=mock_jwks_client),
            patch("jwt.decode", return_value=payload_str_role),
        ):
            user_b = provider.verify_token("token-b")
            assert user_b["permissions"] == Permission.ADMIN()

        # C. Empty scope and empty permissions
        payload_empty_scope = {
            "sub": "user-empty-scope",
            "scope": "",
        }
        with (
            patch("jwt.PyJWKClient", return_value=mock_jwks_client),
            patch("jwt.decode", return_value=payload_empty_scope),
        ):
            user_c = provider.verify_token("token-c")
            assert user_c["permissions"] == []

        # D. Non-empty scope mapping
        payload_scope = {
            "sub": "user-scope",
            "scope": "custom:read custom:write",
        }
        with (
            patch("jwt.PyJWKClient", return_value=mock_jwks_client),
            patch("jwt.decode", return_value=payload_scope),
        ):
            user_scope = provider.verify_token("token-scope")
            assert user_scope["permissions"] == ["custom:read", "custom:write"]

        # E. Context and claims in payload
        payload_ctx = {
            "sub": "user-ctx",
            "org_id": "org-jwt",
            "tenant_id": "ten-jwt",
            "workspace_id": "ws-jwt",
            "active_environment": "prod",
            "context_version": "v3",
            "context": {"team": "red"},
            "authorized_contexts": [{"team": "red"}],
        }
        with (
            patch("jwt.PyJWKClient", return_value=mock_jwks_client),
            patch("jwt.decode", return_value=payload_ctx),
        ):
            user_d = provider.verify_token("token-d")
            assert user_d["org_id"] == "org-jwt"
            assert user_d["tenant_id"] == "ten-jwt"
            assert user_d["workspace_id"] == "ws-jwt"
            assert user_d["active_environment"] == "prod"
            assert user_d["context_version"] == "v3"
            assert user_d["context"] == {"team": "red"}
            assert user_d["authorized_contexts"] == [{"team": "red"}]

        # F. Exception with DEBUG=false (skips print)
        monkeypatch.setenv("DEBUG", "false")
        with patch("jwt.PyJWKClient", side_effect=ValueError("boom")):
            assert provider.verify_token("bad-token") is None

        # G. Exception with DEBUG=true (executes print)
        monkeypatch.setenv("DEBUG", "true")
        with patch("jwt.PyJWKClient", side_effect=ValueError("boom-loud")):
            assert provider.verify_token("bad-token-debug") is None
