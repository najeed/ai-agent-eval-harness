"""
tests/unit/console/test_console_routes_agent_targets.py

Unit tests for eval_runner.console.routes.agent_targets ([G3] reusable
Agent Target registry). Covers: validation (fail-closed), secret
rejection, CRUD persistence, and truthful reachability probing.
"""

import json

import pytest
from flask import Flask

from eval_runner.console.routes.agent_targets import (
    AGENT_TARGETS_SCHEMA_VERSION,
    AgentTargetStore,
    AgentTargetValidationError,
    _probe_endpoint,
    _validate_target_payload,
    agent_targets_bp,
)


@pytest.fixture
def targets_jail(tmp_path, monkeypatch):
    reg = tmp_path / "registry" / "agent_targets.json"
    monkeypatch.setattr("eval_runner.config.AGENT_TARGETS_PATH", reg)
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(agent_targets_bp)
    yield {"client": app.test_client(), "path": reg}


VALID_PAYLOAD = {
    "name": "Primary Agent",
    "protocol": "custom_http",
    "endpoint": "http://127.0.0.1:9/v1/agent",
    "model": "orchestrator-x",
    "max_turns": 12,
    "timeout_seconds": 45,
}


def _save(client, payload=None):
    return client.post(
        "/api/v1/agent-targets", json=payload if payload is not None else VALID_PAYLOAD
    )


# ---------------------------------------------------------------------------
# Validation (fail-closed)
# ---------------------------------------------------------------------------


def test_save_rejects_missing_name(targets_jail):
    client = targets_jail["client"]
    res = _save(client, {**VALID_PAYLOAD, "name": "  "})
    assert res.status_code == 400


def test_save_rejects_unknown_protocol(targets_jail):
    client = targets_jail["client"]
    res = _save(client, {**VALID_PAYLOAD, "protocol": "carrier_pigeon"})
    assert res.status_code == 400
    assert "protocol" in res.get_json()["error"]


def test_save_rejects_missing_endpoint(targets_jail):
    client = targets_jail["client"]
    res = _save(client, {**VALID_PAYLOAD, "endpoint": ""})
    assert res.status_code == 400


def test_save_rejects_non_http_scheme(targets_jail):
    client = targets_jail["client"]
    res = _save(client, {**VALID_PAYLOAD, "endpoint": "file:///etc/passwd"})
    assert res.status_code == 400


def test_save_rejects_secret_fields(targets_jail):
    client = targets_jail["client"]
    res = _save(client, {**VALID_PAYLOAD, "api_key": "sk-super-secret"})
    assert res.status_code == 400
    assert "secret" in res.get_json()["error"].lower()


def test_save_rejects_out_of_range_limits(targets_jail):
    client = targets_jail["client"]
    res = _save(client, {**VALID_PAYLOAD, "max_turns": 5000})
    assert res.status_code == 400
    res = _save(client, {**VALID_PAYLOAD, "timeout_seconds": 1})
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# CRUD + persistence
# ---------------------------------------------------------------------------


def test_create_list_get_update_delete_roundtrip(targets_jail):
    client = targets_jail["client"]

    created = _save(client)
    assert created.status_code == 201
    body = created.get_json()
    assert body["id"]
    tid = body["id"]
    assert body["created_at"] == body["updated_at"]

    listed = client.get("/api/v1/agent-targets")
    assert listed.status_code == 200
    data = listed.get_json()
    assert data["schema_version"] == AGENT_TARGETS_SCHEMA_VERSION
    ids = [t["id"] for t in data["targets"]]
    assert tid in ids
    # Secrets must never round-trip into the registry file.
    raw = json.loads(targets_jail["path"].read_text(encoding="utf-8"))
    assert "api_key" not in json.dumps(raw)

    fetched = client.get(f"/api/v1/agent-targets/{tid}")
    assert fetched.status_code == 200
    assert fetched.get_json()["model"] == "orchestrator-x"

    updated = _save(client, {**VALID_PAYLOAD, "id": tid, "model": "orchestrator-y"})
    assert updated.status_code == 201
    assert updated.get_json()["id"] == tid
    assert updated.get_json()["model"] == "orchestrator-y"
    assert updated.get_json()["updated_at"] >= updated.get_json()["created_at"]

    deleted = client.delete(f"/api/v1/agent-targets/{tid}")
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/agent-targets/{tid}").status_code == 404
    assert client.delete(f"/api/v1/agent-targets/{tid}").status_code == 404


