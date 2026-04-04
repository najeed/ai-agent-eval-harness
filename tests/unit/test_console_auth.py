import pytest
from flask import Flask, session
from eval_runner.console.auth_manager import Permission, StaticKeyProvider, require_permission

def test_static_key_provider_auth():
    """Verify that the StaticKeyProvider correctly authenticates and assigns permissions."""
    provider = StaticKeyProvider("master-key")
    
    # 1. Successful Auth
    user = provider.authenticate("master-key")
    assert user is not None
    assert user["id"] == "root-admin"
    assert "scenarios:read" in user["permissions"]
    
    # 2. Failed Auth
    assert provider.authenticate("wrong-key") is None

def test_require_permission_decorator():
    """Verify that the require_permission decorator correctly enforces access control."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    
    @app.route("/test")
    @require_permission(Permission.SCENARIOS_READ)
    def test_route():
        return "OK"

    client = app.test_client()
    
    # 1. Unauthorized (No Session, No Header)
    resp = client.get("/test")
    assert resp.status_code == 401
    
    # 2. Forbidden (Session with insufficient perms - mock)
    with client.session_transaction() as sess:
        sess["user"] = {"permissions": []}
    resp = client.get("/test")
    assert resp.status_code == 403

    # 3. Authorized (Session with perms)
    with client.session_transaction() as sess:
        sess["user"] = {"permissions": [Permission.SCENARIOS_READ]}
    resp = client.get("/test")
    assert resp.status_code == 200
    assert resp.data.decode() == "OK"
