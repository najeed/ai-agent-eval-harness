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
from eval_runner import config
from eval_runner.console.app import create_app
from eval_runner.reference.local_run_store import LocalFileRunStore


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


def test_resume_derives_reviewer_from_verified_principal(app, provider_scope):
    from unittest.mock import MagicMock

    from flask import g

    provider_scope.get_run.return_value = {"run_id": "r1"}
    approval_store = MagicMock()
    req = MagicMock(run_id="r1", status="PENDING", required_role="compliance_officer")
    approval_store.get_request.return_value = req

    with patch("eval_runner.runtime_services.resolve_approval_store", return_value=approval_store):
        # 1. Reject when principal lacks required_role
        with app.test_request_context(
            "/v1/runs/r1/resume", method="POST", json={"approval_token": "tok1"}
        ):
            g.verified_principal = {"name": "alice", "roles": ["developer"]}
            res, status = runs.resume_run("r1")
            assert status == 403
            assert "Reviewer role does not satisfy" in res.get_json()["error"]

        # 2. Accept and derive reviewer when principal has required_role
        mock_backend = MagicMock()
        mock_backend.resume.return_value = {"status": "RUNNING", "run_id": "r1"}
        with (
            patch(
                "eval_runner.session_components.approval_manager.SessionApprovalManager.resolve_durable_request"
            ) as resolve_mock,
            patch(
                "eval_runner.runtime_services.resolve_execution_backend",
                return_value=mock_backend,
            ),
            patch.object(runs, "_run_is_in_active_context", return_value=True),
            app.test_request_context(
                "/v1/runs/r1/resume", method="POST", json={"approval_token": "tok1"}
            ),
        ):
            g.verified_principal = {"name": "alice", "roles": ["compliance_officer"]}
            res = runs.resume_run("r1")
            assert res.status_code == 200
            resolve_mock.assert_called_once()
            assert resolve_mock.call_args.kwargs["decided_by"] == "alice"


def test_get_verification_certificate_sanitizes_credentials(app, provider_scope):
    from flask import g

    provider_scope.get_run.return_value = {"run_id": "r1"}
    manifest = {
        "run_id": "r1",
        "scenario_data": {
            "metadata": {
                "state_authorities": {
                    "ledger": {
                        "url": "https://bank.example/api",
                        "headers": {"Authorization": "Bearer super-secret-key-123"},
                    }
                }
            }
        },
    }
    provider_scope.get_manifest.return_value = manifest

    with (
        patch.object(runs, "_run_is_in_active_context", return_value=True),
        app.test_request_context("/v1/certificates/r1", method="GET"),
    ):
        g.verified_principal = {"name": "auditor", "roles": ["auditor"]}
        res = runs.get_verification_certificate("r1")
        data = res.get_json()
        assert data["run_id"] == "r1"
        auth_header = data["scenario_data"]["metadata"]["state_authorities"]["ledger"]["headers"][
            "Authorization"
        ]
        assert auth_header == "[REDACTED]"


