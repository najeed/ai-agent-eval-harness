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
