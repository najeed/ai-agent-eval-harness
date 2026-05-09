from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes import runs as rs_runs, scenarios as rs_scen, system as rs_sys


@pytest.fixture
def app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    # Essential registration for industrial coverage
    app.register_blueprint(rs_scen.scenario_bp)
    app.register_blueprint(rs_sys.system_bp)
    app.register_blueprint(rs_runs.run_bp)

    @app.before_request
    def mock_session():
        from flask import session

        session["user"] = {
            "permissions": [
                "scenarios:read",
                "scenarios:write",
                "eval:trigger",
                "docs:read",
                "runs:read",
                "demo:execute",
            ],
            "id": "root",
            "name": "Admin",
        }

    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_routes_scenarios_industrial_resilience(client, tmp_path, monkeypatch):
    """Verifies that scenario evaluation routes handle physical exists checks correctly."""
    base = tmp_path.resolve()
    monkeypatch.setattr(config, "PROJECT_ROOT", base)
    (base / "s1.json").write_text("{}")

    with patch.object(rs_scen, "get_catalog") as mock_get_cat:
        mock_cat = MagicMock()
        mock_get_cat.return_value = mock_cat
        mock_cat.get_absolute_path.return_value = base / "s1.json"

        with patch.object(
            rs_scen.loader,
            "load_scenario",
            return_value={"title": "g", "workflow": {"steps": []}, "metadata": {}},
        ):
            with patch.object(rs_scen.engine, "run_evaluation"):
                resp = client.post("/v1/evaluate", json={"path": "s1.json"})
                assert resp.status_code == 200


def test_routes_system_docs_resolution(client, tmp_path, monkeypatch):
    """Verifies that documentation resolution logic is robust to legacy path structures."""
    base = tmp_path.resolve()
    monkeypatch.setattr(config, "PROJECT_ROOT", base)
    (base / "docs-old").mkdir()
    (base / "docs-old" / "g.md").write_text("# Doc")

    assert client.get("/docs").status_code == 200
    assert client.get("/info").status_code == 200