@pytest.fixture
def run_app_and_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / "runs"
    reports_dir = tmp_path / "reports"
    keys_dir = tmp_path / "keys"
    runs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    keys_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr(config, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(config, "TRUST_ROOT", keys_dir)

    store = LocalFileRunStore(log_dir=runs_dir)
    application = create_app(run_store=store)
    application.config["TESTING"] = True
    return application, store


def test_certificate_endpoint_marks_unverified_manifest_explicitly(run_app_and_store):
    """/v1/certificates/<run_id> invokes TraceVerifier and tags unverified status."""
    app, store = run_app_and_store
    client = app.test_client()

    run_id = "run-unverified-cert-test"
    store.create_run(run_id, scenario_id="sec-1")

    manifest = {
        "run_id": run_id,
        "vc_version": "2.0.0",
        "status": "PASS",
        "verification_status": "CLAIMED_PASS",
        "certificate": {"signature": "mock_unverified_sig"},
    }
    store.save_run_manifest(run_id, manifest)

    mock_verif = MagicMock()
    mock_verif.is_valid = False
    mock_verif.certificate_valid = False
    mock_verif.cryptographically_valid = False
    mock_verif.file_integrity_valid = True
    mock_verif.evaluation_passed = False
    mock_verif.is_authoritative = False
    mock_verif.certificate_authoritative = False
    mock_verif.status = "UNVERIFIED"
    mock_verif.terminal_verdict = "UNVERIFIED"
    mock_verif.claim_scope = {}

    with patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=mock_verif):
        resp = client.get(f"/v1/certificates/{run_id}")
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["verification_status"] == "UNVERIFIED"
        assert data["certificate_authoritative"] is False
        assert data["is_authoritative"] is False
        assert data["certificate_valid"] is False
        assert data["cryptographically_valid"] is False
        assert data["file_integrity_valid"] is True
        assert data["evaluation_passed"] is False

    with patch(
        "eval_runner.verifier.TraceVerifier.verify_run",
        side_effect=RuntimeError("verifier error"),
    ):
        resp2 = client.get(f"/v1/certificates/{run_id}")
        assert resp2.status_code == 200
        data2 = resp2.get_json()
        assert data2["verification_status"] == "UNVERIFIED"
        assert data2["certificate_authoritative"] is False
        assert data2["is_authoritative"] is False


def test_public_certificate_endpoint_reflects_authoritative_verification(
    run_app_and_store,
):
    """/v1/certificates/<run_id>/public projects verified facts without unverified claims."""
    app, store = run_app_and_store
    client = app.test_client()

    run_id = "run-public-cert-test"
    store.create_run(run_id, scenario_id="sec-1")

    manifest = {
        "run_id": run_id,
        "vc_version": "2.0.0",
        "status": "PASS",
        "algorithm": "ML-DSA-65",
        "signature": "valid_pqc_sig",
        "is_public": True,
    }
    store.save_run_manifest(run_id, manifest)

    mock_verif = MagicMock()
    mock_verif.is_valid = True
    mock_verif.certificate_valid = True
    mock_verif.cryptographically_valid = True
    mock_verif.file_integrity_valid = True
    mock_verif.evaluation_passed = True
    mock_verif.is_authoritative = True
    mock_verif.status = "CERTIFIED_PASS"
    mock_verif.terminal_verdict = "CERTIFIED_PASS"
    mock_verif.claim_scope = {}

    with patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=mock_verif):
        resp = client.get(f"/v1/certificates/{run_id}/public")
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["verification_status"] == "CERTIFIED_PASS"
        assert data["certificate_authoritative"] is True
        assert data["certificate_valid"] is True
        assert data["cryptographically_valid"] is True
        assert data["algorithm"] == "ML-DSA-65"


