import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.scenarios import scenario_bp

# SUT
from eval_runner.console.routes.system import DebuggerStateStore, system_bp
from eval_runner.utils import rmtree_resilient


@pytest.fixture(scope="module")
def console_jail(request):
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "master")
    tmp_root = Path(tempfile.gettempdir()) / f"aes_console_sys_jail_{worker_id}"
    root = tmp_root / "root"
    runs = root / "runs"
    docs = root / "docs-v1-deprecated-reference"

    if tmp_root.exists():
        rmtree_resilient(tmp_root)

    os.makedirs(runs, exist_ok=True)
    os.makedirs(docs / "guides", exist_ok=True)
    yield {"root": root, "runs": runs, "docs": docs}

    if tmp_root.exists():
        rmtree_resilient(tmp_root)


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
    """[C2] Doctor status is DERIVED from real dependency probes, never literal."""
    res = client.get("/api/v1/doctor")
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] in {"HEALTHY", "DEGRADED", "UNREACHABLE"}
    assert "pid" in body
    # Truthfulness contract: the verdict is backed by an explicit dependency map.
    assert isinstance(body.get("dependencies"), dict)
    assert set(body["dependencies"]).issuperset({"signing", "run_vault", "scenario_catalog"})


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


def test_mutate_scenario_missing_path(client):
    """Verify 400 when input_path is missing or doesn't exist."""
    res = client.post("/api/v1/mutate", json={"type": "typo"})
    assert res.status_code == 400
    assert "Missing input_path" in res.get_json()["error"]


def test_mutate_scenario_save_output(client, console_jail):
    """Verify that mutation results can be saved to a file."""
    scen_path = console_jail["root"] / "to_mutate.json"
    scen_path.write_text('{"id": "orig"}')
    out_path = console_jail["root"] / "mutated.json"

    with patch("eval_runner.mutator.mutate_scenario", return_value={"id": "mutated"}):
        res = client.post(
            "/api/v1/mutate",
            json={"input_path": str(scen_path), "output_path": str(out_path), "type": "typo"},
        )
        assert res.status_code == 200
        assert out_path.exists()


def test_spec_to_eval_missing_source(client):
    """Verify 400 when both markdown and input_path are missing."""
    res = client.post("/api/v1/spec-to-eval", json={})
    assert res.status_code == 400
    assert "Missing markdown text" in res.get_json()["error"]


def test_spec_to_eval_from_file_and_save(client, console_jail):
    """Verify spec-to-eval using file input and saving the result."""
    md_path = console_jail["root"] / "spec.md"
    md_path.write_text("# Industrial Spec")
    out_path = console_jail["root"] / "scen.json"

    with patch(
        "eval_runner.spec_parser.parse_markdown_to_scenario", AsyncMock(return_value={"id": "md"})
    ):
        res = client.post(
            "/api/v1/spec-to-eval",
            json={"input_path": str(md_path), "output_path": str(out_path)},
        )
        assert res.status_code == 200
        assert out_path.exists()


def test_spec_to_eval_exception(client):
    """Verify 500 when spec parsing fails."""
    with patch(
        "eval_runner.spec_parser.parse_markdown_to_scenario",
        AsyncMock(side_effect=RuntimeError("Parse Fail")),
    ):
        res = client.post("/api/v1/spec-to-eval", json={"markdown": "# Broken"})
        assert res.status_code == 500
        assert "Parse Fail" in res.get_json()["message"]


def test_evaluate_scenario_not_found(client, console_jail):
    """Verify 404 when scenario is missing from catalog and disk."""
    res = client.post("/api/v1/evaluate", json={"path": "ghost.json"})
    assert res.status_code == 404
    assert "Scenario not found" in res.get_json()["error"]


def test_debugger_state_store_run_scoping_and_root_cause():
    """Verify DebuggerStateStore run-scoping and root-cause heuristics."""
    from eval_runner.console.routes.system import DebuggerStateStore

    DebuggerStateStore.reset()
    assert DebuggerStateStore.get_state()["summary"]["message"] == "Waiting for evaluation..."

    DebuggerStateStore.post_event(
        {"event": "run_start", "data": {"scenario": "scen-1"}},
        run_id="run-101",
    )
    state_101 = DebuggerStateStore.get_state(run_id="run-101")
    assert state_101["summary"]["scenario"] == "scen-1"

    DebuggerStateStore.reset(run_id="run-101")
    assert "run-101" not in DebuggerStateStore._run_states

    DebuggerStateStore.post_event(
        {
            "event": "policy_violation",
            "is_root_cause": True,
            "reason": "Jailbreak detected",
            "confidence": 0.98,
        },
        run_id="run-rc",
    )
    rc_state = DebuggerStateStore.get_state(run_id="run-rc")
    assert "root_cause" in rc_state
    assert rc_state["root_cause"]["reason"] == "Jailbreak detected"
    assert rc_state["root_cause"]["confidence"] == 0.98


