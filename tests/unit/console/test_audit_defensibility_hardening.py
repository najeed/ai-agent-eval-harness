"""
tests/unit/console/test_audit_defensibility_hardening.py
Verification suite for enterprise-grade audit defensibility and hardening invariants.
Covers:
  - Path traversal protection on certification and verification routes
  - Provisional execution mode certification refusal
  - Scenario lifecycle bypass closing (save_scenario server-authoritative Draft default)
  - Preflight connectivity probe truthfulness (HTTP 4xx/5xx handling)
  - Canonical certificate locator parity across vault and reports
  - Flight recorder fail-closed under AES_CERTIFICATION_MODE=1 without non-null signer
"""

from datetime import UTC, datetime, timedelta

import pytest

from eval_runner import config
from eval_runner.console.app import create_app
from eval_runner.console.auth_manager import Permission
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.reference.signing import NullSigningBackend


@pytest.fixture
def hardened_app(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    reports_dir = tmp_path / "reports"
    trust_root = tmp_path / ".aes" / "keys"
    for d in (runs_dir, reports_dir, trust_root):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr(config, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "TRUST_ROOT", trust_root)

    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def auth_client(hardened_app):
    with hardened_app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {
                "id": "auditor",
                "name": "Auditor",
                "role": "admin",
                "permissions": Permission.ADMIN(),
            }
        yield c


def test_certify_rejects_path_traversal(auth_client):
    """Test that POST /api/v1/certify and GET /api/v1/verify reject path traversal strings."""
    res = auth_client.post(
        "/api/v1/certify",
        json={"run_id": "../../../etc/passwd"},
    )
    assert res.status_code == 400
    assert "Valid run_id is required" in res.get_json()["error"]

    res_verify = auth_client.get("/api/v1/verify/..%2F..%2Fetc%2Fpasswd")
    assert res_verify.status_code in (400, 403, 404)


def test_certify_requires_dedicated_certificate_authority(hardened_app, monkeypatch):
    """Issuing a certificate is distinct from mutating an execution run."""
    monkeypatch.delenv("AGENTV_TEST_AUTH_BYPASS", raising=False)
    with hardened_app.test_client() as client:
        principal = {
            "id": "compliance-auditor",
            "org_id": "org-test",
            "tenant_id": "org-test",
            "workspace_id": "workspace-test",
            "active_environment": "test",
        }

        with client.session_transaction() as session:
            session["user"] = {**principal, "permissions": [Permission.CERTIFY_WRITE]}
        assert client.post("/api/v1/certify", json={}).status_code == 400

        with client.session_transaction() as session:
            session["user"] = {**principal, "permissions": [Permission.RUNS_WRITE]}
        response = client.post("/api/v1/certify", json={})
        assert response.status_code == 403
        assert "certify:write" in response.get_json()["error"]


def test_execute_industrial_certification_rejects_provisional_run(auth_client, tmp_path):
    """Test that a run with provisional=True or execution_mode=unknown is refused certification."""
    from eval_runner.console.routes.trust import execute_industrial_certification
    from eval_runner.reference.local_run_store import LocalFileRunStore

    runs_dir = tmp_path / "runs"
    run_id = "run-provisional-101"
    run_store = LocalFileRunStore(runs_dir)
    run_store.create_run(run_id, "provisional-scenario")

    now = datetime.now(UTC)
    events = [
        {
            "event": "run_start",
            "timestamp": now.isoformat(),
            "data": {"execution_mode": "unknown"},
        },
        {
            "event": "run_end",
            "timestamp": (now + timedelta(seconds=2)).isoformat(),
            "data": {"status": "EXECUTION_COMPLETED", "passed": True},
        },
    ]
    run_store.append_events(run_id, events)

    with pytest.raises(ValueError, match=r"(is provisional|requires live evidence)"):
        execute_industrial_certification(run_id=run_id, run_store=run_store)


def test_save_scenario_lifecycle_bypass_closed(auth_client, tmp_path):
    """
    Test that POST /api/scenarios creates scenario with Draft
    and does not mutate lifecycle status on update.
    """
    scen_id = "test_sec_scen_1"
    payload = {
        "metadata": {
            "id": scen_id,
            "status": "Ready",  # Attempting to bypass Draft
            "title": "Security Scenario",
            "version": "1.0.0",
        },
        "description": "Test lifecycle status preservation",
        "nodes": [{"id": "start", "task_description": "Initialize security context"}],
    }

    # First save: create -> MUST be Draft
    res = auth_client.post("/api/scenarios", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["lifecycle_status"] == "Draft"

    # Transition to Validated via transition route
    res_trans = auth_client.post(
        f"/api/scenarios/{scen_id}/transition",
        json={"target_status": "Validated", "reason": "Passed structure check"},
    )
    assert res_trans.status_code == 200
    assert res_trans.get_json()["lifecycle_status"] == "Validated"

    # Subsequent save without transition -> MUST preserve Validated status, not overwrite to Ready
    payload["metadata"]["status"] = "Ready"
    res_save2 = auth_client.post("/api/scenarios", json=payload)
    assert res_save2.status_code == 200
    assert res_save2.get_json()["lifecycle_status"] == "Validated"


def test_preflight_truthful_probe_failing_closed_on_http_error(auth_client, monkeypatch):
    """
    Test that HTTP 500 error from agent endpoint marks preflight
    as WARNING / CONFIGURED, not HEALTHY/PASSED.
    """
    import urllib.error

    def mock_probe(req, timeout=3):
        raise urllib.error.HTTPError(
            url=req.full_url,
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=None,
        )

    monkeypatch.setenv("AGENTV_AGENT_PROBE_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setattr("eval_runner.console.routes.scenarios._open_readiness_probe", mock_probe)

    payload = {
        "scenario_id": "test_preflight",
        "agent_config": {"endpoint": "http://127.0.0.1:9099", "protocol": "http_rest"},
        "scenario_data": {
            "metadata": {"id": "test_preflight", "version": "1.0.0"},
            "nodes": [{"id": "init", "task_description": "Initialize"}],
        },
    }

    res = auth_client.post("/api/scenarios/readiness", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["readiness_tier"] == "CONFIGURED"
    agent_check = next(c for c in data["checks"] if c["name"] == "Agent Endpoint")
    assert agent_check["status"] in ("WARNING", "FAILED")
    assert agent_check["tier"] == "CONFIGURED"
    assert "HTTP 500" in agent_check["message"]


def test_provider_certificate_manifest_canonical_parity(tmp_path, monkeypatch):
    """Certificate discovery is a run-provider operation, not a path scan."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)

    run_id = "run-parity-cert-99"
    store = LocalFileRunStore(runs_dir)
    store.create_run(run_id, "scenario")
    assert store.get_manifest(run_id) is None
    store.save_run_manifest(run_id, {"vc_version": "3.0.0", "run_id": run_id})
    assert store.get_manifest(run_id) == {"vc_version": "3.0.0", "run_id": run_id}


def test_flight_recorder_fail_closed_under_aes_certification_mode(tmp_path, monkeypatch):
    """
    Test that FlightRecorderPlugin.finalize_run fails closed when AES_CERTIFICATION_MODE=1
    without non-null signer.
    """
    monkeypatch.setenv("AES_CERTIFICATION_MODE", "1")
    monkeypatch.setattr(
        "eval_runner.identity.get_default_signer",
        lambda: NullSigningBackend(),
    )

    recorder = FlightRecorderPlugin(
        log_dir=tmp_path / "logs",
        signing_backend=NullSigningBackend(),
    )

    run_id = "run-flight-strict-01"
    run_vault = tmp_path / "logs" / run_id
    run_vault.mkdir(parents=True, exist_ok=True)
    (run_vault / "run.jsonl").write_text('{"event":"test"}\n', encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="AES_CERTIFICATION_MODE=1 requires a non-null cryptographic signer",
    ):
        recorder.finalize_run(run_id=run_id)