def test_certificate_endpoints_error_and_edge_branches(run_app_and_store):
    """Test error paths in /v1/certificates/<run_id> and public projection."""
    app, store = run_app_and_store
    client = app.test_client()

    # 1. Non-existent run -> 404
    resp = client.get("/v1/certificates/run-non-existent")
    assert resp.status_code == 404
    resp_pub = client.get("/v1/certificates/run-non-existent/public")
    assert resp_pub.status_code == 404

    # 2. Corrupted run record -> 500
    corrupt_id = "run-corrupted-test"
    store.create_run(corrupt_id, scenario_id="s1")
    vault = store._get_run_vault(corrupt_id)
    store._write_json_durable(store._record_path(vault), {"corrupted": True, "run_id": corrupt_id})
    resp_corrupt = client.get(f"/v1/certificates/{corrupt_id}")
    assert resp_corrupt.status_code == 500
    resp_corrupt_pub = client.get(f"/v1/certificates/{corrupt_id}/public")
    assert resp_corrupt_pub.status_code == 500

    # 3. Manifest missing on disk -> 404
    valid_id = "run-no-manifest-test"
    store.create_run(valid_id, scenario_id="s1")
    resp_no_man = client.get(f"/v1/certificates/{valid_id}")
    assert resp_no_man.status_code == 404
    resp_no_man_pub = client.get(f"/v1/certificates/{valid_id}/public")
    assert resp_no_man_pub.status_code == 404

    # 4. Manifest corruption exception -> 500
    with patch.object(store, "get_manifest", side_effect=ValueError("Corrupt manifest")):
        resp_man_err = client.get(f"/v1/certificates/{valid_id}")
        assert resp_man_err.status_code == 500
        resp_man_err_pub = client.get(f"/v1/certificates/{valid_id}/public")
        assert resp_man_err_pub.status_code == 500

    # 5. Manifest exception other than corrupt raises
    with patch.object(store, "get_manifest", side_effect=ValueError("schema mismatch")):
        with pytest.raises(ValueError, match="schema mismatch"):
            client.get(f"/v1/certificates/{valid_id}")
        with pytest.raises(ValueError, match="schema mismatch"):
            client.get(f"/v1/certificates/{valid_id}/public")

    # 6. Unverified manifest with NO status key
    no_status_id = "run-no-status-manifest"
    store.create_run(no_status_id, scenario_id="s1")
    store.save_run_manifest(no_status_id, {"run_id": no_status_id, "vc_version": "2.0.0"})
    with patch("eval_runner.verifier.TraceVerifier.verify_run", side_effect=RuntimeError("fail")):
        resp_no_stat = client.get(f"/v1/certificates/{no_status_id}")
        assert resp_no_stat.status_code == 200
        assert resp_no_stat.get_json()["verification_status"] == "UNVERIFIED"

    # 7. Inactive context returns 404
    with patch("eval_runner.console.routes.runs._run_is_in_active_context", return_value=False):
        resp_ctx = client.get(f"/v1/certificates/{no_status_id}")
        assert resp_ctx.status_code == 404


def test_public_certificate_publication_control_and_projection(run_app_and_store):
    """Verify private runs return 403 and public projections strip sensitive data."""
    import os

    from eval_runner.console.routes.runs import (
        PUBLIC_CERTIFICATE_FIELDS,
        project_public_certificate,
    )

    app, store = run_app_and_store
    client = app.test_client()

    # 1. Private run returns 403 Forbidden on public endpoint
    priv_run_id = "run-private-cert-test"
    store.create_run(priv_run_id, scenario_id="sec-1")
    store.save_run_manifest(
        priv_run_id,
        {
            "run_id": priv_run_id,
            "vc_version": "2.0.0",
            "is_private": True,
            "status": "PASS",
        },
    )
    resp_priv = client.get(f"/v1/certificates/{priv_run_id}/public")
    assert resp_priv.status_code == 403
    assert "private" in resp_priv.get_json()["error"].lower()

    # 2. Explicit is_public=False returns 403 Forbidden
    no_pub_run_id = "run-no-public-test"
    store.create_run(no_pub_run_id, scenario_id="sec-1")
    store.save_run_manifest(
        no_pub_run_id,
        {
            "run_id": no_pub_run_id,
            "vc_version": "2.0.0",
            "is_public": False,
            "status": "PASS",
        },
    )
    resp_no_pub = client.get(f"/v1/certificates/{no_pub_run_id}/public")
    assert resp_no_pub.status_code == 403

    # 2b. Secure by default: Unmarked run without is_public returns 403
    default_unmarked_id = "run-unmarked-public-test"
    store.create_run(default_unmarked_id, scenario_id="sec-1")
    store.save_run_manifest(
        default_unmarked_id,
        {
            "run_id": default_unmarked_id,
            "vc_version": "2.0.0",
            "status": "PASS",
        },
    )
    resp_unmarked = client.get(f"/v1/certificates/{default_unmarked_id}/public")
    assert resp_unmarked.status_code == 403
    assert "private" in resp_unmarked.get_json()["error"].lower()

    # 2c. Global toggle AGENTV_ENABLE_PUBLIC_CERTIFICATES allows publication
    os.environ["AGENTV_ENABLE_PUBLIC_CERTIFICATES"] = "true"
    try:
        with patch(
            "eval_runner.verifier.TraceVerifier.verify_run", return_value={"is_valid": True}
        ):
            resp_env_pub = client.get(f"/v1/certificates/{default_unmarked_id}/public")
            assert resp_env_pub.status_code == 200
    finally:
        os.environ.pop("AGENTV_ENABLE_PUBLIC_CERTIFICATES", None)

    # 3. project_public_certificate strips internal/sensitive fields
    full_manifest = {
        "run_id": "run-proj-test",
        "vc_version": "2.0.0",
        "status": "CERTIFIED_PASS",
        "verification_status": "CERTIFIED_PASS",
        "certificate_authoritative": True,
        "is_authoritative": True,
        "evidence_valid": True,
        "certificate_valid": True,
        "cryptographically_valid": True,
        "file_integrity_valid": True,
        "evaluation_passed": True,
        "algorithm": "ML-DSA-65",
        "signature": "valid_sig",
        "raw_evidence": {"private_key": "sec_12345"},
        "scenario_inputs": {"customer_ssn": "000-11-2222"},
        "internal_jwt_secret": "secret_abc",
        "environment_variables": {"API_KEY": "sk-123456"},
    }
    projected = project_public_certificate(full_manifest)
    assert "raw_evidence" not in projected
    assert "scenario_inputs" not in projected
    assert "internal_jwt_secret" not in projected
    assert "environment_variables" not in projected
    assert set(projected.keys()).issubset(PUBLIC_CERTIFICATE_FIELDS)
    assert projected["run_id"] == "run-proj-test"
    assert projected["algorithm"] == "ML-DSA-65"


