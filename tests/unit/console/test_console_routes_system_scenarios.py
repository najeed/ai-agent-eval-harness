import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.scenarios import scenario_bp

# SUT
from eval_runner.console.routes.system import DebuggerStateStore, system_bp


@pytest.fixture(scope="module")
def console_jail():
    tmp_root = Path(tempfile.gettempdir()) / "aes_console_sys_jail"
    root = tmp_root / "root"
    runs = root / "runs"
    docs = root / "docs-old"

    if tmp_root.exists():
        shutil.rmtree(tmp_root)

    os.makedirs(runs, exist_ok=True)
    os.makedirs(docs / "guides", exist_ok=True)
    yield {"root": root, "runs": runs, "docs": docs}

    if tmp_root.exists():
        shutil.rmtree(tmp_root)


@pytest.fixture
def client(console_jail, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(system_bp, url_prefix="/api")
    app.register_blueprint(scenario_bp, url_prefix="/api")

    monkeypatch.setattr(config, "PROJECT_ROOT", console_jail["root"])
    monkeypatch.setattr(config, "RUN_LOG_DIR", console_jail["runs"])

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


@pytest.fixture(autouse=True)
def clean_state():
    DebuggerStateStore.reset()


def test_debugger_state_flattening():
    DebuggerStateStore.handle_event({"event": "test", "data": {"key": "val"}})
    state = DebuggerStateStore.get_state()
    assert state["timeline"][0]["key"] == "val"


def test_debugger_state_limit():
    for i in range(100):
        DebuggerStateStore.handle_event({"event": f"e{i}"})
    state = DebuggerStateStore.get_state()
    assert len(state["timeline"]) == 50
    assert state["timeline"][-1]["event"] == "e99"


def test_list_docs_categories(client, console_jail):
    docs_dir = console_jail["docs"]
    (docs_dir / "guides" / "how-to.md").write_text("# How to", encoding="utf-8")

    res = client.get("/api/docs")
    docs = res.get_json()["docs"]
    assert any(d["category"] == "Guide" for d in docs)


def test_get_system_info_providers(client):
    with patch("eval_runner.config.GOOGLE_API_KEY", "key"):
        res = client.get("/api/info")
        assert res.get_json()["agent_endpoint"] == "Gemini (Google)"

    with patch("eval_runner.config.GOOGLE_API_KEY", None):
        with patch("eval_runner.config.ANTHROPIC_API_KEY", "key"):
            res = client.get("/api/info")
            assert res.get_json()["agent_endpoint"] == "Claude (Anthropic)"


def test_cleanup_runs(client, console_jail):
    run_dir = console_jail["runs"] / "old_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (console_jail["runs"] / "run.jsonl").write_text("log", encoding="utf-8")

    res = client.post("/api/cleanup-runs")
    assert res.status_code == 200
    assert not run_dir.exists()
    assert not (console_jail["runs"] / "run.jsonl").exists()


def test_save_scenario_validation(client):
    res = client.post("/api/scenarios", json={"id": "bad id"})
    assert res.status_code == 400


def test_evaluate_scenario_absolute_path(client, console_jail):
    scen_path = console_jail["root"] / "my.json"
    scen_path.write_text('{"id": "s1"}', encoding="utf-8")

    with patch("eval_runner.loader.load_scenario", return_value={"id": "s1"}):
        res = client.post("/api/v1/evaluate", json={"path": str(scen_path)})
        assert res.status_code == 200
        assert "run-my" in res.get_json()["run_id"]


def test_mutate_scenario_raw(client):
    with patch("eval_runner.mutator.mutate_scenario", return_value={"mutated": True}):
        res = client.post("/api/v1/mutate", json={"raw_json": {"id": "s1"}, "type": "typo"})
        assert res.status_code == 200
        assert res.get_json()["mutated"]["mutated"] is True


def test_spec_to_eval_markdown(client):
    with patch(
        "eval_runner.spec_parser.parse_markdown_to_scenario", AsyncMock(return_value={"id": "scen"})
    ):
        res = client.post("/api/v1/spec-to-eval", json={"markdown": "# Spec"})
        assert res.status_code == 200
        assert res.get_json()["scenario"]["id"] == "scen"


def test_debugger_state_historical_rehydrate(client, console_jail):
    run_id = "hist_1"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    # Write a multi-event log
    (run_dir / "run.jsonl").write_text(
        '{"event": "world_state_change", "state": {"hp": 50}}\n'
        '{"event": "agent_action", "action": "move"}\n',
        encoding="utf-8",
    )

    res = client.get(f"/api/debugger/state?run_id={run_id}")
    assert res.status_code == 200
    res_data = res.get_json()["data"]
    assert len(res_data["timeline"]) == 2
    assert res_data["summary"]["state"]["hp"] == 50


def test_evaluate_scenario_load_fail(client, console_jail):
    scen_path = console_jail["root"] / "broken.json"
    scen_path.write_text("{}", encoding="utf-8")

    with patch("eval_runner.loader.load_scenario", side_effect=Exception("Corrupt Spec")):
        res = client.post("/api/v1/evaluate", json={"path": str(scen_path)})
        assert res.status_code == 500
        assert "Corrupt Spec" in res.get_json()["error"]


def test_mutate_scenario_exception(client):
    with patch("eval_runner.mutator.mutate_scenario", side_effect=ValueError("Invalid Type")):
        res = client.post("/api/v1/mutate", json={"raw_json": {"id": "s1"}, "type": "ghost"})
        assert res.status_code == 500
        assert "Invalid Type" in res.get_json()["message"]


def test_v_doctor_audit(client):
    res = client.get("/api/v1/doctor")
    assert res.status_code == 200
    assert res.get_json()["status"] == "healthy"
    assert "pid" in res.get_json()


def test_debugger_state_demo_narrative(client, console_jail):
    run_id = "run-loan-demo-123"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text('{"event": "run_start"}\n', encoding="utf-8")

    res = client.get(f"/api/debugger/state?run_id={run_id}")
    assert res.status_code == 200
    assert "Industrial Demo Narrative" in res.get_json()["data"]["summary"]["message"]


def test_debugger_event_mapping_complex(client):
    from eval_runner.events import CoreEvents

    events = [
        {"event": CoreEvents.TURN_START, "data": {"agent_name": "TestBot"}},
        {"event": CoreEvents.TOOL_CALL, "data": {"tool": "search"}},
        {"event": CoreEvents.RUN_END, "data": {"status": "pass", "run_id": "run-loan-x"}},
    ]
    for e in events:
        client.post("/api/debugger/state", json=e)

    res = client.get("/api/debugger/state")
    summary = res.get_json()["data"]["summary"]
    assert summary["current_agent"] == "Agent TestBot"
    assert summary["last_tool"] == "search"
    assert "Industrial Demo Narrative" in summary["message"]
