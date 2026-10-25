"""Provider-native console run-route contracts.

Run directories may exist inside the local reference provider, but these tests
seed and inspect evidence solely through its public provider contract.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

from eval_runner.console.routes.runs import run_bp
from eval_runner.reference.local_run_store import LocalFileRunStore


@pytest.fixture
def provider(tmp_path: Path) -> LocalFileRunStore:
    return LocalFileRunStore(tmp_path / "provider-runs")


@pytest.fixture
def client(provider: LocalFileRunStore, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.extensions["agentv_run_store"] = provider
    app.register_blueprint(run_bp, url_prefix="/api")
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda fn: fn):
        with patch(
            "eval_runner.console.auth_manager.require_sse_permission", lambda _: lambda fn: fn
        ):
            yield app.test_client()


def _seed_run(
    provider: LocalFileRunStore,
    run_id: str,
    *,
    scenario: str = "scenario-a",
    events: list[dict] | None = None,
    manifest: dict | None = None,
    status: str = "RUNNING",
) -> None:
    provider.create_run(run_id, scenario)
    provider.append_events(run_id, events or [{"event": "run_start", "_seq": 1}])
    provider.save_run_manifest(run_id, manifest or {"scenario_data": {"id": scenario}})
    provider.update_run_status(run_id, status)


def test_list_runs_reads_only_provider_owned_records(client, provider, tmp_path):
    _seed_run(provider, "provider-run", scenario="provider-scenario")
    # A path-shaped decoy is intentionally not registered in the provider.
    decoy = tmp_path / "unowned" / "run.jsonl"
    decoy.parent.mkdir(parents=True)
    decoy.write_text('{"run_id":"filesystem-decoy"}\n', encoding="utf-8")

    response = client.get("/api/runs")

    assert response.status_code == 200
    assert [row["run_id"] for row in response.get_json()["runs"]] == ["provider-run"]


def test_list_runs_query_uses_provider_search(client, provider):
    _seed_run(provider, "alpha", scenario="alpha-scenario")
    _seed_run(provider, "beta", scenario="beta-scenario")

    response = client.get("/api/runs?q=beta")

    assert response.status_code == 200
    assert [row["run_id"] for row in response.get_json()["runs"]] == ["beta"]


def test_status_uses_provider_events_for_terminal_state(client, provider):
    _seed_run(
        provider,
        "completed",
        events=[
            {"event": "run_start", "_seq": 1},
            {"event": "session_decision", "_seq": 2, "decision": "PASS"},
        ],
    )

    response = client.get("/api/v1/runs/completed")

    assert response.status_code == 200
    data = response.get_json()
    assert data["run_id"] == "completed"
    assert data["size"] == 2
    assert data["status"] == "COMPLETED"


def test_status_returns_404_when_provider_does_not_own_run(client):
    response = client.get("/api/v1/runs/not-owned")

    assert response.status_code == 404


def test_certificate_reads_provider_manifest(client, provider):
    _seed_run(provider, "certified", manifest={"verification_package": {"id": "package-1"}})

    response = client.get("/api/v1/certificates/certified")

    assert response.status_code == 200
    assert response.get_json()["verification_package"]["id"] == "package-1"


def test_explain_reads_provider_events(client, provider):
    _seed_run(provider, "explain", events=[{"event": "run_start", "_seq": 1}])

    with patch("eval_runner.console.routes.runs.explain_events", return_value={"rca": "ok"}):
        response = client.get("/api/v1/explain/explain")

    assert response.status_code == 200
    assert response.get_json()["analysis"] == {"rca": "ok"}


def test_stream_returns_provider_events_and_closes_at_terminal_event(client, provider):
    _seed_run(
        provider,
        "streamed",
        events=[
            {"event": "run_start", "_seq": 1},
            {"event": "run_end", "_seq": 2, "status": "PASS"},
        ],
    )

    response = client.get("/api/v1/runs/streamed/stream")

    assert response.status_code == 200
    payload = response.get_data(as_text=True)
    assert '"event": "run_start"' in payload
    assert '"event": "run_end"' in payload


def test_verify_uses_provider_not_path_recovery(client, provider):
    _seed_run(provider, "verify")
    with patch(
        "eval_runner.verifier.TraceVerifier.verify_trace_bytes",
        return_value=False,
    ):
        response = client.get("/api/v1/runs/verify/verify")

    assert response.status_code == 200
    assert response.get_json()["verification_status"] == "FAILED_VERIFICATION"


def test_console_authenticated_scope_b_denial_returns_404(provider, monkeypatch):
    """Scoped provider route regression test.

    Proves an authenticated client bound to Scope B receives 404 Not Found on
    runs, streams, and reports created under Scope A, while Scope A receives 200.
    """
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.extensions["agentv_run_store"] = provider
    app.register_blueprint(run_bp, url_prefix="/api")
    monkeypatch.delenv("AGENTV_TEST_AUTH_BYPASS", raising=False)

    run_id = "scoped-run-alpha"
    scope_a = {"org_id": "scope-a"}
    scope_b = {"org_id": "scope-b"}

    provider.create_run(run_id, "scenario-a", context=scope_a)
    provider.append_events(run_id, [{"event": "run_start", "_seq": 1}], context=scope_a)
    provider.save_run_manifest(
        run_id,
        {"scenario_data": {"id": "scenario-a"}, "context": scope_a},
        context=scope_a,
    )
    provider.update_run_status(run_id, "COMPLETED", context=scope_a)

    user_a = {
        "id": "operator-a",
        "permissions": ["*"],
        "roles": ["admin"],
        "context": scope_a,
    }
    user_b = {
        "id": "operator-b",
        "permissions": ["*"],
        "roles": ["admin"],
        "context": scope_b,
    }

    client = app.test_client()

    # Scope A client receives 200 on run status and stream
    with client.session_transaction() as sess:
        sess["user"] = user_a

    resp_a_status = client.get(f"/api/v1/runs/{run_id}")
    assert resp_a_status.status_code == 200
    assert resp_a_status.get_json()["run_id"] == run_id

    resp_a_stream = client.get(f"/api/v1/runs/{run_id}/stream")
    assert resp_a_stream.status_code == 200

    # Scope B client is denied fail-closed with 404 across all endpoints
    with client.session_transaction() as sess:
        sess["user"] = user_b

    resp_b_status = client.get(f"/api/v1/runs/{run_id}")
    assert resp_b_status.status_code == 404

    resp_b_stream = client.get(f"/api/v1/runs/{run_id}/stream")
    assert resp_b_stream.status_code == 404

    resp_b_report = client.get(f"/api/v1/runs/{run_id}/report.pdf")
    assert resp_b_report.status_code == 404
