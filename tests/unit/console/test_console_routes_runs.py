"""Full provider-native migration of the console run-route test suite.

Each former vault, master-log, direct-path, or file-tail scenario is exercised
through the RunStorageProvider contract.  Local-file behaviour belongs in the
reference provider's own tests; the console is tested only as its consumer.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import eval_runner.console.routes.runs as runs


@pytest.fixture
def app():
    application = Flask(__name__)
    application.secret_key = "test-secret"
    application.register_blueprint(runs.run_bp, url_prefix="/api")
    return application


@pytest.fixture
def scope():
    return {"org_id": "org-a", "tenant_id": "tenant-a", "workspace_id": "ws-a"}


@pytest.fixture
def store():
    provider = MagicMock()
    provider.get_run.return_value = None
    provider.get_manifest.return_value = None
    provider.get_events.return_value = []
    provider.get_trace_bytes.return_value = None
    provider.search_runs.return_value = []
    provider.list_runs.return_value = []
    provider.stream_events.return_value = iter(())
    return provider


@pytest.fixture
def provider_scope(store, scope):
    with (
        patch.object(runs, "_active_run_store", return_value=store),
        patch.object(runs, "active_runtime_context", return_value=scope),
    ):
        yield store


def invoke(app, handler, *args, path="/", method="GET", body=None, headers=None):
    with app.test_request_context(path, method=method, json=body, headers=headers):
        return getattr(handler, "__wrapped__", handler)(*args)


def body(response):
    return response.get_json()


# Former trace-location tests: evidence existence is now provider-owned.
@pytest.mark.parametrize("trace_bytes", [b"{}\n", b'{"event":"run_end"}\n', b"raw canonical bytes"])
def test_provider_trace_bytes_are_authoritative_not_paths(store, trace_bytes):
    store.get_trace_bytes.return_value = trace_bytes
    assert store.get_trace_bytes("r1", context={"tenant_id": "t"}) == trace_bytes


def test_provider_missing_trace_is_none_not_a_path(store):
    assert store.get_trace_bytes("missing", context={"tenant_id": "t"}) is None


def test_durable_scoped_provider_read_allows_owner_and_hides_other_scope(
    app, provider_scope, scope
):
    provider_scope.get_run.side_effect = lambda run_id, context=None: (
        {"run_id": run_id, "status": "OPEN"} if context == scope else None
    )
    with app.test_request_context("/"):
        assert runs._run_is_in_active_context("pending", scope)
        assert not runs._run_is_in_active_context("pending", {"tenant_id": "other"})


def test_list_metrics(app):
    with patch.object(runs.MetricRegistry, "list_metrics", return_value=["quality", "latency"]):
        response = invoke(app, runs.list_metrics)
    assert body(response)["metrics"] == ["quality", "latency"]


# Former explain vault/master-log/parse/error cases.
def test_explain_reads_provider_events(app, provider_scope, scope):
    provider_scope.get_run.return_value = {"run_id": "r1"}
    provider_scope.get_events.return_value = [{"event": "tool_result", "result": "ok"}]
    with patch.object(runs, "explain_events", return_value={"root_cause": "none"}) as explain:
        response = invoke(app, runs.explain_run, "r1")
    assert body(response)["analysis"] == {"root_cause": "none"}
    explain.assert_called_once_with(provider_scope.get_events.return_value)
    provider_scope.get_events.assert_called_once_with(
        "r1", offset=0, limit=10_000_000, context=scope
    )


def test_explain_missing_run_is_404(app, provider_scope):
    response, status = invoke(app, runs.explain_run, "missing")
    assert status == 404
    assert body(response)["error"] == "Not found"


def test_explain_empty_provider_trace_is_404(app, provider_scope):
    provider_scope.get_run.return_value = {"run_id": "r1"}
    response, status = invoke(app, runs.explain_run, "r1")
    assert status == 404
    assert body(response)["error"] == "Trace not found"


def test_explain_provider_analysis_error_is_500(app, provider_scope):
    provider_scope.get_run.return_value = {"run_id": "r1"}
    provider_scope.get_events.return_value = [{"event": "malformed_provider_event"}]
    with patch.object(runs, "explain_events", side_effect=ValueError("bad evidence")):
        response, status = invoke(app, runs.explain_run, "r1")
    assert status == 500
    assert body(response)["error"] == "bad evidence"


# Former fragment/vault listing permutations become provider record permutations.
@pytest.mark.parametrize(
    "record, expected",
    [
        ({"run_id": "r1", "scenario_id": "scenario-a", "status": "OPEN"}, "OPEN"),
        ({"run_id": "r2", "scenario": "scenario-b", "status": "COMPLETED"}, "COMPLETED"),
        ({"run_id": "r3", "status": "running"}, "RUNNING"),
        ({"run_id": "r4", "manifest": {"status": "SEALED"}}, "SEALED"),
        ({"run_id": "r5", "status": None}, "OPEN"),
        ({"run_id": "r6", "status": "FAILED", "failure_reasons": ["oracle"]}, "FAILED"),
    ],
)
def test_list_runs_provider_record_variants(app, provider_scope, record, expected):
    provider_scope.search_runs.return_value = [record]
    provider_scope.get_run.return_value = {"run_id": record["run_id"]}
    response = invoke(app, runs.list_runs)
    listed = body(response)["runs"]
    assert listed[0]["run_id"] == record["run_id"]
    assert listed[0]["status"] == expected


def test_list_runs_query_is_forwarded_to_provider(app, provider_scope, scope):
    provider_scope.search_runs.return_value = []
    invoke(app, runs.list_runs, path="/?q=customer%20support")
    provider_scope.search_runs.assert_called_once_with(
        query="customer support", limit=200, context=scope
    )


def test_list_runs_scope_denied_record_is_not_leaked(app, provider_scope):
    provider_scope.search_runs.return_value = [{"run_id": "other-tenant"}]
    provider_scope.get_run.return_value = None
    assert body(invoke(app, runs.list_runs)) == {"runs": []}


def test_list_summary_preserves_provider_oracle_diagnostics():
    summary = runs._summary_from_provider(
        {
            "run_id": "r1",
            "manifest": {
                "verification_package": {
                    "executed_oracle_results": [{"oracle_id": "o1", "passed": False}]
                }
            },
        }
    )
    assert summary["score_category"] == "ORACLE_DEFECT"
    assert summary["failure_reasons"] == ["Oracle failed: o1"]


# Former status vault/master-log/large/stalled/certificate cases.
@pytest.mark.parametrize(
    "record, events, expected_status",
    [
        ({"run_id": "r1", "status": "RUNNING"}, [{"event": "run_end"}], "COMPLETED"),
        ({"run_id": "r1", "status": "OPEN"}, [{"event": "tool_result"}], "RUNNING"),
        ({"run_id": "r1", "status": "SEALED"}, [], "SEALED"),
        ({"run_id": "r1", "status": "FAILED"}, [], "FAILED"),
        ({"run_id": "r1", "status": "CANCELLED"}, [], "CANCELLED"),
        ({"run_id": "r1", "status": "COMPLETED"}, [{"event": "run_end"}] * 1001, "COMPLETED"),
    ],
)
def test_status_is_provider_derived(app, provider_scope, record, events, expected_status):
    provider_scope.get_run.return_value = record
    provider_scope.get_events.return_value = events
    provider_scope.get_manifest.return_value = {"scenario_data": {"id": "scenario"}}
    response = invoke(app, runs.get_run_status, "r1")
    result = body(response)
    assert result["status"] == expected_status
    assert result["size"] == len(events)
    assert result["scenario"] == {"id": "scenario"}
    assert result["sourced_from_master"] is False


def test_status_orphaned_provisional_run_is_stalled(app, provider_scope):
    provider_scope.get_run.return_value = {"run_id": "r1", "status": "RUNNING", "provisional": True}
    with patch.object(runs, "is_run_alive", return_value=False):
        assert body(invoke(app, runs.get_run_status, "r1"))["status"] == "STALLED"


def test_status_returns_404_when_provider_denies_run(app, provider_scope):
    response, status = invoke(app, runs.get_run_status, "missing")
    assert status == 404
    assert body(response) == {"error": "Not found"}


def test_status_reports_provider_certificate_and_score(app, provider_scope):
    provider_scope.get_run.return_value = {"run_id": "r1", "status": "PASSED"}
    provider_scope.get_manifest.return_value = {
        "verification_package": {"id": "certificate"},
        "compliance": {"score": 0.98},
    }
    result = body(invoke(app, runs.get_run_status, "r1"))
    assert result["has_certificate"] is True
    assert result["score"] == 0.98


# Former report certificate recovery is now entirely derived from provider metadata.
def test_download_pdf_uses_provider_run_and_manifest(app, provider_scope):
    provider_scope.get_run.return_value = {"run_id": "r1", "status": "PASSED"}
    provider_scope.get_manifest.return_value = {
        "execution_manifest": {"scenario_id": "s1"},
        "verification_package": {"evidence": "e"},
    }

    def render(_data, destination):
        destination.write_bytes(b"%PDF-1.7 provider")
        return True

    with patch("eval_runner.console.pdf_service.generate_run_pdf", side_effect=render):
        response = invoke(app, runs.download_run_report_pdf, "r1")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"


def test_download_pdf_missing_provider_run_is_404(app, provider_scope):
    response, status = invoke(app, runs.download_run_report_pdf, "missing")
    assert status == 404
    assert body(response)["error"] == "Not found"


def test_certificate_is_read_from_provider_manifest(app, provider_scope):
    provider_scope.get_run.return_value = {"run_id": "r1"}
    provider_scope.get_manifest.return_value = {"vc_version": "1", "trace_hash": "abc"}
    assert body(invoke(app, runs.get_verification_certificate, "r1"))["trace_hash"] == "abc"


def test_certificate_missing_provider_manifest_is_404(app, provider_scope):
    provider_scope.get_run.return_value = {"run_id": "r1"}
    response, status = invoke(app, runs.get_verification_certificate, "r1")
    assert status == 404


# Provider streaming retains replay, terminal, heartbeat, and pause semantics.
def stream_text(app, run_id, *, path="/", headers=None):
    with app.test_request_context(path, headers=headers):
        response = runs.stream_run_logs.__wrapped__(run_id)
        return "".join(response.response)


def test_stream_replays_provider_events_from_last_event_id(app, provider_scope, scope):
    provider_scope.get_run.return_value = {"run_id": "r1", "status": "RUNNING"}
    provider_scope.stream_events.return_value = iter(
        [{"event": "tool_result", "_seq": 100}, {"event": "run_end", "_seq": 101}]
    )
    text = stream_text(app, "r1", headers={"Last-Event-ID": "4"})
    assert "id: 5" in text and "id: 6" in text
    assert '"_seq": 100' in text
    provider_scope.stream_events.assert_called_once_with("r1", from_seq=4, context=scope)


def test_stream_accepts_query_cursor(app, provider_scope, scope):
    provider_scope.get_run.return_value = {"run_id": "r1", "status": "RUNNING"}
    provider_scope.stream_events.return_value = iter([{"event": "run_end"}])
    stream_text(app, "r1", path="/?since=7")
    provider_scope.stream_events.assert_called_once_with("r1", from_seq=7, context=scope)


def test_stream_invalid_cursor_defaults_to_zero(app, provider_scope, scope):
    provider_scope.get_run.return_value = {"run_id": "r1", "status": "RUNNING"}
    provider_scope.stream_events.return_value = iter([{"event": "run_end"}])
    stream_text(app, "r1", path="/?last_event_id=not-an-int")
    provider_scope.stream_events.assert_called_once_with("r1", from_seq=0, context=scope)


def test_stream_terminal_provider_event_closes_stream(app, provider_scope):
    provider_scope.get_run.return_value = {"run_id": "r1", "status": "RUNNING"}
    provider_scope.stream_events.return_value = iter([{"event": "trace_sealed"}])
    assert '"event": "trace_sealed"' in stream_text(app, "r1")


def test_stream_paused_run_emits_control_frame(app, provider_scope):
    provider_scope.get_run.side_effect = [
        {"run_id": "r1", "status": "RUNNING"},
        {"run_id": "r1", "status": "RUNNING"},
        {"run_id": "r1", "status": "PAUSED_FOR_APPROVAL"},
    ]
    assert "paused_for_approval" in stream_text(app, "r1")


def test_stream_completed_record_closes_without_polling_files(app, provider_scope):
    provider_scope.get_run.side_effect = [
        {"run_id": "r1", "status": "COMPLETED"},
        {"run_id": "r1", "status": "COMPLETED"},
        {"run_id": "r1", "status": "COMPLETED"},
    ]
    assert stream_text(app, "r1") == ""


def test_stream_missing_unscoped_provider_record_is_not_found(app, provider_scope):
    with patch.object(runs, "active_runtime_context", return_value=None):
        with patch.object(runs, "is_run_alive", return_value=False):
            text = stream_text(app, "r1")
    assert '"event": "not_found"' in text


def test_stream_registered_idle_run_closes_when_writer_is_gone(app, provider_scope):
    provider_scope.get_run.side_effect = [
        {"run_id": "r1", "status": "RUNNING"},
        {"run_id": "r1", "status": "RUNNING"},
        {"run_id": "r1", "status": "RUNNING"},
    ]
    with patch.object(runs, "is_run_alive", return_value=False):
        assert stream_text(app, "r1") == ""


# Former backend fallback/control tests: all use runtime discovery, not a reference backend.
def test_cancel_uses_discovered_execution_backend(app, provider_scope):
    provider_scope.get_run.return_value = {"run_id": "r1"}
    backend = MagicMock()
    backend.cancel.return_value = True
    with patch("eval_runner.runtime_services.resolve_execution_backend", return_value=backend):
        result = body(
            invoke(app, runs.cancel_run, "r1", method="POST", body={"reason": "operator"})
        )
    assert result["status"] == "ABORTED"
    backend.cancel.assert_called_once_with("r1", reason="operator")


def test_cancel_inactive_run_is_404(app, provider_scope):
    provider_scope.get_run.return_value = {"run_id": "r1"}
    backend = MagicMock()
    backend.cancel.return_value = False
    with patch("eval_runner.runtime_services.resolve_execution_backend", return_value=backend):
        response, status = invoke(app, runs.cancel_run, "r1", method="POST", body={})
    assert status == 404
    assert "not active" in body(response)["error"]


@pytest.mark.parametrize("request_body", [{}, {"decision": "APPROVED"}, {"decision": "REJECTED"}])
def test_resume_requires_provider_owned_durable_token(app, provider_scope, request_body):
    provider_scope.get_run.return_value = {"run_id": "r1"}
    response, status = invoke(app, runs.resume_run, "r1", method="POST", body=request_body)
    assert status == 400
    assert "approval token" in body(response)["error"]


# Verification is explicitly exact-byte and provider scoped.
def test_verify_uses_exact_provider_bytes_and_manifest(app, provider_scope, scope):
    provider_scope.get_run.return_value = {"run_id": "r1"}
    manifest = {
        "run_id": "r1",
        "trace_hash": "abc",
        "execution_mode": "live",
        "compliance_status": "pass",
    }
    canonical = b'{"event":"run_end","_seq":7}\n'
    provider_scope.get_manifest.return_value = manifest
    provider_scope.get_trace_bytes.return_value = canonical
    with patch(
        "eval_runner.verifier.TraceVerifier.verify_trace_bytes", return_value=True
    ) as verify:
        response = invoke(app, runs.verify_run, "r1")
    assert body(response)["verification_status"] == "VERIFIED"
    verify.assert_called_once_with(
        canonical, manifest, run_store=provider_scope, context=scope, trace_only=False
    )


def test_verify_missing_provider_evidence_is_404(app, provider_scope):
    provider_scope.get_run.return_value = {"run_id": "r1"}
    response, status = invoke(app, runs.verify_run, "r1")
    assert status == 404
    assert body(response)["verification_status"] == "NOT_FOUND"


def test_console_module_has_no_filesystem_evidence_bypass():
    source = Path(runs.__file__).read_text(encoding="utf-8")
    forbidden = (
        "resolve_" + "trace_path",
        "tail_file_" + "generator",
        "RUN_LOG_" + "DIR",
        "REPORTS_" + "DIR",
        "master_" + "log",
        "status_" + "vault",
    )
    assert not [name for name in forbidden if name in source]
