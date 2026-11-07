import json

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.app import create_app
from eval_runner.console.auth_manager import Permission, require_permission
from eval_runner.console.routes import core_bp
from eval_runner.console.routes.system import system_bp
from eval_runner.reference.local_run_store import LocalFileRunStore


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTV_TEST_AUTH_BYPASS", raising=False)
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    store = LocalFileRunStore(tmp_path / "runs")

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.extensions["agentv_run_store"] = store
    app.register_blueprint(system_bp)
    app.register_blueprint(core_bp)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_debugger_anonymous_access_denied(client):
    """Anonymous access to /debugger/state must fail with 401."""
    res_get = client.get("/debugger/state")
    assert res_get.status_code == 401

    res_post = client.post("/debugger/state", json={"event": "test"})
    assert res_post.status_code == 401

    # Legacy proxy route also requires authentication
    res_proxy_get = client.get("/api/debugger/state")
    assert res_proxy_get.status_code == 401


def test_debugger_insufficient_permissions_denied(client):
    """Caller without required permission is rejected with 403."""
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "readonly-docs",
            "permissions": [Permission.DOCS_READ],
            "context": {
                "org_id": "org1",
                "tenant_id": "t1",
                "workspace_id": "w1",
                "active_environment": "dev",
            },
            "authorized_contexts": [
                {
                    "org_id": "org1",
                    "tenant_id": "t1",
                    "workspace_id": "w1",
                    "environments": ["dev"],
                }
            ],
            "context_version": "2",
        }

    res_get = client.get("/debugger/state")
    assert res_get.status_code == 403

    res_post = client.post("/debugger/state", json={"event": "test"})
    assert res_post.status_code == 403


def test_debugger_cross_tenant_isolation(client, tmp_path, monkeypatch):
    """Verify that a tenant cannot access debugger traces of another tenant."""
    # 1. Setup tenant-a run with trace events
    run_id = "tenant-a-run"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text(
        '{"event": "start", "run_id": "tenant-a-run"}\n'
        '{"event": "secret_observation", "data": "confidential_a"}\n'
        '{"event": "run_end", "outcome": "pass"}\n',
        encoding="utf-8",
    )
    manifest_data = {
        "run_id": run_id,
        "context": {"org_id": "tenant-a", "tenant_id": "tenant-a"},
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    # 2. Authenticate as tenant-b user
    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "tenant-b-user",
            "permissions": [Permission.DEBUG_READ],
            "context_version": "2",
            "context": {
                "org_id": "tenant-b",
                "tenant_id": "tenant-b",
                "workspace_id": "ws1",
                "active_environment": "prod",
            },
            "authorized_contexts": [
                {
                    "org_id": "tenant-b",
                    "tenant_id": "tenant-b",
                    "workspace_id": "ws1",
                    "environments": ["prod"],
                }
            ],
        }

    # Attempt to read tenant-a's run via debugger -> must return 404
    res = client.get(f"/debugger/state?run_id={run_id}")
    assert res.status_code == 404
    assert "confidential_a" not in res.get_data(as_text=True)

    # Legacy proxy route also blocks cross-tenant access
    res_proxy = client.get(f"/api/debugger/state?run_id={run_id}")
    assert res_proxy.status_code == 404
    assert "confidential_a" not in res_proxy.get_data(as_text=True)


def test_debugger_authorized_tenant_access_succeeds(client, tmp_path, monkeypatch):
    """Verify that a tenant can access their own run in the debugger."""
    run_id = "tenant-valid-run"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text(
        '{"event": "start", "run_id": "tenant-valid-run"}\n'
        '{"event": "run_end", "outcome": "pass"}\n',
        encoding="utf-8",
    )
    manifest_data = {
        "run_id": run_id,
        "context": {
            "org_id": "corp1",
            "tenant_id": "tenant1",
            "workspace_id": "ws1",
            "active_environment": "dev",
        },
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    with client.session_transaction() as sess:
        sess["user"] = {
            "id": "tenant1-user",
            "permissions": [Permission.DEBUG_READ],
            "context_version": "2",
            "context": {
                "org_id": "corp1",
                "tenant_id": "tenant1",
                "workspace_id": "ws1",
                "active_environment": "dev",
            },
            "authorized_contexts": [
                {
                    "org_id": "corp1",
                    "tenant_id": "tenant1",
                    "workspace_id": "ws1",
                    "environments": ["dev"],
                }
            ],
        }

    res = client.get(f"/debugger/state?run_id={run_id}")
    assert res.status_code == 200
    assert "data" in res.get_json()


def test_production_auth_bypass_fails_at_startup(monkeypatch):
    """AGENTV_TEST_AUTH_BYPASS=1 in production must immediately crash create_app()."""
    monkeypatch.setenv("AGENTV_ENV", "production")
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    monkeypatch.setattr(config, "is_production", lambda: True)

    with pytest.raises(RuntimeError, match="prohibited in production"):
        create_app()


def test_production_auth_bypass_fails_at_decorator(monkeypatch, app):
    """AGENTV_TEST_AUTH_BYPASS=1 in production must fail closed in require_permission."""
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    monkeypatch.setattr(config, "is_production", lambda: True)

    @app.route("/protected-prod-test")
    @require_permission(Permission.RUNS_READ)
    def protected():
        return {"status": "ok"}

    with app.test_client() as c:
        with pytest.raises(RuntimeError, match="prohibited in production"):
            c.get("/protected-prod-test")