def test_debugger_state_store_reset_latest_run_ordering():
    """Verify DebuggerStateStore resets latest run ID and promotes next run."""
    from eval_runner.console.routes.system import DebuggerStateStore

    DebuggerStateStore.reset()
    DebuggerStateStore.post_event({"event": "turn_1"}, run_id="run-A")
    DebuggerStateStore.post_event({"event": "turn_2"}, run_id="run-B")
    assert DebuggerStateStore._latest_run_id == "run-B"

    DebuggerStateStore.reset(run_id="run-B")
    assert DebuggerStateStore._latest_run_id == "run-A"


def test_ollama_status_parse_error_handling(client):
    """Verify ollama status handles response parsing errors gracefully."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b"invalid-json-bytes"
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.get("/api/system/ollama-status")
        assert res.status_code == 200
        assert res.get_json()["available"] is True


def test_scenarios_taxonomy_and_refresh_error(client):
    """Verify taxonomy GET and refresh error handling."""
    res = client.get("/api/v1/taxonomy")
    assert res.status_code == 200
    assert "categories" in res.get_json()

    with patch(
        "eval_runner.catalog.ScenarioCatalog.get_instance",
        side_effect=RuntimeError("disk unreadable"),
    ):
        res_refresh = client.post("/api/scenarios/refresh")
        assert res_refresh.status_code == 500


def test_scenarios_mutate_endpoints(client, tmp_path):
    """Verify /v1/mutate endpoint edge cases."""
    # 1. Missing fields
    res = client.post("/api/v1/mutate", json={})
    assert res.status_code == 400

    # 2. Path outside root
    res = client.post("/api/v1/mutate", json={"input_path": "../../etc/passwd"})
    assert res.status_code == 403

    # 3. Path non-existent
    res = client.post("/api/v1/mutate", json={"input_path": str(tmp_path / "non_existent.json")})
    assert res.status_code == 400

    # 4. Mutate with raw JSON success
    res = client.post(
        "/api/v1/mutate",
        json={"raw_json": {"id": "test_mutate", "title": "Test"}, "type": "typo"},
    )
    assert res.status_code == 200
    assert res.get_json()["status"] == "success"


def test_scenarios_spec_to_eval_endpoints(client, tmp_path):
    """Verify /v1/spec-to-eval endpoint edge cases."""
    # 1. Missing fields
    res = client.post("/api/v1/spec-to-eval", json={})
    assert res.status_code == 400

    # 2. Path outside root
    res = client.post("/api/v1/spec-to-eval", json={"input_path": "../../etc/shadow"})
    assert res.status_code == 403

    # 3. Path non-existent
    res = client.post("/api/v1/spec-to-eval", json={"input_path": str(tmp_path / "missing.md")})
    assert res.status_code == 400

    # 4. Success with markdown text
    with patch(
        "eval_runner.spec_parser.parse_markdown_to_scenario",
        return_value={"id": "parsed_scen"},
    ):
        res = client.post("/api/v1/spec-to-eval", json={"markdown": "# Specification"})
        assert res.status_code == 200
        assert res.get_json()["status"] == "success"


def test_scenarios_auto_translate_and_evaluate(client):
    """Verify /v1/auto-translate and /v1/evaluate."""
    # 1. Auto translate missing text
    res = client.post("/api/v1/auto-translate", json={})
    assert res.status_code == 400

    # 2. Auto translate success
    with patch(
        "eval_runner.auto_translate.translate_to_scenario",
        return_value={"id": "translated_scen"},
    ):
        res = client.post("/api/v1/auto-translate", json={"text": "Test agent goal"})
        assert res.status_code == 200
        assert res.get_json()["id"] == "translated_scen"

    # 3. Evaluate missing path
    res = client.post("/api/v1/evaluate", json={})
    assert res.status_code == 400


def test_system_guide_file_and_system_info_branches(client, console_jail, monkeypatch):
    docs_dir = console_jail["docs"]
    (docs_dir / "quickstart.md").write_text("# Quickstart", encoding="utf-8")
    (docs_dir / "api_reference.md").write_text("# API Reference", encoding="utf-8")
    (docs_dir / "tutorial.md").write_text("# Tutorial", encoding="utf-8")

    # Guide file with fallback to .md extension
    res_fallback = client.get("/api/docs/quickstart")
    assert res_fallback.status_code == 200
    assert res_fallback.get_json()["id"] == "quickstart"

    # Guide file unsafe traversal path rejected
    with patch("eval_runner.utils.is_path_safe", return_value=False):
        res_unsafe = client.get("/api/docs/unsafe_file.md")
        assert res_unsafe.status_code == 403

    # List docs with categorization
    res_docs = client.get("/api/docs")
    assert res_docs.status_code == 200
    docs_list = res_docs.get_json()["docs"]
    categories = {d["category"] for d in docs_list}
    assert "Guide" in categories or "API Reference" in categories

    # System info with Ollama URL and OpenAI / Anthropic keys
    monkeypatch.setattr(config, "AGENT_API_URLS", ["http://localhost:11434/v1"])
    monkeypatch.setattr(config, "GOOGLE_API_KEY", "")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "anthropic_key")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    res_anthropic = client.get("/api/info")
    assert res_anthropic.status_code == 200

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "openai_key")
    res_openai = client.get("/api/info")
    assert res_openai.status_code == 200

    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    res_ollama_info = client.get("/api/info")
    assert res_ollama_info.status_code == 200

    # Nav registry
    res_nav = client.get("/api/nav")
    assert res_nav.status_code == 200


def test_runtime_health_and_ollama_status_branches(client, monkeypatch):

    # Runtime health with EVAL_SIGNING_KEY
    monkeypatch.setenv("EVAL_SIGNING_KEY", "dummy_key")
    res_status = client.get("/api/status")
    assert res_status.status_code == 200
    assert res_status.get_json()["signing_backend"] == "persistent"
    assert res_status.get_json()["status"] == "HEALTHY"

    # Runtime health with run vault write failure
    with patch("pathlib.Path.write_text", side_effect=OSError("Read-only filesystem")):
        res_unreachable = client.get("/api/status")
        assert res_unreachable.status_code == 200
        assert res_unreachable.get_json()["status"] == "UNREACHABLE"

    # Runtime health with scenario catalog failure
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("Permission denied")):
        res_cat_fail = client.get("/api/status")
        assert res_cat_fail.status_code == 200
        assert res_cat_fail.get_json()["status"] == "UNREACHABLE"

    # Ollama status endpoint with active response
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({"models": [{"name": "llama3:8b"}]}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    with patch("urllib.request.urlopen", return_value=mock_resp):
        res_ollama = client.get("/api/system/ollama-status")
        assert res_ollama.status_code == 200
        assert res_ollama.get_json()["available"] is True
        assert res_ollama.get_json()["models"] == ["llama3:8b"]

    # Ping diagnostic
    res_ping = client.get("/api/ping")
    assert res_ping.status_code == 200
    assert res_ping.get_json()["status"] == "pong"


def test_debugger_state_historical_and_events(client, console_jail):
    import json
    from types import SimpleNamespace

    from eval_runner.events import CoreEvents

    # Non-dict event object handling
    event_obj = SimpleNamespace(
        name=CoreEvents.TOOL_CALL,
        data={"tool": "search_db"},
        timestamp="2026-08-01T00:00:00Z",
        run_id="run-obj-1",
    )
    DebuggerStateStore.handle_event(event_obj)
    state = DebuggerStateStore.get_state("run-obj-1")
    assert state["summary"]["last_tool"] == "search_db"

    # TURN_START and RUN_END with loan narrative
    DebuggerStateStore.handle_event(
        {
            "event": CoreEvents.TURN_START,
            "data": {"agent_name": "LoanOfficer"},
            "run_id": "run-loan-100",
        }
    )
    DebuggerStateStore.handle_event(
        {
            "event": CoreEvents.RUN_END,
            "data": {"status": "SUCCESS", "run_id": "run-loan-100"},
            "run_id": "run-loan-100",
        }
    )
    loan_state = DebuggerStateStore.get_state("run-loan-100")
    assert "Industrial Demo Narrative" in loan_state["summary"]["message"]

    # Load historical trace from disk
    run_dir = console_jail["runs"] / "run-hist-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text(
        json.dumps({"event": "run_start", "data": {"scenario": "test"}}) + "\n", encoding="utf-8"
    )
    res_hist = client.get("/api/debugger/state?run_id=run-hist-1")
    assert res_hist.status_code == 200

    # Historical trace corrupt file
    run_bad = console_jail["runs"] / "run-bad-1"
    run_bad.mkdir(parents=True, exist_ok=True)
    (run_bad / "run.jsonl").write_text("CORRUPT_JSON{\n", encoding="utf-8")
    res_bad = client.get("/api/debugger/state?run_id=run-bad-1")
    assert res_bad.status_code == 500

    # Historical trace 404
    res_404 = client.get("/api/debugger/state?run_id=run-nonexistent-99")
    assert res_404.status_code == 404


def test_system_cleanup_runs_and_doctor_audit_exception(client, console_jail):
    # Cleanup runs success
    run_trash = console_jail["runs"] / "trash_dir"
    run_trash.mkdir(parents=True, exist_ok=True)
    (console_jail["runs"] / "stale.jsonl").write_text("{}\n", encoding="utf-8")

    res_clean = client.post("/api/cleanup-runs")
    assert res_clean.status_code == 200
    assert res_clean.get_json()["status"] == "success"

    # Cleanup runs error
    with patch("pathlib.Path.iterdir", side_effect=OSError("Disk IO Error")):
        res_clean_err = client.post("/api/cleanup-runs")
        assert res_clean_err.status_code == 500

    # Doctor audit error
    with patch(
        "eval_runner.console.routes.system._runtime_health",
        side_effect=RuntimeError("Doctor Probe Crash"),
    ):
        res_doc_err = client.get("/api/v1/doctor")
        assert res_doc_err.status_code == 500


def test_system_docs_and_cleanup_plugin_coverage(client, console_jail, monkeypatch):
    from eval_runner.console.routes.system import _resolve_legacy_docs_dir

    # Legacy docs-old fallback when deprecated reference dir does not exist
    with patch.object(Path, "exists", return_value=False):
        old_dir = _resolve_legacy_docs_dir()
        assert "docs-old" in str(old_dir)

    # Read doc 404 when file does not exist
    res_404 = client.get("/api/docs/nonexistent_guide_xyz")
    assert res_404.status_code == 404

    # List docs with .github ignore and duplicate stem
    docs_dir = console_jail["docs"]
    gh_dir = docs_dir / ".github"
    gh_dir.mkdir(parents=True, exist_ok=True)
    (gh_dir / "ignore_me.md").write_text("# Ignore", encoding="utf-8")

    sub_dir = docs_dir / "tutorial"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "quickstart.md").write_text("# Duplicate Stem", encoding="utf-8")

    res_docs = client.get("/api/docs")
    assert res_docs.status_code == 200
    docs = res_docs.get_json()["docs"]
    assert not any(".github" in d["path"] for d in docs)

    # Cleanup runs triggering plugin hooks with exceptions
    class MockCleanupPlugin:
        def on_cleanup_runs(self):
            raise RuntimeError("Cleanup hook error")

    from eval_runner.plugins import manager

    monkeypatch.setattr(manager, "plugins", [MockCleanupPlugin()])
    res_clean = client.post("/api/cleanup-runs")
    assert res_clean.status_code == 200


def test_system_security_path_traversal_and_ollama_errors(client):
    # Security intercept for traversal
    res_trav = client.get("/api/v1/../secrets")
    assert res_trav.status_code == 403

    # Ollama status with invalid JSON response
    mock_bad_resp = MagicMock()
    mock_bad_resp.status = 200
    mock_bad_resp.read.return_value = b"INVALID_JSON{"
    mock_bad_resp.__enter__.return_value = mock_bad_resp
    mock_bad_resp.__exit__.return_value = False

    with patch("urllib.request.urlopen", return_value=mock_bad_resp):
        res_ollama_bad = client.get("/api/system/ollama-status")
        assert res_ollama_bad.status_code == 200
        assert res_ollama_bad.get_json()["models"] == []

    # Ollama status with connection error
    with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
        res_ollama_conn = client.get("/api/system/ollama-status")
        assert res_ollama_conn.status_code == 200
        assert res_ollama_conn.get_json()["available"] is False


def test_scenario_readiness_gemini_and_warning_branches(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy_google_key")

    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
        res = client.post(
            "/api/scenarios/readiness",
            json={
                "scenario_data": {"id": "invalid-scen"},
                "agent_config": {
                    "protocol": "gemini",
                    "endpoint": "generativelanguage.googleapis.com",
                },
            },
        )
        assert res.status_code == 200
        checks = res.get_json()["checks"]
        assert any(
            c["name"] == "Scenario Specification" and c["status"] == "FAILED" for c in checks
        )
        assert any(c["name"] == "Agent Endpoint" and c["status"] == "PASSED" for c in checks)


def test_scenario_crud_and_lifecycle_transitions(client, console_jail):
    # List scenarios with query filters
    res_list = client.get("/api/scenarios?q=test&industry=finance&difficulty=easy&limit=10&page=1")
    assert res_list.status_code == 200
    assert "scenarios" in res_list.get_json()

    # Get canonical scenario 404
    res_get_404 = client.get("/api/scenarios/nonexistent_scenario_id")
    assert res_get_404.status_code == 404

    # Create new scenario (with automatic Draft demotion for invalid structure)
    scen_payload = {
        "id": "scenario_lifecycle_1",
        "title": "Lifecycle Scenario",
        "industry": "banking",
        "status": "Ready",  # Will demote to Draft because tasks/nodes are missing
    }
    res_create = client.post("/api/scenarios", json=scen_payload)
    assert res_create.status_code == 200
    created_data = res_create.get_json()
    assert created_data["status"] == "success"

    # Get canonical scenario success
    res_get = client.get("/api/scenarios/scenario_lifecycle_1")
    assert res_get.status_code == 200
    assert res_get.get_json()["scenario"]["id"] == "scenario_lifecycle_1"

    # Validate inline scenario payload
    res_val = client.post("/api/scenarios/validate", json={"scenario": {"id": "test_node_err"}})
    assert res_val.status_code == 200

    # Validate by scenario_id
    res_val_id = client.post("/api/scenarios/scenario_lifecycle_1/validate", json={})
    assert res_val_id.status_code == 200

    # Transition invalid target status (400)
    res_trans_inv = client.post(
        "/api/scenarios/scenario_lifecycle_1/transition",
        json={"target_status": "InvalidStatus"},
    )
    assert res_trans_inv.status_code == 400

    # Transition illegal transition (400)
    res_trans_illegal = client.post(
        "/api/scenarios/scenario_lifecycle_1/transition",
        json={"target_status": "Ready"},
    )
    assert res_trans_illegal.status_code == 400

    # Optimistic concurrency conflict on create (409)
    res_conflict = client.post(
        "/api/scenarios",
        json={**scen_payload, "expected_revision_hash": "stale_hash_value"},
    )
    assert res_conflict.status_code == 409


def test_scenario_mutation_translation_and_spec_parsing_errors(client, tmp_path):
    # Mutate with scenario_id not found (404)
    res_mut_404 = client.post("/api/v1/mutate", json={"scenario_id": "ghost_id_xyz"})
    assert res_mut_404.status_code == 404

    # Mutate with unsafe output_path (403)
    res_mut_unsafe = client.post(
        "/api/v1/mutate",
        json={"raw_json": {"id": "m1"}, "output_path": "../../outside_root.json"},
    )
    assert res_mut_unsafe.status_code == 403

    # Spec to eval with unsafe output_path (403)
    with patch(
        "eval_runner.spec_parser.parse_markdown_to_scenario",
        return_value={"id": "parsed_scen"},
    ):
        res_spec_unsafe = client.post(
            "/api/v1/spec-to-eval",
            json={"markdown": "# Spec", "output_path": "../../outside.json"},
        )
        assert res_spec_unsafe.status_code == 403

    # Auto translate server failure (500)
    with patch(
        "eval_runner.auto_translate.translate_to_scenario",
        side_effect=RuntimeError("LLM Backend Down"),
    ):
        res_trans_500 = client.post("/api/v1/auto-translate", json={"text": "Goal statement"})
        assert res_trans_500.status_code == 500
