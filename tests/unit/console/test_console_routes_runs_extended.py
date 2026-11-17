"""Provider-native console run-route contracts.

Run directories may exist inside the local reference provider, but these tests
seed and inspect evidence solely through its public provider contract.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from agentv_runtime.discovery import set_extension
from eval_runner.console.routes.runs import (
    _assess_run_certification_readiness,
    _finalization_from_events,
    _run_is_in_active_context,
    _summary_from_provider,
    is_run_alive,
    project_public_certificate,
    register_report_action_provider,
    resolve_run_report_actions,
    run_bp,
)
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
    # A certified run (carries a certificate marker) whose provider-native verification fails.
    _seed_run(
        provider,
        "verify",
        manifest={"scenario_data": {"id": "scenario-a"}, "trace_hash": "sha3_256:00"},
    )
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


def test_report_action_provider_registration_and_fallbacks():
    try:

        def provider_two_arg(run_id, context):
            return {"href": f"/custom/{run_id}/report"}

        register_report_action_provider(provider_two_arg)
        actions = resolve_run_report_actions("run-1", context={"tenant": "t1"})
        assert actions["download_url"] == "/custom/run-1/report"

        def provider_one_arg(run_id):
            return {"download_url": f"/single/{run_id}"}

        register_report_action_provider(provider_one_arg)
        actions = resolve_run_report_actions("run-2")
        assert actions["download_url"] == "/single/run-2"

        def provider_error(run_id, context=None):
            raise RuntimeError("Provider failed")

        register_report_action_provider(provider_error)
        actions = resolve_run_report_actions("run-3")
        assert actions["mode"] == "basic"
        assert actions["download_url"] == "/api/v1/runs/run-3/report.pdf"

        register_report_action_provider(lambda run_id, ctx=None: "invalid")
        actions = resolve_run_report_actions("run-4")
        assert actions["mode"] == "basic"

        register_report_action_provider(None)
        set_extension("report_action_provider", lambda run_id, ctx=None: {"href": "/via/extension"})
        actions = resolve_run_report_actions("run-5")
        assert actions["download_url"] == "/via/extension"
    finally:
        register_report_action_provider(None)
        set_extension("report_action_provider", None)


def test_run_context_and_summary_helper_edge_cases(provider, client):
    with client.application.test_request_context():
        assert _run_is_in_active_context("non-existent-run", context=None) is False

        _seed_run(provider, "run-scoped-org", manifest={"context": {"org_id": "org-1"}})
        vault_org = provider._get_run_vault("run-scoped-org")
        run_rec_org = provider._read_json(provider._record_path(vault_org))
        run_rec_org["context"] = {"org_id": "org-1"}
        provider._write_json(provider._record_path(vault_org), run_rec_org)
        assert _run_is_in_active_context("run-scoped-org", context=None) is False

        _seed_run(provider, "run-scoped-meta")
        vault_meta = provider._get_run_vault("run-scoped-meta")
        run_rec_meta = provider._read_json(provider._record_path(vault_meta))
        run_rec_meta["metadata"] = {"runtime_context": {"tenant_id": "tenant-1"}}
        provider._write_json(provider._record_path(vault_meta), run_rec_meta)
        assert _run_is_in_active_context("run-scoped-meta", context=None) is False

        _seed_run(provider, "run-unscoped")
        assert _run_is_in_active_context("run-unscoped", context=None) is True

    assert _finalization_from_events(None) == {}
    assert _finalization_from_events([]) == {}
    assert _finalization_from_events(
        [{"event": "evaluator_finalization", "data": {"score": 1.0}}]
    ) == {"score": 1.0}
    assert _finalization_from_events(
        [{"event": "run_end", "data": {"finalization": {"score": 0.9}}}]
    ) == {"score": 0.9}
    assert _finalization_from_events(
        [{"event": "run_end", "finalization": {"score": 0.8}, "data": {}}]
    ) == {"score": 0.8}

    summary_corrupt = _summary_from_provider(
        {
            "run_id": "corrupt-summary",
            "manifest": {
                "execution_manifest": "invalid",
            },
        }
    )
    assert summary_corrupt["scenario"] == "unknown"

    summary_corrupt_configs = _summary_from_provider(
        {
            "run_id": "corrupt-configs",
            "manifest": {
                "execution_manifest": {
                    "runtime_config": "invalid",
                    "agent_config": "invalid",
                },
            },
        }
    )
    assert summary_corrupt_configs["execution_mode"] is None

    summary_live = _summary_from_provider(
        {
            "run_id": "live-run",
            "execution_mode": "live",
            "score": 0.99,
        }
    )
    assert summary_live["provisional"] is False
    assert summary_live["score"] == 0.99

    summary_hybrid = _summary_from_provider(
        {
            "run_id": "hybrid-run",
            "execution_mode": "hybrid",
        }
    )
    assert summary_hybrid["provisional"] is False


def test_list_runs_and_stream_runs_list_edge_branches(client, provider):
    _seed_run(
        provider,
        "run-with-cert",
        manifest={"vc_version": "1.0", "scenario_data": {"id": "s-cert"}},
    )
    with patch(
        "eval_runner.services.run_summary.RunSummaryService.get_authoritative_verdict",
        return_value="CERTIFIED_PASS",
    ):
        with patch.object(provider, "get_manifest", side_effect=OSError("Disk read failed")):
            resp = client.get("/api/runs")
            assert resp.status_code == 200

        resp = client.get("/api/runs")
        assert resp.status_code == 200
        run_row = next(r for r in resp.get_json()["runs"] if r["run_id"] == "run-with-cert")
        assert run_row["verification_status"] == "CERTIFIED_PASS"

        resp_stream = client.get("/api/v1/runs/stream-list")
        assert resp_stream.status_code == 200
        chunk_data = resp_stream.get_data(as_text=True)
        assert "run-with-cert" in chunk_data

        _seed_run(
            provider,
            "run-scope-x",
            manifest={"context": {"org_id": "scope-x"}},
        )
        vault_x = provider._get_run_vault("run-scope-x")
        rec_x = provider._read_json(provider._record_path(vault_x))
        rec_x["context"] = {"org_id": "scope-x"}
        provider._write_json(provider._record_path(vault_x), rec_x)

        with patch("eval_runner.console.routes.runs._run_is_in_active_context", return_value=False):
            with patch(
                "eval_runner.console.routes.runs.active_runtime_context",
                return_value={"org_id": "scope-x"},
            ):
                resp_stream_filtered = client.get("/api/v1/runs/stream-list")
                assert resp_stream_filtered.status_code == 200
                chunk_filtered = resp_stream_filtered.get_data(as_text=True)
                assert chunk_filtered == "data: []\n\n"


def test_download_run_report_pdf_error_branches(client, provider, tmp_path):
    resp_404 = client.get("/api/v1/runs/missing-run-id/report.pdf")
    assert resp_404.status_code == 404

    _seed_run(provider, "pdf-run", manifest={"execution_manifest": "non-dict"})

    with patch("eval_runner.console.routes.runs._run_is_in_active_context", return_value=True):
        with patch.object(provider, "get_run", return_value=None):
            resp_no_run = client.get("/api/v1/runs/pdf-run/report.pdf")
            assert resp_no_run.status_code == 404
            assert resp_no_run.get_json()["error"] == "Run not found"

    with patch("eval_runner.console.pdf_service.generate_run_pdf", return_value=False):
        resp_fail = client.get("/api/v1/runs/pdf-run/report.pdf")
        assert resp_fail.status_code == 503
        assert resp_fail.get_json()["error"] == "PDF report generation failed"

    def fake_generate_bad_pdf(report_data, out_path):
        Path(out_path).write_bytes(b"NOT_A_PDF_STREAM")
        return True

    with patch(
        "eval_runner.console.pdf_service.generate_run_pdf", side_effect=fake_generate_bad_pdf
    ):
        resp_bad = client.get("/api/v1/runs/pdf-run/report.pdf")
        assert resp_bad.status_code == 503
        assert resp_bad.get_json()["error"] == "No PDF rendering engine is available"


def test_get_run_report_actions_scoped_denial(client, provider):
    _seed_run(provider, "report-action-run")
    with patch(
        "eval_runner.console.routes.runs.active_runtime_context", return_value={"org_id": "scope-z"}
    ):
        with patch("eval_runner.console.routes.runs._run_is_in_active_context", return_value=False):
            resp = client.get("/api/v1/runs/report-action-run/report-actions")
            assert resp.status_code == 404

    resp_ok = client.get("/api/v1/runs/report-action-run/report-actions")
    assert resp_ok.status_code == 200


def test_assess_run_certification_readiness_edge_branches():
    run_unspec = {"run_id": "r-unspec"}
    manifest_unspec = {}
    events_live = [
        {"event": "step", "data": {"execution_mode": "live", "provisional": False}},
        {"event": "evaluator_finalization", "outcome": "pass"},
    ]
    elig, reasons = _assess_run_certification_readiness(
        run=run_unspec,
        manifest=manifest_unspec,
        events=events_live,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=5,
    )
    assert elig == "eligible"
    assert reasons == []

    events_multi = [
        {"event": "step", "data": {}},
        {"event": "step", "data": {"provisional": False}},
        {"event": "evaluator_finalization", "outcome": "pass"},
    ]
    elig_multi, _ = _assess_run_certification_readiness(
        run={"run_id": "r-multi", "execution_mode": "live"},
        manifest={},
        events=events_multi,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=5,
    )
    assert elig_multi == "eligible"

    elig_prov_branch, _ = _assess_run_certification_readiness(
        run={"run_id": "r-prov-fixed", "provisional": False},
        manifest={},
        events=[
            {"event": "step", "data": {"execution_mode": "live"}},
            {"event": "evaluator_finalization", "outcome": "pass"},
        ],
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=5,
    )
    assert elig_prov_branch == "eligible"

    events_live_tool = [
        {"event": "tool_call", "provenance": "live"},
        {"event": "evaluator_finalization", "outcome": "pass"},
    ]
    elig_live_tool, _ = _assess_run_certification_readiness(
        run={"run_id": "r-live-tool", "execution_mode": "live", "provisional": False},
        manifest={},
        events=events_live_tool,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=5,
    )
    assert elig_live_tool == "eligible"

    events_sim_flag = [
        {"event": "step", "has_simulated_tools": True},
        {"event": "evaluator_finalization", "outcome": "pass"},
    ]
    elig, reasons = _assess_run_certification_readiness(
        run=run_unspec,
        manifest={"execution_mode": "live", "provisional": False},
        events=events_sim_flag,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=5,
    )
    assert elig == "ineligible"
    assert any("simulated tool" in r for r in reasons)

    events_tool_sim = [
        {"event": "tool_call", "provenance": "simulated"},
        {"event": "evaluator_finalization", "outcome": "pass"},
    ]
    elig, reasons = _assess_run_certification_readiness(
        run=run_unspec,
        manifest={"execution_mode": "live", "provisional": False},
        events=events_tool_sim,
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=5,
    )
    assert elig == "ineligible"
    assert any("simulated tool" in r for r in reasons)

    elig_tampered, reasons_tampered = _assess_run_certification_readiness(
        run={
            "run_id": "r-tampered",
            "trace_integrity": "CORRUPTED",
            "verification_status": "FAILED_VERIFICATION",
        },
        manifest={"corrupted": True},
        events=[{"event": "evaluator_finalization", "outcome": "fail"}],
        raw_status="COMPLETED",
        terminal=True,
        evidence_nodes=5,
    )
    assert elig_tampered == "ineligible"
    assert any("integrity" in r.lower() for r in reasons_tampered)


def test_get_run_status_stalled_and_not_found_branches(client, provider):
    resp_404 = client.get("/api/v1/runs/non-existent-status")
    assert resp_404.status_code == 404

    with patch("eval_runner.console.routes.runs._run_is_in_active_context", return_value=True):
        with patch.object(provider, "get_run", return_value=None):
            resp_missing = client.get("/api/v1/runs/missing-status")
            assert resp_missing.status_code == 404
            assert resp_missing.get_json()["error"] == "Run not found"

    _seed_run(provider, "stalled-run", events=[{"event": "step", "_seq": 1}])
    vault_stalled = provider._get_run_vault("stalled-run")
    run_rec = provider._read_json(provider._record_path(vault_stalled))
    run_rec["updated_at"] = time.time() - 400
    run_rec["status"] = "RUNNING"
    provider._write_json(provider._record_path(vault_stalled), run_rec)

    with patch("eval_runner.console.routes.runs.is_run_alive", return_value=False):
        resp = client.get("/api/v1/runs/stalled-run")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "STALLED"

    with patch(
        "agentv_runtime.evidence_graph.build_evidence_graph_from_events",
        side_effect=RuntimeError("Graph failed"),
    ):
        resp_graph_fail = client.get("/api/v1/runs/stalled-run")
        assert resp_graph_fail.status_code == 200
        assert resp_graph_fail.get_json()["evidence_nodes"] == 0


def test_cancel_and_resume_run_branches(client, provider, monkeypatch):
    _seed_run(provider, "cancel-run")

    with patch("eval_runner.console.routes.runs._run_is_in_active_context", return_value=False):
        resp = client.post("/api/v1/runs/cancel-run/cancel")
        assert resp.status_code == 404

        resp = client.post("/api/v1/runs/cancel-run/resume")
        assert resp.status_code == 404

    with client.session_transaction() as sess:
        sess["user"] = {"id": "u1", "permissions": ["*"]}

    with patch.dict(os.environ, {"AGENTV_TEST_AUTH_BYPASS": "0"}):
        with patch("eval_runner.console.routes.runs.g", MagicMock(verified_principal=None)):
            resp_unauth = client.post("/api/v1/runs/cancel-run/resume", json={})
            assert resp_unauth.status_code == 401
            assert (
                resp_unauth.get_json()["error"]
                == "Unauthorized: An authenticated principal is required to resolve approvals"
            )

    resp_bad_decision = client.post("/api/v1/runs/cancel-run/resume", json={"decision": "MAYBE"})
    assert resp_bad_decision.status_code == 400

    resp_missing_tok = client.post("/api/v1/runs/cancel-run/resume", json={"decision": "APPROVED"})
    assert resp_missing_tok.status_code == 400

    mock_store = MagicMock()
    mock_store.get_request.return_value = None
    with patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_store):
        resp_tok_404 = client.post(
            "/api/v1/runs/cancel-run/resume",
            json={"resumption_token": "missing-tok", "decision": "APPROVED"},
        )
        assert resp_tok_404.status_code == 404

    mock_req_wrong_run = MagicMock(run_id="other-run", status="PENDING")
    mock_store.get_request.return_value = mock_req_wrong_run
    with patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_store):
        resp_wrong_run = client.post(
            "/api/v1/runs/cancel-run/resume",
            json={"resumption_token": "tok-1", "decision": "APPROVED"},
        )
        assert resp_wrong_run.status_code == 409

    mock_req_resolved = MagicMock(run_id="cancel-run", status="APPROVED")
    mock_store.get_request.return_value = mock_req_resolved
    with patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_store):
        resp_not_pending = client.post(
            "/api/v1/runs/cancel-run/resume",
            json={"resumption_token": "tok-1", "decision": "APPROVED"},
        )
        assert resp_not_pending.status_code == 409

    mock_req_pending = MagicMock(run_id="cancel-run", status="PENDING", required_role="secops")
    mock_store.get_request.return_value = mock_req_pending
    principal = {"name": "Alice", "roles": "admin", "role": "secops"}

    mock_g = MagicMock()
    mock_g.verified_principal = principal
    with patch("eval_runner.console.routes.runs.g", mock_g):
        with patch("eval_runner.runtime_services.resolve_approval_store", return_value=mock_store):
            with patch(
                "eval_runner.session_components.approval_manager.SessionApprovalManager.resolve_durable_request"
            ) as mock_resolve:
                mock_resolve.side_effect = PermissionError("Not allowed")
                resp_perm = client.post(
                    "/api/v1/runs/cancel-run/resume",
                    json={"resumption_token": "tok-1", "decision": "APPROVED"},
                )
                assert resp_perm.status_code == 403

                mock_resolve.side_effect = ValueError("Corrupt request")
                resp_val = client.post(
                    "/api/v1/runs/cancel-run/resume",
                    json={"resumption_token": "tok-1", "decision": "APPROVED"},
                )
                assert resp_val.status_code == 409

                mock_resolve.side_effect = None
                resp_rej = client.post(
                    "/api/v1/runs/cancel-run/resume",
                    json={"resumption_token": "tok-1", "decision": "REJECTED"},
                )
                assert resp_rej.status_code == 200
                assert resp_rej.get_json()["status"] == "REJECTED"

                mock_backend = MagicMock()
                mock_backend.resume.side_effect = RuntimeError("Checkpoint unavailable")
                with patch(
                    "eval_runner.runtime_services.resolve_execution_backend",
                    return_value=mock_backend,
                ):
                    resp_no_ckpt = client.post(
                        "/api/v1/runs/cancel-run/resume",
                        json={"resumption_token": "tok-1", "decision": "APPROVED"},
                    )
                    assert resp_no_ckpt.status_code == 404

                mock_backend.resume.side_effect = RuntimeError("Fatal crash")
                with patch(
                    "eval_runner.runtime_services.resolve_execution_backend",
                    return_value=mock_backend,
                ):
                    resp_fatal = client.post(
                        "/api/v1/runs/cancel-run/resume",
                        json={"resumption_token": "tok-1", "decision": "APPROVED"},
                    )
                    assert resp_fatal.status_code == 500


def test_certificates_and_verification_routes_branches(client, provider):
    resp_cert_404 = client.get("/api/v1/certificates/unknown-run")
    assert resp_cert_404.status_code == 404

    with patch("eval_runner.console.routes.runs._run_is_in_active_context", return_value=True):
        with patch.object(provider, "get_run", return_value=None):
            resp_cert_none = client.get("/api/v1/certificates/cert-none-run")
            assert resp_cert_none.status_code == 404
            assert resp_cert_none.get_json()["error"] == "Certificate not found"

    # Certificate corrupted or missing manifest branches
    _seed_run(provider, "cert-corrupt-run")
    vault_corrupt = provider._get_run_vault("cert-corrupt-run")
    rec_corrupt = provider._read_json(provider._record_path(vault_corrupt))
    rec_corrupt["corrupted"] = True
    provider._write_json(provider._record_path(vault_corrupt), rec_corrupt)
    resp_corrupt = client.get("/api/v1/certificates/cert-corrupt-run")
    assert resp_corrupt.status_code == 500

    _seed_run(provider, "cert-err-run")
    with patch.object(provider, "get_manifest", side_effect=ValueError("corrupt json structure")):
        resp_err = client.get("/api/v1/certificates/cert-err-run")
        assert resp_err.status_code == 500

    with patch.object(provider, "get_manifest", return_value=None):
        resp_empty_m = client.get("/api/v1/certificates/cert-err-run")
        assert resp_empty_m.status_code == 404

    _seed_run(provider, "stream-hb-run")
    with patch("eval_runner.console.routes.runs.is_run_alive", side_effect=[True] * 5 + [False]):
        with patch.object(provider, "stream_events", return_value=iter([])):
            with patch("eval_runner.console.routes.runs.time.sleep", return_value=None):
                resp_hb = client.get("/api/v1/runs/stream-hb-run/stream")
                data = resp_hb.get_data(as_text=True)
                assert ": heartbeat" in data

    _seed_run(provider, "stream-loop-sleep", status="RUNNING")
    iter_calls = 0

    def mock_stream_events(run_id, from_seq=0, context=None):
        nonlocal iter_calls
        iter_calls += 1
        if iter_calls == 1:
            return [{"_seq": 1, "event": "step"}]
        return [{"_seq": 2, "event": "run_end"}]

    with patch.object(provider, "stream_events", side_effect=mock_stream_events):
        with patch("eval_runner.console.routes.runs.time.sleep", return_value=None):
            resp_sleep = client.get("/api/v1/runs/stream-loop-sleep/stream")
            data_sleep = resp_sleep.get_data(as_text=True)
            assert '"event": "step"' in data_sleep
            assert '"event": "run_end"' in data_sleep

    _seed_run(provider, "stream-nonterm-run", status="COMPLETED")
    with patch.object(provider, "stream_events", return_value=iter([{"_seq": 1, "event": "step"}])):
        resp_nonterm = client.get("/api/v1/runs/stream-nonterm-run/stream")
        data_nonterm = resp_nonterm.get_data(as_text=True)
        assert '"event": "step"' in data_nonterm

    with patch("eval_runner.console.routes.runs.is_run_alive", return_value=True):
        with patch.object(provider, "stream_events", return_value=iter([])):
            with patch("eval_runner.console.routes.runs.time.sleep", return_value=None):
                resp_loop = client.get("/api/v1/runs/stream-hb-run/stream")
                data_loop = resp_loop.get_data(as_text=True)
                assert ": heartbeat" in data_loop

    with patch("eval_runner.console.routes.runs.active_runtime_context", return_value=None):
        resp_unavail = client.get("/api/v1/runs/stream-missing-run/stream")
        data = resp_unavail.get_data(as_text=True)
        assert "not_found" in data

    with patch("eval_runner.console.routes.runs._run_is_in_active_context", return_value=False):
        resp_verif_scoped = client.get("/api/v1/runs/stream-hb-run/verify")
        assert resp_verif_scoped.status_code == 404

    with patch.object(provider, "get_trace_bytes", return_value=None):
        resp_verif_404 = client.get("/api/v1/runs/stream-hb-run/verify")
        assert resp_verif_404.status_code == 404
        assert resp_verif_404.get_json()["verification_status"] == "NOT_FOUND"

    _seed_run(
        provider,
        "verif-non-list-prov",
        manifest={"scenario_data": {"id": "s"}, "provenance_chain": "not-a-list"},
    )
    with patch(
        "eval_runner.verifier.TraceVerifier.verify_run",
        return_value={"is_valid": True, "verification_status": "VERIFIED"},
    ):
        resp_prov = client.get("/api/v1/runs/verif-non-list-prov/verify")
        assert resp_prov.status_code == 200
        assert resp_prov.get_json()["has_certificate"] is False

    pub_proj = project_public_certificate(
        {"run_id": "r1", "vc_version": "1.0", "internal_secret": "sensitive"}
    )
    assert pub_proj.get("run_id") == "r1"
    assert pub_proj.get("vc_version") == "1.0"
    assert "internal_secret" not in pub_proj


def test_is_run_alive_helper():
    run_id = "test-live-thread-id"
    assert is_run_alive(run_id) is False

    t = threading.Thread(name=f"eval-{run_id}", target=lambda: time.sleep(0.1))
    t.start()
    try:
        assert is_run_alive(run_id) is True
    finally:
        t.join()