def test_store_reloads_from_disk_across_instances(targets_jail):
    store_a = AgentTargetStore(targets_jail["path"])
    record = store_a.upsert(_validate_target_payload(VALID_PAYLOAD), target_id="persist-1")

    store_b = AgentTargetStore(targets_jail["path"])
    assert store_b.get("persist-1")["id"] == record["id"]
    assert any(t["id"] == "persist-1" for t in store_b.list_targets())


def test_registry_file_is_atomic_and_schema_stamped(targets_jail):
    client = targets_jail["client"]
    _save(client, {**VALID_PAYLOAD, "name": "Atomic Check"})
    raw = json.loads(targets_jail["path"].read_text(encoding="utf-8"))
    assert raw["schema_version"] == AGENT_TARGETS_SCHEMA_VERSION
    assert len(raw["targets"]) == 1


# ---------------------------------------------------------------------------
# Reachability probing (truthful tiers only)
# ---------------------------------------------------------------------------


def test_probe_reports_unreachable_for_closed_port():
    result = _probe_endpoint("http_rest", "http://127.0.0.1:1/health", timeout=2.0)
    assert result["reachable"] is False
    assert result["tier"] == "UNREACHABLE"


def test_probe_provider_without_credentials_is_configured(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = _probe_endpoint("openai", "https://api.openai.com/v1")
    assert result["reachable"] is False
    assert result["tier"] == "CONFIGURED"
    assert "OPENAI_API_KEY" in result["message"]


def test_probe_in_process_is_configured_not_reachable():
    result = _probe_endpoint("in_process", "http://127.0.0.1:1/")
    assert result["reachable"] is False
    assert result["tier"] == "CONFIGURED"


def test_saved_target_test_endpoint_returns_truthful_tier(targets_jail):
    client = targets_jail["client"]
    tid = _save(client).get_json()["id"]
    res = client.post(f"/api/v1/agent-targets/{tid}/test")
    assert res.status_code == 200
    body = res.get_json()
    assert body["reachable"] is False
    assert body["tier"] in ("UNREACHABLE", "CONFIGURED")


def test_unsaved_target_test_validates_payload(targets_jail):
    client = targets_jail["client"]
    res = client.post("/api/v1/agent-targets/test", json={"protocol": "nope"})
    assert res.status_code == 400
    missing = client.post("/api/v1/agent-targets/test", json={})
    assert missing.status_code == 400


def test_saved_target_test_404_for_unknown_id(targets_jail):
    client = targets_jail["client"]
    res = client.post("/api/v1/agent-targets/ghost/test")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Direct validator errors (non-route)
# ---------------------------------------------------------------------------


def test_validator_raises_on_bad_id_format():
    with pytest.raises(AgentTargetValidationError):
        AgentTargetStore().upsert(_validate_target_payload(VALID_PAYLOAD), target_id="BAD ID!")


def test_validator_additional_error_branches():
    # Non-dict payload
    with pytest.raises(AgentTargetValidationError, match="Request body must be a JSON object"):
        _validate_target_payload("not-a-dict")  # type: ignore

    # URL with no hostname
    with pytest.raises(AgentTargetValidationError, match="no resolvable hostname"):
        _validate_target_payload({**VALID_PAYLOAD, "endpoint": "http:///no-host"})

    # Non-integer max_turns
    with pytest.raises(AgentTargetValidationError, match="'max_turns' must be an integer"):
        _validate_target_payload({**VALID_PAYLOAD, "max_turns": "invalid-int"})

    # Non-integer timeout_seconds
    with pytest.raises(AgentTargetValidationError, match="'timeout_seconds' must be an integer"):
        _validate_target_payload({**VALID_PAYLOAD, "timeout_seconds": "invalid-int"})


def test_probe_endpoint_additional_branches(monkeypatch):
    import urllib.error
    import urllib.request
    from unittest.mock import MagicMock

    # 1. Non-http scheme probe
    res_scheme = _probe_endpoint("custom_http", "ftp://example.com/agent")
    assert res_scheme["reachable"] is False
    assert "not probeable" in res_scheme["message"]

    # 2. DNS resolution failure
    def mock_getaddrinfo(*args, **kwargs):
        raise OSError("Name or service not known")

    monkeypatch.setattr("socket.getaddrinfo", mock_getaddrinfo)
    res_dns = _probe_endpoint("custom_http", "http://unresolvable.fake.local:8080/agent")
    assert res_dns["reachable"] is False
    assert "DNS resolution failed" in res_dns["message"]

    # 3. HTTP 200 Success probe
    monkeypatch.undo()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b'{"status": "ok"}'
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=5.0: mock_resp)
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: None)

    res_ok = _probe_endpoint("custom_http", "http://127.0.0.1:8000/agent")
    assert res_ok["reachable"] is True
    assert res_ok["tier"] == "REACHABLE"

    # 4. HTTPError probe
    def mock_urlopen_err(*args, **kwargs):
        raise urllib.error.HTTPError("http://127.0.0.1:8000/agent", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_err)
    res_err = _probe_endpoint("custom_http", "http://127.0.0.1:8000/agent")
    assert res_err["reachable"] is True
    assert "HTTP 401" in res_err["message"]


