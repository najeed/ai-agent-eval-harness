"""Provider-only run-list verdict presentation contracts."""

from __future__ import annotations

import pytest
from flask import Flask

from eval_runner.console.routes.runs import run_bp


class FakeRunStore:
    def __init__(self, runs):
        self.runs = {item["run_id"]: dict(item) for item in runs}

    def search_runs(self, query="", filters=None, limit=100, offset=0, context=None):
        rows = [row for row in self.runs.values() if query in row["run_id"]]
        return rows[offset : offset + limit]

    def get_run(self, run_id, context=None):
        return self.runs.get(run_id)

    def get_manifest(self, run_id, context=None):
        return self.runs.get(run_id, {}).get("manifest")

    def get_events(self, run_id, offset=0, limit=1000, context=None):
        return []


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.extensions["agentv_run_store"] = FakeRunStore(
        [
            {"run_id": "verified", "status": "SEALED", "verification_status": "VERIFIED"},
            {
                "run_id": "tampered",
                "status": "SEALED",
                "verification_status": "FAILED_VERIFICATION",
            },
            {"run_id": "uncertified", "status": "OPEN", "verification_status": "UNKNOWN"},
            {
                "run_id": "provisional",
                "status": "SEALED",
                "verification_status": "VERIFIED_PROVISIONAL",
                "provisional": True,
            },
        ]
    )
    app.register_blueprint(run_bp, url_prefix="/api")
    monkeypatch.setattr(
        "eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f
    )
    return app.test_client()


@pytest.mark.parametrize(
    ("run_id", "expected"),
    [
        ("verified", "VERIFIED"),
        ("tampered", "FAILED_VERIFICATION"),
        ("uncertified", "UNKNOWN"),
        ("provisional", "VERIFIED_PROVISIONAL"),
    ],
)
def test_list_runs_presents_provider_verdict(client, run_id, expected):
    response = client.get("/api/runs")
    assert response.status_code == 200
    rows = {row["run_id"]: row for row in response.get_json()["runs"]}
    assert rows[run_id]["verification_status"] == expected


def test_list_runs_does_not_read_a_vault_or_master_log(client, tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "decoy-runs")
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert {row["run_id"] for row in response.get_json()["runs"]} == {
        "verified",
        "tampered",
        "uncertified",
        "provisional",
    }