def test_certificate_endpoints_preserve_attested_fail(run_app_and_store):
    """Verify authoritative ATTESTED_FAIL is preserved and not collapsed to UNVERIFIED."""
    app, store = run_app_and_store
    client = app.test_client()

    run_id = "run-attested-fail-test"
    store.create_run(run_id, scenario_id="audit-1")
    manifest = {
        "run_id": run_id,
        "vc_version": "2.0.0",
        "status": "FAILED",
        "verification_status": "ATTESTED_FAIL",
        "is_public": True,
    }
    store.save_run_manifest(run_id, manifest)

    mock_verif = MagicMock()
    mock_verif.is_valid = False
    mock_verif.certificate_valid = False
    mock_verif.cryptographically_valid = True
    mock_verif.file_integrity_valid = True
    mock_verif.evaluation_passed = False
    mock_verif.is_authoritative = True
    mock_verif.certificate_authoritative = True
    mock_verif.status = "ATTESTED_FAIL"
    mock_verif.terminal_verdict = "ATTESTED_FAIL"
    mock_verif.claim_scope = {"scope": "external_business_state"}

    with patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=mock_verif):
        resp = client.get(f"/v1/certificates/{run_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["verification_status"] == "ATTESTED_FAIL"
        assert data["terminal_verdict"] == "ATTESTED_FAIL"
        assert data["certificate_authoritative"] is True
        assert data["evaluation_passed"] is False

        resp_pub = client.get(f"/v1/certificates/{run_id}/public")
        assert resp_pub.status_code == 200
        pub_data = resp_pub.get_json()
        assert pub_data["verification_status"] == "ATTESTED_FAIL"
        assert pub_data["terminal_verdict"] == "ATTESTED_FAIL"
        assert pub_data["certificate_authoritative"] is True


def test_run_verify_endpoint_preserves_independent_validity_dimensions(run_app_and_store):
    """Endpoint preserves cryptographically_valid independently from is_valid."""
    app, store = run_app_and_store
    client = app.test_client()

    run_id = "run-verify-dimensions-test"
    store.create_run(run_id, scenario_id="sec-1")
    manifest = {
        "run_id": run_id,
        "vc_version": "2.0.0",
        "status": "FAIL",
        "signatures": [{"identity": "sec-oracle", "algorithm": "ED25519"}],
    }
    store.save_run_manifest(run_id, manifest)
    store.append_events(run_id, [{"event": "start"}])

    mock_verif_result = {
        "is_valid": False,
        "cryptographically_valid": True,
        "file_integrity_valid": True,
        "certificate_valid": True,
        "certificate_authoritative": True,
        "verification_status": "ATTESTED_FAIL",
        "claim_scope": "external_business_state",
    }

    with patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=mock_verif_result):
        resp = client.get(f"/api/v1/runs/{run_id}/verify")
        assert resp.status_code == 200
        data = resp.get_json()

        assert data["is_valid"] is False
        assert data["cryptographically_valid"] is True
        assert data["file_integrity_valid"] is True
        assert data["certificate_valid"] is True
        assert data["certificate_authoritative"] is True
        assert data["verification_status"] == "ATTESTED_FAIL"
        assert data["algorithm"] == "ED25519"
        assert data["signer_identity"] == "sec-oracle"


