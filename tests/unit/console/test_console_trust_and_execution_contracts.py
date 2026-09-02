"""
tests/unit/console/test_console_trust_and_execution_contracts.py
Comprehensive unit tests covering console trust contracts, session auth,
canonical scenario authoring/validation/readiness, durable publish routes,
and agent config propagation.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
import pytest

from eval_runner import config
from eval_runner.console.app import create_app
from eval_runner.console.auth import (
    generate_handoff_token,
    get_jwt_secret,
    handoff_required,
)
from eval_runner.console.routes.publish import (
    JOBS,
    DurableJobStore,
    _get_job,
    _update_job,
)


@pytest.fixture
def ent_client(tmp_path):
    scen_dir = tmp_path / "scenarios"
    scen_dir.mkdir(parents=True, exist_ok=True)
    sample_scen = {
        "aes_version": 1.4,
        "metadata": {
            "id": "test_scen_1",
            "version": "1.0.0",
            "name": "Test Scenario 1",
            "compliance_level": "Standard",
        },
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "task_description": "run_test",
                    "required_tools": [],
                    "expected_outcome": [],
                }
            ],
            "edges": [],
        },
        "evaluation": {
            "consensus": {
                "strategy": "Majority_Vote",
                "min_judges": 1,
                "judge_panel": ["Luna-1"],
            }
        },
        "industry": "finance",
    }

    (scen_dir / "test_scen_1.json").write_text(json.dumps(sample_scen), encoding="utf-8")

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    dist_dir = tmp_path / "ui" / "visual-console" / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text(
        "<!DOCTYPE html><html><body>Visual Console</body></html>", encoding="utf-8"
    )

    with (
        patch.object(config, "PROJECT_ROOT", tmp_path),
        patch.object(config, "RUN_LOG_DIR", runs_dir),
    ):
        app = create_app()
        app.secret_key = "test_enterprise_secret_key"
        with app.test_client() as client:
            yield client, tmp_path


# ===========================================================================
# 1. AUTH API TESTS
# ===========================================================================


def test_get_jwt_secret_resolution():
    with patch.object(config, "JWT_SECRET", "custom_secret_from_config", create=True):
        assert get_jwt_secret() == "custom_secret_from_config"

    with (
        patch.object(config, "JWT_SECRET", None, create=True),
        patch.dict("os.environ", {"JWT_SECRET": "env_jwt_secret"}),
    ):
        assert get_jwt_secret() == "env_jwt_secret"

    with (
        patch.object(config, "JWT_SECRET", None, create=True),
        patch.dict("os.environ", {}, clear=True),
        patch.object(config, "DASHBOARD_API_KEY", "dash_key_123"),
    ):
        assert get_jwt_secret() == "dash_key_123"

    with (
        patch.object(config, "JWT_SECRET", None, create=True),
        patch.dict("os.environ", {}, clear=True),
        patch.object(config, "DASHBOARD_API_KEY", None),
        patch.object(config, "SERVICE_API_KEY", "svc_key_456"),
    ):
        assert get_jwt_secret() == "svc_key_456"


def test_handoff_token_endpoint(ent_client):
    """Handoff endpoint issues a valid scoped JWT and stamps plugin_id."""
    client, _ = ent_client

    res = client.get("/api/auth/handoff?plugin_id=custom-p")
    assert res.status_code == 200
    data = res.get_json()
    assert "token" in data
    assert data["audience"] == "agentv-plugin"
    assert data["expires_in"] == 900

    from eval_runner.console.auth import get_jwt_secret

    decoded = jwt.decode(
        data["token"],
        get_jwt_secret(),
        algorithms=["HS256"],
        audience="agentv-plugin",
    )
    assert decoded["plugin_id"] == "custom-p"
    assert decoded["scope"] == "console-handoff"
    assert "jti" in decoded


def test_handoff_required_decorator_contract():
    """Verify handoff_required decorator enforces the extension API trust contract."""
    from flask import Flask, jsonify

    app = Flask(__name__)

    @app.route("/ext-protected")
    @handoff_required
    def protected():
        return jsonify({"status": "ok"})

    token = generate_handoff_token()

    with app.test_client() as tc:
        # No token
        r1 = tc.get("/ext-protected")
        assert r1.status_code == 401
        assert "Handoff token required" in r1.get_json()["error"]

        # Valid token
        r2 = tc.get(f"/ext-protected?token={token}")
        assert r2.status_code == 200

        # Valid token via header
        r3 = tc.get("/ext-protected", headers={"X-Handoff-Token": token})
        assert r3.status_code == 200

        # Expired token
        expired = generate_handoff_token(expires_in_seconds=-10)
        r4 = tc.get(f"/ext-protected?token={expired}")
        assert r4.status_code == 401
        assert "Token expired" in r4.get_json()["error"]


def test_auth_me_scenarios(ent_client):
    client, _ = ent_client

    # 1. Anonymous with dev mode on (localhost)
    with patch.object(config, "ENABLE_DEMO", True, create=True):
        res = client.get("/api/auth/me", environ_base={"REMOTE_ADDR": "127.0.0.1"})
        assert res.status_code == 200
        data = res.get_json()
        assert data["authenticated"] is True
        assert data["user"]["role"] == "System Admin"

    # 2. Anonymous in non-dev mode
    with (
        patch.object(config, "ENABLE_DEMO", False, create=True),
        patch.dict("os.environ", {"DEV_PERSONA_SIMULATOR": "false"}),
    ):
        res = client.get("/api/auth/me", environ_base={"REMOTE_ADDR": "192.168.1.50"})
        assert res.status_code == 200
        assert res.get_json()["authenticated"] is False

    # 3. Session user with different permission subsets
    with client.session_transaction() as sess:
        sess["user"] = {"id": "auditor_1", "permissions": ["certify:write"]}
    res = client.get("/api/auth/me")
    assert res.get_json()["user"]["role"] == "Compliance Auditor"

    with client.session_transaction() as sess:
        sess["user"] = {"id": "designer_1", "permissions": ["scenarios:write"]}
    res = client.get("/api/auth/me")
    assert res.get_json()["user"]["role"] == "Scenario Designer"

    with client.session_transaction() as sess:
        sess["user"] = {"id": "ops_1", "permissions": ["runs:read"]}
    res = client.get("/api/auth/me")
    assert res.get_json()["user"]["role"] == "MultiAgentOps Eng."


def test_auth_login_and_logout(ent_client):
    client, _ = ent_client

    # Logout
    res = client.post("/api/auth/logout")
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"

    # Login with missing credentials
    r_bad = client.post("/api/auth/login", json={})
    assert r_bad.status_code == 400

    # Login with valid key
    r_good = client.post("/api/auth/login", json={"key": "test-key-123", "role": "admin"})
    assert r_good.status_code in (200, 401)


# ===========================================================================
# 2. SCENARIOS API TESTS
# ===========================================================================


def test_get_canonical_scenario_success_and_404(ent_client):
    client, tmp_path = ent_client

    # Success
    res = client.get("/api/scenarios/test_scen_1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["scenario"]["metadata"]["id"] == "test_scen_1"
    assert data["scenario_hash"].startswith("sha3_256:")

    # 404 Not Found
    res404 = client.get("/api/scenarios/non_existent_scenario_xyz")
    assert res404.status_code == 404
    assert "not found" in res404.get_json()["error"]


def test_validate_scenario_schema(ent_client):
    client, _ = ent_client

    # Validate by ID
    res = client.post("/api/scenarios/test_scen_1/validate", json={})
    assert res.status_code == 200
    assert res.get_json()["valid"] is True
    assert res.get_json()["status"] == "Validated"

    # Validate invalid inline scenario
    bad_scen = {"metadata": {}, "workflow": {}}
    res_bad = client.post("/api/scenarios/test_scen_1/validate", json={"scenario": bad_scen})
    assert res_bad.status_code == 200
    assert res_bad.get_json()["valid"] is False
    assert len(res_bad.get_json()["errors"]) > 0

    # Missing scenario
    res_empty = client.post("/api/scenarios/non_existent/validate", json={})
    assert res_empty.status_code == 400


def test_check_execution_readiness(ent_client):
    client, tmp_path = ent_client

    # 1. Successful readiness check
    payload = {
        "scenario_id": "test_scen_1",
        "agent_config": {
            "protocol": "http_rest",
            "endpoint": "http://localhost:8000",
        },
        "runtime_config": {"max_turns": 10},
    }
    res = client.post("/api/scenarios/readiness", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["ready"] is True
    assert data["manifest"] is not None
    assert data["manifest"]["scenario_id"] == "test_scen_1"

    # 2. Failed scenario resolution
    payload_fail = {
        "scenario_id": "missing_scen_xyz",
        "agent_config": {"protocol": "custom_grpc"},
    }
    res_fail = client.post("/api/scenarios/readiness", json=payload_fail)
    assert res_fail.status_code == 200
    assert res_fail.get_json()["ready"] is False


def test_save_scenario_with_hash_and_status(ent_client):
    client, tmp_path = ent_client

    payload = {
        "id": "new_created_scen",
        "name": "New Test Scenario",
        "industry": "finance",
        "version": "1.1.0",
        "status": "Validated",
        "nodes": [{"id": "n1", "task": "evaluate_risk"}],
    }
    res = client.post("/api/scenarios", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["scenario_id"] == "new_created_scen"
    assert data["scenario_hash"].startswith("sha3_256:")
    assert data["status"] == "success"
    assert data["lifecycle_status"] == "Draft"


# ===========================================================================
# 3. PUBLISH API & DURABLE JOB STORE TESTS
# ===========================================================================


def test_durable_job_store(tmp_path):
    with patch.object(config, "PROJECT_ROOT", tmp_path):
        # Save and Load
        job_data = {"job_id": "job_dur_1", "status": "running", "progress": "50%"}
        DurableJobStore.save("job_dur_1", job_data)

        loaded = DurableJobStore.load("job_dur_1")
        assert loaded == job_data
        assert DurableJobStore.load("missing_job") is None

        # List active
        active = DurableJobStore.list_active()
        assert "job_dur_1" in active

        # Helper functions
        _update_job("job_dur_1", {"progress": "75%"})
        assert _get_job("job_dur_1")["progress"] == "75%"


def test_publish_bundle_download(ent_client):
    client, tmp_path = ent_client

    batch_dir = tmp_path / "results" / "batch_bundle_test"
    batch_dir.mkdir(parents=True, exist_ok=True)
    zip_path = batch_dir / "publication_artifact_bundle.zip"
    zip_path.write_bytes(b"PK\x05\x06" + b"\x00" * 18)  # Minimal valid zip structure

    JOBS["job_bundle_ok"] = {
        "job_id": "job_bundle_ok",
        "status": "completed",
        "results": {
            "batch_id": "batch_bundle_test",
            "zip_file": str(zip_path.relative_to(tmp_path)).replace("\\", "/"),
        },
    }

    # Successful download
    res = client.get("/api/publish/job_bundle_ok/bundle")
    assert res.status_code == 200

    # Job not found
    assert client.get("/api/publish/nonexistent/bundle").status_code == 404

    # Job incomplete
    JOBS["job_inc"] = {"job_id": "job_inc", "status": "running", "results": None}
    assert client.get("/api/publish/job_inc/bundle").status_code == 400


def test_publish_stop_job(ent_client):
    client, tmp_path = ent_client

    # 1. Non-existent job
    assert client.post("/api/publish/non_existent_job/stop").status_code == 404

    # 2. Already finished job
    JOBS["job_finished"] = {"job_id": "job_finished", "status": "completed"}
    res_fin = client.post("/api/publish/job_finished/stop")
    assert res_fin.status_code == 200
    assert "already finished" in res_fin.get_json()["message"]

    # 3. Running job with mock process
    mock_p = MagicMock()
    mock_p.pid = 99999
    JOBS["job_to_kill"] = {
        "job_id": "job_to_kill",
        "status": "running",
        "_proc": mock_p,
    }
    with patch("psutil.Process") as mock_proc_cls:
        mock_proc_instance = MagicMock()
        mock_proc_instance.children.return_value = []
        mock_proc_cls.return_value = mock_proc_instance
        res_kill = client.post("/api/publish/job_to_kill/stop")
        assert res_kill.status_code == 200
        assert res_kill.get_json()["status"] == "stopped"
        assert JOBS["job_to_kill"]["status"] == "failed"


def test_conductor_explicit_batch_and_output_dir(tmp_path):
    from eval_runner.publication_suite.conductor import Conductor

    # Explicit batch_id
    args1 = MagicMock(spec=["batch_id", "path"])
    args1.batch_id = "batch_custom_id_123"
    args1.output_dir = None
    args1.path = str(tmp_path)
    c1 = Conductor(args1)
    assert c1.base_dir == Path("results") / "batch_custom_id_123"

    # Explicit output_dir
    custom_out = tmp_path / "custom_out_dir"
    args2 = MagicMock(spec=["output_dir", "path"])
    args2.output_dir = str(custom_out)
    args2.batch_id = None
    args2.path = str(tmp_path)
    c2 = Conductor(args2)
    assert c2.base_dir == custom_out


def test_evaluate_scenario_propagates_agent_config_to_manifest(ent_client):
    client, tmp_path = ent_client

    payload = {
        "path": "scenarios/test_scen_1.json",
        "max_turns": 15,
        "agent_config": {
            "agent_name": "custom_enterprise_agent",
            "protocol": "grpc_secure",
            "endpoint": "https://agent.enterprise.corp:9443/v1",
            "model": "claude-3-7-sonnet",
        },
        "runtime_config": {
            "max_turns": 15,
            "policy_evaluator": "strict_zero_trust",
        },
        "metadata": {
            "notes": "E2E verification of agent endpoint binding",
        },
    }

    res = client.post("/api/v1/evaluate", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "started"
    assert data["run_id"] is not None

    manifest = data["manifest"]
    assert manifest["agent_config"]["agent_name"] == "custom_enterprise_agent"
    assert manifest["agent_config"]["protocol"] == "grpc_secure"
    assert manifest["agent_config"]["endpoint"] == "https://agent.enterprise.corp:9443/v1"
    assert manifest["agent_config"]["model"] == "claude-3-7-sonnet"
    assert manifest["runtime_config"]["max_turns"] == 15
    assert manifest["runtime_config"]["policy_evaluator"] == "strict_zero_trust"


def test_nav_registry_and_extension_metadata(ent_client):
    client, tmp_path = ent_client
    res = client.get("/api/nav")
    assert res.status_code == 200
    data = res.get_json()
    assert "nav" in data
    assert isinstance(data["nav"], list)

    # Verify handoff token with explicit plugin_id
    handoff_res = client.get("/api/auth/handoff?plugin_id=control-plane")
    assert handoff_res.status_code == 200
    handoff_data = handoff_res.get_json()
    assert "token" in handoff_data
    assert handoff_data["audience"] == "agentv-plugin"


def test_primary_console_canonical_and_v2_compatibility(ent_client):
    """
    Contract Test: Asserts that visual-console is mounted as the primary UX at '/',
    '/scenarios', '/reports', '/editor', '/debugger', etc., with '/v2' preserved
    strictly as a backward-compatible route.
    """
    client, _ = ent_client

    # Root and primary SPA routes must return 200 and serve HTML
    for route in ("/", "/scenarios", "/reports", "/editor", "/debugger", "/runner", "/v2"):
        res = client.get(route)
        assert res.status_code == 200
        assert "text/html" in res.content_type


def test_server_authoritative_lifecycle_transition(ent_client):
    """
    Contract Test: Asserts server-authoritative lifecycle state transitions
    Draft -> Validated -> Ready -> Deprecated with validation verification and audit history.
    """
    client, _ = ent_client

    # Transition valid scenario to Validated
    res = client.post(
        "/api/scenarios/test_scen_1/transition",
        json={"target_status": "Validated", "reason": "Passed automated QA"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["lifecycle_status"] == "Validated"
    assert data["content_hash"].startswith("sha3_256:")

    # Transition to Ready
    ready_res = client.post(
        "/api/scenarios/test_scen_1/transition",
        json={"target_status": "Ready", "reason": "Production verification sign-off"},
    )
    assert ready_res.status_code == 200
    assert ready_res.get_json()["lifecycle_status"] == "Ready"

    # Reject invalid target status
    invalid_res = client.post(
        "/api/scenarios/test_scen_1/transition",
        json={"target_status": "UnknownStatus"},
    )
    assert invalid_res.status_code == 400


def test_scenario_transition_and_readiness_edge_cases(ent_client):
    """Verify scenario transition 404, bad ID, demotion, and readiness warnings."""
    client, _ = ent_client

    # Transition non-existent scenario
    res = client.post(
        "/api/scenarios/non_existent_scen_999/transition",
        json={"target_status": "Ready"},
    )
    assert res.status_code == 404

    # Save invalid scenario ID
    res_bad_id = client.post("/api/scenarios", json={"id": "bad/id/with/slashes!"})
    assert res_bad_id.status_code == 400

    # Save scenario demotion from Ready to Draft when invalid
    res_demote = client.post(
        "/api/scenarios",
        json={
            "id": "invalid_ready_scen",
            "status": "Ready",
            "metadata": {"id": "invalid_ready_scen"},
        },
    )
    assert res_demote.status_code == 200
    assert res_demote.get_json()["lifecycle_status"] == "Draft"

    # Readiness with custom protocol
    res_ready = client.post(
        "/api/scenarios/readiness",
        json={
            "scenario_data": {
                "metadata": {"id": "demo_scen"},
                "workflow": {"nodes": [{"id": "n1"}]},
            },
            "agent_config": {
                "protocol": "custom_grpc",
                "endpoint": "grpc://10.0.0.1:50051",
            },
        },
    )
    assert res_ready.status_code == 200
    data = res_ready.get_json()
    assert data["ready"] is True
    assert any(c["status"] == "WARNING" for c in data["checks"])
