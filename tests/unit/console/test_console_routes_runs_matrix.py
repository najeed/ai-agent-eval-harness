"""Provider-native branch matrix for console run routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import eval_runner.console.routes.runs as runs
from eval_runner.services.run_summary import RunSummaryService


@pytest.fixture
def app():
    value = Flask(__name__)
    value.config["TESTING"] = True
    return value


@pytest.fixture
def scope():
    return {"org_id": "acme", "tenant_id": "t1", "workspace_id": "w1"}


@pytest.fixture
def provider():
    store = MagicMock()
    store.get_run.return_value = None
    store.get_events.return_value = []
    store.get_manifest.return_value = None
    store.get_trace_bytes.return_value = None
    store.search_runs.return_value = []
    store.list_runs.return_value = []
    store.stream_events.return_value = iter(())
    return store


def invoke(app, handler, *args, path="/", headers=None):
    with app.test_request_context(path, headers=headers):
        return handler.__wrapped__(*args)


def test_list_runs_endpoint_queries_active_provider(app, provider, scope):
    provider.search_runs.return_value = [
        {"run_id": "run-v1", "scenario_id": "sc1", "status": "COMPLETED"}
    ]
    provider.get_run.return_value = {"run_id": "run-v1"}
    with (
        patch.object(runs, "_active_run_store", return_value=provider),
        patch.object(runs, "active_runtime_context", return_value=scope),
    ):
        response = invoke(app, runs.list_runs, path="/?q=sc1")
    assert response.get_json()["runs"][0]["run_id"] == "run-v1"
    provider.search_runs.assert_called_once_with(query="sc1", limit=200, context=scope)


def test_authoritative_verdict_provider_edge_cases(provider):
    assert RunSummaryService.get_authoritative_verdict("", run_store=provider) == "NOT_EXECUTED"
    provider.get_run.return_value = {"run_id": "corrupt"}
    provider.get_manifest.return_value = {"trace_hash": "bad"}
    provider.get_trace_bytes.return_value = b"bad canonical bytes"
    with patch(
        "eval_runner.services.run_summary.TraceVerifier.verify_trace_bytes", side_effect=ValueError
    ):
        assert (
            RunSummaryService.get_authoritative_verdict("corrupt", run_store=provider)
            == "FAILED_VERIFICATION"
        )


def test_stream_runs_list_uses_provider_records(app, provider, scope):
    provider.list_runs.return_value = [
        {"run_id": "run-cert", "status": "SEALED"},
        {"run_id": "run-zero", "status": "OPEN"},
        {"run_id": "run-active", "status": "RUNNING"},
    ]
    provider.get_run.side_effect = lambda run_id, context=None: {"run_id": run_id, "status": "OPEN"}
    with (
        patch.object(runs, "_active_run_store", return_value=provider),
        patch.object(runs, "active_runtime_context", return_value=scope),
        patch.object(runs.time, "sleep"),
    ):
        response = invoke(app, runs.stream_runs_list)
        payload = "".join(response.response)
    assert "run-cert" in payload and "run-zero" in payload and "run-active" in payload
    provider.list_runs.assert_called_once_with(limit=200, context=scope)


def test_get_run_status_reads_provider_scenario_and_missing_run(app, provider, scope):
    provider.get_run.return_value = {"run_id": "run-orig", "status": "COMPLETED"}
    provider.get_manifest.return_value = {"scenario_data": {"id": "provider-scenario"}}
    with (
        patch.object(runs, "_active_run_store", return_value=provider),
        patch.object(runs, "active_runtime_context", return_value=scope),
    ):
        response = invoke(app, runs.get_run_status, "run-orig")
    assert response.get_json()["scenario"] == {"id": "provider-scenario"}

    provider.get_run.return_value = None
    with (
        patch.object(runs, "_active_run_store", return_value=provider),
        patch.object(runs, "active_runtime_context", return_value=scope),
    ):
        missing, status = invoke(app, runs.get_run_status, "missing")
    assert status == 404
    assert missing.get_json()["error"] == "Not found"


def test_stream_logs_uses_provider_events_and_transport_cursor(app, provider, scope):
    provider.get_run.return_value = {"run_id": "run-stream", "status": "RUNNING"}
    provider.stream_events.return_value = iter(
        [
            {"event": "step1", "_seq": 5},
            {"event": "step2", "_seq": 9},
            {"event": "run_end", "_seq": 11},
        ]
    )
    with (
        patch.object(runs, "_active_run_store", return_value=provider),
        patch.object(runs, "active_runtime_context", return_value=scope),
    ):
        response = invoke(
            app, runs.stream_run_logs, "run-stream", path="/?last_event_id=not_an_int"
        )
        payload = "".join(response.response)
    assert "id: 1" in payload and "id: 3" in payload
    assert '"_seq": 5' in payload and '"_seq": 11' in payload
    provider.stream_events.assert_called_once_with("run-stream", from_seq=0, context=scope)


def test_verify_run_endpoint_uses_provider_exact_bytes(app, provider, scope):
    provider.get_run.return_value = {"run_id": "run-verify-ok"}
    provider.get_manifest.return_value = {
        "trace_hash": "digest",
        "execution_mode": "live",
        "compliance_status": "pass",
    }
    provider.get_trace_bytes.return_value = b'{"event":"run_end"}\n'
    with (
        patch.object(runs, "_active_run_store", return_value=provider),
        patch.object(runs, "active_runtime_context", return_value=scope),
        patch("eval_runner.verifier.TraceVerifier.verify_trace_bytes", return_value=True) as verify,
    ):
        response = invoke(app, runs.verify_run, "run-verify-ok")
    assert response.get_json()["verification_status"] == "VERIFIED"
    verify.assert_called_once_with(
        b'{"event":"run_end"}\n',
        {"trace_hash": "digest", "execution_mode": "live", "compliance_status": "pass"},
        run_store=provider,
        context=scope,
        trace_only=False,
    )