def test_readiness_blocks_tampered_or_unverified_runs():
    """Readiness blocks runs with tampered trace or failed verification."""
    from eval_runner.console.routes.runs import _assess_run_certification_readiness

    base_run = {"run_id": "r-tamper", "execution_mode": "live"}
    manifest = {}
    events = [
        {"event": "run_start", "data": {"execution_mode": "live"}},
        {"event": "evaluator_finalization", "data": {"outcome": "pass"}},
    ]

    # Tampered trace integrity blocks certification
    tampered_run = dict(base_run, trace_integrity="TAMPERED")
    elig, reasons = _assess_run_certification_readiness(
        run=tampered_run,
        manifest=manifest,
        events=events,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=3,
    )
    assert elig == "ineligible"
    assert any("Trace integrity verification failed" in r for r in reasons)

    # Failed verification blocks certification
    failed_verif_run = dict(base_run, verification_status="FAILED_VERIFICATION")
    elig_v, reasons_v = _assess_run_certification_readiness(
        run=failed_verif_run,
        manifest=manifest,
        events=events,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=3,
    )
    assert elig_v == "ineligible"
    assert any("failed cryptographic verification" in r for r in reasons_v)

    # Corrupted manifest blocks certification
    corrupt_manifest = {"corrupted": True}
    elig_c, reasons_c = _assess_run_certification_readiness(
        run=base_run,
        manifest=corrupt_manifest,
        events=events,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=3,
    )
    assert elig_c == "ineligible"
    assert any("corrupted" in r for r in reasons_c)


def test_has_certificate_disentangled_from_artifact_presence(run_app_and_store):
    """Verification endpoint does not set certificate_valid from artifact presence alone."""
    app, store = run_app_and_store
    client = app.test_client()

    run_id = "run-failed-cert-presence"
    store.create_run(run_id, scenario_id="sec-1")
    store.save_run_manifest(
        run_id,
        {
            "run_id": run_id,
            "vc_version": "2.0.0",
            "certificate": {"signature": "invalid"},
            "verification_status": "FAILED_VERIFICATION",
            "status": "FAILED_VERIFICATION",
        },
    )
    store.append_events(run_id, [{"event": "start"}])

    mock_verif = {
        "is_valid": False,
        "cryptographically_valid": False,
        "file_integrity_valid": True,
        "certificate_valid": False,
        "certificate_authoritative": False,
        "verification_status": "FAILED_VERIFICATION",
    }
    with patch("eval_runner.verifier.TraceVerifier.verify_run", return_value=mock_verif):
        resp = client.get(f"/api/v1/runs/{run_id}/verify")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["has_certificate"] is True
        assert data["certificate_valid"] is False

    corrupt_run_id = "run-corrupted-manifest"
    store.create_run(corrupt_run_id, scenario_id="sec-1")
    store.save_run_manifest(
        corrupt_run_id,
        {
            "run_id": corrupt_run_id,
            "corrupted": True,
            "certificate": {"pkg": True},
        },
    )
    from eval_runner.console.routes.runs import _summary_from_provider

    summary = _summary_from_provider(
        {
            "run_id": corrupt_run_id,
            "corrupted": True,
            "manifest": {"corrupted": True, "certificate": {"pkg": True}},
        }
    )
    assert summary["has_certificate"] is False