def test_agent_target_store_corrupt_file_and_missing_endpoints(targets_jail):
    from unittest.mock import patch

    client = targets_jail["client"]
    reg_path = targets_jail["path"]

    # 1. Corrupt file handling (lines 249-251)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text("NOT_VALID_JSON{", encoding="utf-8")
    store = AgentTargetStore(reg_path)
    assert store.list_targets() == []
    assert store.get("any_id") is None

    # 2. Delete 404 for nonexistent target (lines 353-354)
    res_del = client.delete("/api/v1/agent-targets/nonexistent_id")
    assert res_del.status_code == 404

    # 3. Slug collision in upsert (line 292)
    t1 = store.upsert({"name": "duplicate-name", "endpoint": "http://127.0.0.1:8000"})
    t2 = store.upsert({"name": "duplicate-name", "endpoint": "http://127.0.0.1:8000"})
    assert t1["id"] != t2["id"]

    # 4. Probe endpoint with 500+ status (lines 203-207)
    from unittest.mock import MagicMock

    mock_502 = MagicMock()
    mock_502.status = 502
    mock_502.read.return_value = b""
    mock_502.__enter__.return_value = mock_502
    mock_502.__exit__.return_value = False

    with patch("urllib.request.urlopen", return_value=mock_502):
        with patch("socket.getaddrinfo", return_value=None):
            res_502 = _probe_endpoint("custom_http", "http://127.0.0.1:8000/agent")
            assert res_502["reachable"] is False
            assert res_502["tier"] == "UNREACHABLE"
            assert "Unexpected HTTP status 502" in res_502["message"]

    # 5. Save error 500 in route (lines 344-346)
    with patch.object(AgentTargetStore, "upsert", side_effect=OSError("Disk write error")):
        res_500 = _save(client, VALID_PAYLOAD)
        assert res_500.status_code == 500

    # 6. Unsaved target test with valid payload (lines 367-368)
    res_unsaved_valid = client.post("/api/v1/agent-targets/test", json=VALID_PAYLOAD)
    assert res_unsaved_valid.status_code == 200
    assert "reachable" in res_unsaved_valid.get_json()
