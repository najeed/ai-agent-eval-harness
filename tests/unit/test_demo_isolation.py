"""
tests/unit/test_demo_isolation.py
P0-5 Demo/Production Isolation contract tests.

Production mode (ENABLE_DEMO=false) must:
  - physically exclude all /api/demo/* and SPA /demo* routes
  - refuse unauthenticated API access (no implicit localhost trust)
  - declare X-AgentV-Mode: production on every response

Demo mode (ENABLE_DEMO=true) may register demo routes but must still not grant
implicit authority to localhost without credentials.
"""

from __future__ import annotations

import json

import pytest

import eval_runner.config as harness_config
from eval_runner.console.app import create_app


@pytest.fixture()
def isolated_app(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    reports = tmp_path / "reports"
    ui = tmp_path / "ui"
    for d in (runs, reports, ui):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(harness_config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(harness_config, "RUN_LOG_DIR", runs)
    monkeypatch.setattr(harness_config, "REPORTS_DIR", reports)
    return create_app()


def _client(app):
    app.config["TESTING"] = True
    return app.test_client()


def test_production_mode_excludes_demo_routes(isolated_app, monkeypatch):
    monkeypatch.setattr(harness_config, "ENABLE_DEMO", False)
    client = _client(isolated_app)

    demo_api_paths = [
        "/api/demo/traces",
        "/api/demo/loan",
        "/api/demo/session",
        "/api/demo/run",
    ]
    for p in demo_api_paths:
        res = client.get(p)
        assert res.status_code == 404, f"{p} must be absent in production mode"

    # SPA demo entrypoints must not resolve to the demo experience either.
    for p in ("/demo", "/demo/loan"):
        res = client.get(p)
        # Either 404 or a non-demo fallback; the demo blueprint must be gone.
        if res.status_code == 200:
            res.get_data(as_text=True)
            assert "demo" not in res.headers.get("X-AgentV-Mode", ""), p


def test_production_mode_declares_mode_header(isolated_app, monkeypatch):
    monkeypatch.setattr(harness_config, "ENABLE_DEMO", False)
    client = _client(isolated_app)

    res = client.get("/api/v1/evidence/packages")
    assert res.headers.get("X-AgentV-Mode") == "production"


def test_demo_mode_declares_mode_header_and_registers_routes(isolated_app, monkeypatch):
    monkeypatch.setattr(harness_config, "ENABLE_DEMO", True)
    app = create_app()  # re-create so registration sees ENABLE_DEMO=True
    app.config["TESTING"] = True
    client = app.test_client()

    res = client.get("/api/v1/evidence/packages")
    assert res.headers.get("X-AgentV-Mode") == "demo"

    rule_paths = {str(r) for r in app.url_map.iter_rules()}
    assert any("/demo" in r for r in rule_paths), "demo routes must exist in demo mode"


def test_no_implicit_localhost_admin_in_any_mode(isolated_app, monkeypatch):
    """
    The removed 'Local Trust' backdoor must stay removed: a request from
    127.0.0.1 with no credentials is unauthorized in BOTH modes.
    """

    for demo_enabled in (False, True):
        monkeypatch.setattr(harness_config, "ENABLE_DEMO", demo_enabled)
        app = create_app() if demo_enabled else isolated_app
        app.config["TESTING"] = True
        client = app.test_client()

        res = client.get(
            "/api/v1/evidence/packages",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert res.status_code in (401, 403), (
            f"localhost without credentials must never be admin "
            f"(ENABLE_DEMO={demo_enabled}, got {res.status_code})"
        )
        if res.status_code == 401:
            body = json.loads(res.get_data(as_text=True))
            assert "error" in body


def test_require_permission_has_no_localhost_shortcut(monkeypatch):
    """Source-level guard: the implicit Local Trust block stays deleted."""
    import inspect

    from eval_runner.console import auth_manager

    src = inspect.getsource(auth_manager.require_permission)
    assert "Local Trust" not in src, "implicit localhost admin trust must not return"
    assert "remote_addr" not in src, "no IP-based authorization decisions"
