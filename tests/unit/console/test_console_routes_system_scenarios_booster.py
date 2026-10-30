import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.system import DebuggerStateStore, system_bp
from eval_runner.utils import rmtree_resilient


@pytest.fixture(scope="module")
def console_jail(request):
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "master")
    tmp_root = Path(tempfile.gettempdir()) / f"aes_console_sys_jail_extra_{worker_id}"
    root = tmp_root / "root"
    runs = root / "runs"
    docs = root / "docs-old"

    if tmp_root.exists():
        rmtree_resilient(tmp_root)

    os.makedirs(runs, exist_ok=True)
    os.makedirs(docs / "guides", exist_ok=True)
    os.makedirs(docs / "api", exist_ok=True)
    os.makedirs(docs / "tutorials", exist_ok=True)
    yield {"root": root, "runs": runs, "docs": docs}

    if tmp_root.exists():
        rmtree_resilient(tmp_root)


@pytest.fixture
def client(console_jail, monkeypatch):
    from eval_runner.console.routes.scenarios import scenario_bp

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


def test_system_route_debugger_state_handle_event_non_dict_fallback():
    """Test DebuggerStateStore.handle_event with non-dict/mock attributes fallback (Lines 55-57)"""

    class MockEvent:
        def __init__(self):
            self.name = "mock_event"
            self.data = {"val": 123}
            self.timestamp = "time_stamp"

    DebuggerStateStore.handle_event(MockEvent())
    state = DebuggerStateStore.get_state()
    # Check fallback fields: 'data' dict is popped and its contents updated to the flat event
    assert state["timeline"][0]["event"] == "mock_event"
    assert state["timeline"][0]["val"] == 123


def test_system_route_debugger_state_handle_event_no_name_has_status():
    """Test DebuggerStateStore.handle_event when name is absent but status exists (Line 61)"""
    # event is a dict but has no 'event', 'name', or 'timestamp'. It has 'status' and some data keys
    e = {"status": "in_progress", "foo": "bar"}
    DebuggerStateStore.handle_event(e)
    state = DebuggerStateStore.get_state()
    assert state["timeline"][0]["event"] == "in_progress"


def test_system_route_debugger_state_get_state_root_cause():
    """Test DebuggerStateStore.get_state when root cause event is present (Lines 88-94)"""
    DebuggerStateStore.handle_event(
        {
            "event": "custom",
            "is_root_cause": True,
            "reason": "Failed health check",
            "confidence": 0.9,
        }
    )
    state = DebuggerStateStore.get_state()
    assert "root_cause" in state
    assert state["root_cause"]["reason"] == "Failed health check"
    assert state["root_cause"]["confidence"] == 0.9


def test_system_route_get_nav(client):
    """Test GET /api/nav (Lines 109-111)"""
    with patch.dict(client.application.config, {"NAV_REGISTRY": ["item1", "item2"]}):
        res = client.get("/api/nav")
        assert res.status_code == 200
        assert res.get_json()["nav"] == ["item1", "item2"]


def test_system_route_list_docs_github_skip_and_categories(client, console_jail):
    """Test github folder skip and categorization mapping in list_docs (Lines 124, 127, 138-146)"""
    docs_dir = console_jail["docs"]
    # github skip
    github_doc = docs_dir / ".github" / "workflows" / "ci.md"
    github_doc.parent.mkdir(parents=True, exist_ok=True)
    github_doc.write_text("ci", encoding="utf-8")

    # API docs
    api_doc = docs_dir / "api" / "ref.md"
    api_doc.write_text("ref", encoding="utf-8")

    # Tutorial docs
    tut_doc = docs_dir / "tutorials" / "learn.md"
    tut_doc.write_text("learn", encoding="utf-8")

    res = client.get("/api/docs")
    assert res.status_code == 200
    docs = res.get_json()["docs"]

    ids = [d["id"] for d in docs]
    assert "ci" not in ids

    cats = {d["id"]: d["category"] for d in docs}
    assert cats.get("ref") == "API Reference"
    assert cats.get("learn") == "Tutorial"


def test_system_route_read_doc_not_found(client):
    """Test read_doc 404 Not Found path (Line 166)"""
    res = client.get("/api/docs/nonexistent_doc_file_path.md")
    assert res.status_code == 404
    assert res.get_json()["error"] == "Not Found"


def test_system_route_security_intercept_traversal_attempts(client):
    """Test security_intercept_blueprint traversal interception (Line 187)"""
    # Pass '..' in REQUEST_URI / path to trigger traverse detection
    res = client.get("/api/nav?path=../../etc")
    # request path traversal intercept handles '..' in URI/path info
    res = client.get("/api/docs/..%2fetc/passwd")
    assert res.status_code == 403
    assert "Security: Unauthorized Path Traversal" in res.get_json()["error"]


def test_system_route_info_agent_providers(client):
    """Test info provider shims and load_index fallback (Lines 210-215, 235-240)"""
    from eval_runner.catalog import ScenarioCatalog

    # Empty scenario catalogs trigger load_index (Line 200)
    catalog = ScenarioCatalog.get_instance()
    catalog.clear_instance()
    catalog = ScenarioCatalog.get_instance()
    # Force scenarios to empty list to trigger index load
    catalog.scenarios = []

    try:
        with (
            patch("eval_runner.config.GOOGLE_API_KEY", None),
            patch("eval_runner.config.ANTHROPIC_API_KEY", None),
            patch("eval_runner.config.OPENAI_API_KEY", "key"),
            patch("eval_runner.config.AGENT_API_URLS", ["http://localhost:11434"]),
            patch("eval_runner.catalog.ScenarioCatalog.load_index") as mock_load_index,
            patch("eval_runner.plugins.manager.plugins", []),
        ):
            res = client.get("/api/info")
            assert res.status_code == 200
            mock_load_index.assert_called_once()
            assert res.get_json()["agent_endpoint"] == "GPT (OpenAI)"

        # Test Ollama specific block specifically (Lines 214-215)
        catalog.scenarios = [{"id": "dummy"}]
        with (
            patch("eval_runner.config.GOOGLE_API_KEY", None),
            patch("eval_runner.config.ANTHROPIC_API_KEY", None),
            patch("eval_runner.config.OPENAI_API_KEY", None),
            patch("eval_runner.config.AGENT_API_URLS", ["http://127.0.0.1:11434"]),
            patch("eval_runner.plugins.manager.plugins", []),
        ):
            res2 = client.get("/api/info")
            assert res2.status_code == 200
            assert res2.get_json()["agent_endpoint"] == "Llama (Ollama)"
    finally:
        catalog.scenarios = []

    # Test relpath ValueError branch (Lines 235-237) and general exception branch (Lines 239-240)
    # Test provider_managed runs_dir in /api/info
    res3 = client.get("/api/info")
    assert res3.status_code == 200
    assert res3.get_json()["runs_dir"] == "provider_managed"


def test_system_route_cleanup_runs_exception(client):
    """Test cleanup_runs error branch"""
    with patch(
        "eval_runner.console.routes.system.get_run_store", side_effect=Exception("Disk locked")
    ):
        res = client.post("/api/cleanup-runs")
        assert res.status_code == 500
        assert "Disk locked" in res.get_json()["message"]


def test_system_route_doctor_audit_exception(client):
    """Test doctor audit error branch (Lines 300-301)"""
    with patch(
        "eval_runner.console.routes.system.get_simulator_registry",
        side_effect=Exception("Doctor audit failed"),
    ):
        res = client.get("/api/v1/doctor")
        assert res.status_code == 500
        assert "Doctor audit failed" in res.get_json()["error"]


def test_system_route_list_docs_duplicate_stem(client, console_jail):
    """Test list_docs handles duplicate stems correctly by skipping them (Line 127)"""
    docs_dir = console_jail["docs"]
    doc1 = docs_dir / "dup.md"
    doc2 = docs_dir / "guides" / "dup.md"
    doc1.write_text("dup1", encoding="utf-8")
    doc2.write_text("dup2", encoding="utf-8")

    res = client.get("/api/docs")
    assert res.status_code == 200
    docs = res.get_json()["docs"]
    stems = [d["id"] for d in docs]
    # 'dup' should only appear once
    assert stems.count("dup") == 1


def test_system_route_read_doc_unsafe_path(client):
    """Test read_doc unsafe path interception (Line 163)"""
    with patch("eval_runner.utils.is_path_safe", return_value=False):
        res = client.get("/api/docs/any_doc_path_here.md")
        assert res.status_code == 403
        assert res.get_json()["error"] == "Unauthorized Access"


# Helper to mock PropertyMock


def test_system_route_debugger_state_parsing_exception(client, console_jail):
    """Test historical trace parsing exception in debugger_state (Lines 332-335)"""
    run_id = "broken_trace_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("invalid json lines here{", encoding="utf-8")

    res = client.get(f"/api/debugger/state?run_id={run_id}")
    assert res.status_code == 500
    assert "Failed to parse trace file" in res.get_json()["error"]


def test_system_route_debugger_state_not_found(client):
    """Test historical trace not found error response (Lines 349-350)"""
    res = client.get("/api/debugger/state?run_id=missing_run_id_for_debugger")
    assert res.status_code == 404
    assert "Provider trace not found" in res.get_json()["error"]


def test_system_route_ping(client):
    """Test GET /api/ping (Line 358)"""
    res = client.get("/api/ping")
    assert res.status_code == 200
    assert res.get_json()["status"] == "pong"


# --- Coverage booster for system.py ---


def test_debugger_state_store_post_event_no_dict_data():
    from eval_runner.console.routes.system import DebuggerStateStore

    DebuggerStateStore.reset()
    # 1. No data key
    DebuggerStateStore.post_event({"event": "test"})
    # 2. data key is not a dict
    DebuggerStateStore.post_event({"event": "test", "data": "string_not_dict"})
    assert len(DebuggerStateStore._events) == 2


def test_system_route_list_docs_dir_missing(client):
    from eval_runner import config

    # Temporarily point PROJECT_ROOT to somewhere where docs-old does not exist
    with patch.object(config, "PROJECT_ROOT", Path("non_existent_folder_xyz")):
        res = client.get("/api/docs")
        assert res.status_code == 200
        assert res.get_json()["docs"] == []


def test_system_route_read_doc_no_extension_fallback(client, console_jail):
    docs_dir = console_jail["docs"]
    doc = docs_dir / "my_guide.md"
    doc.write_text("my guide content", encoding="utf-8")

    # Access filename without .md extension, should fallback to my_guide.md (Lines 167-169)
    res = client.get("/api/docs/my_guide")
    assert res.status_code == 200
    assert res.get_json()["content"] == "my guide content"


def test_system_route_cleanup_runs_files_and_plugins(client):
    class FakeCleanupStore:
        def __init__(self):
            self.deleted = []

        def list_runs(self, limit=10_000, context=None):
            return [{"run_id": "run_dir_1"}, {"run_id": "run_1"}]

        def delete_run(self, run_id, context=None):
            self.deleted.append(run_id)
            return True

    class CrashingCleanupPlugin:
        def on_cleanup_runs(self):
            raise ValueError("Plugin cleanup failed")

    from eval_runner.plugins import manager

    plugin = CrashingCleanupPlugin()
    manager.plugins.append(plugin)
    fake_store = FakeCleanupStore()

    try:
        with patch("eval_runner.console.routes.system.get_run_store", return_value=fake_store):
            res = client.post("/api/cleanup-runs")
            assert res.status_code == 200
            assert res.get_json()["count"] == 2
            assert fake_store.deleted == ["run_dir_1", "run_1"]
    finally:
        manager.plugins.remove(plugin)


def test_system_route_debugger_state_glob_fallback_and_empty_line(client):
    class FakeEventsStore:
        def get_events(self, run_id, offset=0, limit=10_000_000, context=None):
            return [{"event": "run_start", "data": {}}]

    with patch("eval_runner.console.routes.system.get_run_store", return_value=FakeEventsStore()):
        res = client.get("/api/debugger/state?run_id=glob_run_id")
        assert res.status_code == 200
        assert len(res.get_json()["data"]["timeline"]) == 1


# ---------------------------------------------------------------------------
# Missing-branch coverage additions for system.py
# ---------------------------------------------------------------------------


def test_system_route_debugger_loan_narrative(client):
    """Cover line 73->74: run_end event with run_id starting with 'run-loan'."""
    from eval_runner.events import CoreEvents

    res = client.post(
        "/api/debugger/state",
        json={
            "event": CoreEvents.RUN_END,
            "data": {"status": "COMPLETED", "run_id": "run-loan-demo-001"},
        },
    )
    assert res.status_code == 200
    state = client.get("/api/debugger/state").get_json()
    msg = state["data"]["summary"]["message"]
    assert msg == "Evaluation complete. Status: COMPLETED"


def test_system_route_cleanup_runs_dir_absent(client, monkeypatch):
    """Cover line 274->286: cleanup_runs when RUN_LOG_DIR does not exist."""
    from pathlib import Path

    from eval_runner import config

    monkeypatch.setattr(config, "RUN_LOG_DIR", Path("/nonexistent_dir_xyz_aes"))
    res = client.post("/api/cleanup-runs")
    assert res.status_code == 200
    assert res.get_json()["count"] == 0


def test_system_route_cleanup_runs_plugin_without_method(client, console_jail):
    """Cover line 290->288 false branch: plugin with no on_cleanup_runs attribute."""
    from eval_runner.plugins import manager

    class NoCleanupPlugin:
        pass

    plugin = NoCleanupPlugin()
    manager.plugins.append(plugin)
    try:
        res = client.post("/api/cleanup-runs")
        assert res.status_code == 200
    finally:
        manager.plugins.remove(plugin)


def test_system_route_debugger_state_demo_trace_hydration(client, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_DEMO", True)
    monkeypatch.setitem(client.application.config, "DEBUG", True)
    """Cover 336->363 false branch: get_demo_trace returns a trace, skipping file scan."""
    demo_events = [{"event": "run_start", "data": {}}]
    with patch("eval_runner.console.demo_traces.get_demo_trace", return_value=demo_events):
        res = client.get("/api/debugger/state?run_id=run-loan-demo-hydrate")
    assert res.status_code == 200
    body = res.get_json()
    assert "data" in body
    assert "timeline" in body["data"]


def test_system_route_ollama_status_all_paths(client):
    """Cover lines 394-410: all three ollama-status sub-paths."""

    # 1. Valid HTTP endpoint — server responds 200
    class FakeResponse:
        status = 200

        def read(self):
            return b'{"models": [{"name": "llama3:latest"}, {"name": "mistral"}]}'

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    with patch("urllib.request.urlopen", return_value=FakeResponse()):
        res = client.get("/api/system/ollama-status")
    assert res.status_code == 200
    data = res.get_json()
    assert data["available"] is True
    assert data["models"] == ["llama3:latest", "mistral"]

    # 2. urlopen raises (server unreachable)
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        res = client.get("/api/system/ollama-status")
    assert res.status_code == 200
    assert res.get_json()["available"] is False
    assert res.get_json()["models"] == []

    # 3. Endpoint that doesn't start with http/https
    from eval_runner import config

    with patch.object(config, "OLLAMA_BASE_URL", "grpc://localhost:9000", create=True):
        res = client.get("/api/system/ollama-status")
    assert res.status_code == 200
    assert res.get_json()["available"] is False
    assert res.get_json()["models"] == []


def test_system_route_read_doc_fallback_not_found(client, console_jail):
    """Cover 168->171 false branch: no-extension request and .md file doesn't exist."""
    # Request a filename without extension where no .md file exists either
    res = client.get("/api/docs/nonexistent_guide_xyz")
    assert res.status_code == 404


def test_system_route_auto_translate_success(client):
    """Test POST /api/v1/auto-translate succeeds."""
    mock_scenario = {"id": "scenario-1", "title": "Mock Title"}

    async def mock_translate(*args, **kwargs):
        return mock_scenario

    with patch("eval_runner.auto_translate.translate_to_scenario", side_effect=mock_translate):
        res = client.post("/api/v1/auto-translate", json={"text": "raw specs", "model": "m1"})
        assert res.status_code == 200
        assert res.get_json() == mock_scenario


def test_system_route_auto_translate_missing_text(client):
    """Test POST /api/v1/auto-translate fails with 400 when text is missing."""
    res = client.post("/api/v1/auto-translate", json={"model": "m1"})
    assert res.status_code == 400
    assert "Missing required field: text" in res.get_json()["error"]


def test_system_route_auto_translate_failure(client):
    """Test POST /api/v1/auto-translate fails with 500 when translate_to_scenario raises."""

    async def mock_translate_fail(*args, **kwargs):
        raise RuntimeError("Ollama crashed")

    with patch("eval_runner.auto_translate.translate_to_scenario", side_effect=mock_translate_fail):
        res = client.post("/api/v1/auto-translate", json={"text": "raw specs"})
        assert res.status_code == 500
        assert "Ollama crashed" in res.get_json()["error"]


def test_scenarios_evaluate_by_id(client, console_jail):
    """Cover lines 108-109 in scenarios.py evaluate_scenario route."""
    from eval_runner.catalog import ScenarioCatalog

    cat = ScenarioCatalog.get_instance()
    scen_dir = console_jail["root"] / "industries" / "generic" / "scenarios"
    scen_dir.mkdir(parents=True, exist_ok=True)
    scen_file = scen_dir / "scen_evaluate_id.json"
    scen_file.write_text('{"id": "scen_evaluate_id", "title": "Scen Title"}', encoding="utf-8")

    cat.scenarios = [
        {"id": "scen_evaluate_id", "path": "industries/generic/scenarios/scen_evaluate_id.json"}
    ]

    with patch("eval_runner.loader.load_scenario") as mock_load:
        mock_load.return_value = {"id": "scen_evaluate_id"}
        with patch("threading.Thread.start"):  # Don't actually run thread
            res = client.post("/api/v1/evaluate", json={"path": "scen_evaluate_id"})
            assert res.status_code == 200
            assert res.get_json()["status"] == "started"


def test_scenarios_evaluate_async_eval_fails(client, console_jail):
    """Cover evaluate scenario route with mocked backend submission to prevent thread leak."""
    from eval_runner.catalog import ScenarioCatalog
    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

    ScenarioCatalog.get_instance()
    scen_dir = console_jail["root"] / "scenarios"
    scen_dir.mkdir(parents=True, exist_ok=True)
    scen_file = scen_dir / "scen_eval_fail.json"
    scen_file.write_text('{"id": "scen_eval_fail"}', encoding="utf-8")

    backend = InProcessExecutionBackend.get_instance()
    with (
        patch("eval_runner.loader.load_scenario", return_value={"id": "scen_eval_fail"}),
        patch.object(
            backend, "submit", return_value={"status": "started", "run_id": "run-test"}
        ) as mock_submit,
    ):
        res = client.post("/api/v1/evaluate", json={"path": str(scen_file)})
        assert res.status_code == 200
        assert res.get_json()["status"] == "started"
        assert mock_submit.called


def test_scenarios_mutate_by_id_success(client, console_jail):
    """Cover mutate_scenario with scenario_id lookup (lines 182-187)."""
    from eval_runner.catalog import ScenarioCatalog

    cat = ScenarioCatalog.get_instance()
    scen_dir = console_jail["root"] / "scenarios"
    scen_dir.mkdir(parents=True, exist_ok=True)
    scen_file = scen_dir / "scen_mutate_id.json"
    scen_file.write_text('{"id": "scen_mutate_id", "title": "Original"}', encoding="utf-8")

    cat.scenarios = [{"id": "scen_mutate_id", "path": "scenarios/scen_mutate_id.json"}]

    with patch(
        "eval_runner.mutator.mutate_scenario",
        return_value={"id": "scen_mutate_id", "title": "Mutated"},
    ):
        res = client.post("/api/v1/mutate", json={"scenario_id": "scen_mutate_id", "type": "typo"})
        assert res.status_code == 200
        assert res.get_json()["mutated"]["title"] == "Mutated"


def test_scenarios_mutate_by_id_not_found(client):
    """Cover mutate_scenario scenario_id 404."""
    res = client.post("/api/v1/mutate", json={"scenario_id": "nonexistent_mutate_id"})
    assert res.status_code == 404
    assert "not found" in res.get_json()["error"]


def test_debugger_state_store_run_end_variations():
    from eval_runner.console.routes.system import DebuggerStateStore
    from eval_runner.events import CoreEvents

    DebuggerStateStore.reset()
    # Loan demo run ID
    DebuggerStateStore.handle_event(
        {"event": CoreEvents.RUN_END, "data": {"status": "SUCCESS"}},
        run_id="run-loan-narrative",
    )
    state = DebuggerStateStore.get_state("run-loan-narrative")
    assert state["summary"]["message"] == "Evaluation complete. Status: SUCCESS"

    # Normal run ID without loan prefix
    DebuggerStateStore.handle_event(
        {"event": CoreEvents.RUN_END, "data": {"status": "FAILED"}},
        run_id="run-standard-exec",
    )
    norm_state = DebuggerStateStore.get_state("run-standard-exec")
    assert "Industrial Demo Narrative" not in norm_state["summary"]["message"]

    # Run without run_id in data or call
    DebuggerStateStore.handle_event(
        {"event": CoreEvents.RUN_END, "data": {"status": "SUCCESS"}},
        run_id=None,
    )


def test_canonicalize_nav_registry_exhaustive_branches():
    from eval_runner.console.routes.system import canonicalize_nav_registry

    # Non-list input returns input directly
    assert canonicalize_nav_registry(None) is None
    assert canonicalize_nav_registry("invalid") == "invalid"

    # Non-dict items in inventory view vs normal view
    non_dict_items = ["string_nav_entry", 123]
    assert canonicalize_nav_registry(non_dict_items, inventory_view=True) == []
    assert canonicalize_nav_registry(non_dict_items, inventory_view=False) == non_dict_items

    # Non-extension items in inventory view vs core view
    core_items = [{"title": "Dashboard", "path": "/dashboard"}]
    assert canonicalize_nav_registry(core_items, inventory_view=True) == []
    res_core = canonicalize_nav_registry(core_items, inventory_view=False)
    assert len(res_core) == 1
    assert res_core[0]["title"] == "Dashboard"

    # Multiple remote versions for capability
    multi_version = [
        {
            "capabilityId": "cap-multi",
            "extensionId": "ext-1",
            "remoteEntry": "url-v1",
            "version": "1.0.0",
        },
        {
            "capabilityId": "cap-multi",
            "extensionId": "ext-1",
            "remoteEntry": "url-v2",
            "version": "2.0.0",
        },
    ]
    res_multi = canonicalize_nav_registry(multi_version, inventory_view=True)
    assert len(res_multi) == 2

    # Related registration IDs and de-duplication
    related_ids_items = [
        {
            "capabilityId": "cap-rel",
            "extensionId": "ext-rel",
            "remoteEntry": "url-rel",
            "id": "reg-1",
            "relatedRegistrationIds": ["reg-2", "reg-3", "reg-1"],
        }
    ]
    res_rel = canonicalize_nav_registry(related_ids_items, inventory_view=True)
    assert "reg-1" in res_rel[0]["relatedRegistrationIds"]
    assert "reg-2" in res_rel[0]["relatedRegistrationIds"]

    # Items without IDs or relatedRegistrationIds
    no_ids_items = [
        {"capabilityId": "cap-no-id", "extensionId": "ext-no-id", "remoteEntry": "url-no-id"}
    ]
    res_no_id = canonicalize_nav_registry(no_ids_items, inventory_view=True)
    assert "relatedRegistrationIds" not in res_no_id[0]

    # Item with neither title nor name
    no_title_name = [
        {
            "capabilityId": "cap-fallback",
            "extensionId": "ext-fallback",
            "remoteEntry": "url-fallback",
        }
    ]
    res_fallback = canonicalize_nav_registry(no_title_name, inventory_view=True)
    assert res_fallback[0]["title"] == "cap-fallback"

    # Item with both title and name
    both_title_name = [
        {
            "capabilityId": "cap-both",
            "extensionId": "ext-both",
            "remoteEntry": "url-both",
            "title": "Existing Title",
            "name": "Existing Name",
        }
    ]
    res_both = canonicalize_nav_registry(both_title_name, inventory_view=True)
    assert res_both[0]["title"] == "Existing Title"
    assert res_both[0]["name"] == "Existing Name"


def test_system_route_read_doc_direct_match(client, console_jail):
    docs_dir = console_jail["docs"]
    raw_doc = docs_dir / "RAW_FILE"
    raw_doc.write_text("direct content", encoding="utf-8")
    res = client.get("/api/docs/RAW_FILE")
    assert res.status_code == 200
    assert res.get_json()["content"] == "direct content"


def test_system_cleanup_runs_error_handling(client):
    class FailingListStore:
        def list_runs(self, limit=10_000, context=None):
            raise RuntimeError("Database connection lost")

    with patch("eval_runner.console.routes.system.get_run_store", return_value=FailingListStore()):
        res = client.post("/api/cleanup-runs")
        assert res.status_code == 500
        assert "Database connection lost" in res.get_json()["message"]


def test_runtime_health_exhaustive_states(client):
    from types import SimpleNamespace

    from eval_runner.console.routes.system import _runtime_health

    app = client.application

    # Outside application context (handles RuntimeError at current_app)
    outside_ctx_health = _runtime_health()
    assert outside_ctx_health["status"] in ("HEALTHY", "DEGRADED", "UNREACHABLE")

    with app.app_context():
        # Signing state FAILED without error message
        mock_failed_signing = SimpleNamespace(
            is_verifiable=False,
            signer_type="FAILED",
            error_message=None,
        )
        with patch(
            "eval_runner.signing_readiness.check_signing_readiness",
            return_value=mock_failed_signing,
        ):
            health_failed = _runtime_health()
            assert health_failed["status"] == "UNREACHABLE"
            assert health_failed["dependencies"]["signing"] == "FAILED"

        # Signing state DEGRADED with error message
        mock_degraded_signing = SimpleNamespace(
            is_verifiable=False,
            signer_type="EPHEMERAL",
            error_message="Ephemeral signing key active",
        )
        with patch(
            "eval_runner.signing_readiness.check_signing_readiness",
            return_value=mock_degraded_signing,
        ):
            health_degraded = _runtime_health()
            assert health_degraded["status"] == "DEGRADED"
            assert health_degraded["dependencies"]["signing"] == "DEGRADED"
            assert any("Ephemeral signing key active" in d for d in health_degraded["details"])

        # Signing state DEGRADED without error message
        mock_deg_no_err = SimpleNamespace(
            is_verifiable=False,
            signer_type="EPHEMERAL",
            error_message=None,
        )
        with patch(
            "eval_runner.signing_readiness.check_signing_readiness", return_value=mock_deg_no_err
        ):
            health_deg_no_err = _runtime_health()
            assert health_deg_no_err["status"] == "DEGRADED"
            assert health_deg_no_err["dependencies"]["signing"] == "DEGRADED"

        # Plugin registration errors present in app config
        app.config["PLUGIN_REGISTRATION_ERRORS"] = [
            {"plugin": "faulty_extension", "error": "Import crashed"}
        ]
        try:
            health_plugins = _runtime_health()
            assert health_plugins["dependencies"]["plugins"] == "FAILED"
            assert any("faulty_extension" in d for d in health_plugins["details"])
        finally:
            app.config.pop("PLUGIN_REGISTRATION_ERRORS", None)


def test_system_debugger_state_auth_headers_and_path_safety(client, console_jail, monkeypatch):
    from unittest.mock import MagicMock

    # Auth bypass disabled to exercise header checks
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "0")

    # Client without session user
    with client.session_transaction() as sess:
        sess.pop("user", None)

    # Missing credentials returns 401
    res_unauth = client.get("/api/debugger/state")
    assert res_unauth.status_code == 401

    # Bearer token auth in Authorization header
    with patch("eval_runner.console.auth_manager.get_auth_provider") as mock_get_provider:
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider
        mock_provider.verify_token.return_value = {"id": "token-user", "permissions": ["*"]}
        mock_provider.has_permission.return_value = True

        res_bearer = client.get(
            "/api/debugger/state",
            headers={"Authorization": "Bearer valid-auth-token"},
        )
        assert res_bearer.status_code == 200
        mock_provider.verify_token.assert_called_with("valid-auth-token")

        # API Key in X-AES-API-KEY header
        mock_provider.authenticate.return_value = {"id": "key-user", "permissions": ["*"]}
        res_key = client.get(
            "/api/debugger/state",
            headers={"X-AES-API-KEY": "valid-aes-key"},
        )
        assert res_key.status_code == 200
        mock_provider.authenticate.assert_called_with("valid-aes-key")

    # Path traversal detection in trace loading
    with client.session_transaction() as sess:
        sess["user"] = {"id": "test-admin", "name": "Admin", "permissions": ["*"]}

    run_id = "traversal_run_test"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("{}\n", encoding="utf-8")

    with patch("eval_runner.utils.is_path_safe", return_value=False):
        res_traversal = client.get(f"/api/debugger/state?run_id={run_id}")
        assert res_traversal.status_code == 400
        assert "Path traversal detected" in res_traversal.get_json()["error"]


def test_system_ollama_status_error_and_status_branches(client):
    from unittest.mock import MagicMock

    # Ollama status non-200 response
    mock_resp_500 = MagicMock()
    mock_resp_500.status = 500
    mock_resp_500.__enter__.return_value = mock_resp_500
    with patch("urllib.request.urlopen", return_value=mock_resp_500):
        res_500 = client.get("/api/system/ollama-status")
        assert res_500.status_code == 200
        assert res_500.get_json()["available"] is False

    # Ollama status 200 with JSON decode exception
    mock_resp_bad_json = MagicMock()
    mock_resp_bad_json.status = 200
    mock_resp_bad_json.read.return_value = b"invalid json content"
    mock_resp_bad_json.__enter__.return_value = mock_resp_bad_json
    with patch("urllib.request.urlopen", return_value=mock_resp_bad_json):
        res_bad_json = client.get("/api/system/ollama-status")
        assert res_bad_json.status_code == 200
        assert res_bad_json.get_json()["available"] is True
        assert res_bad_json.get_json()["models"] == []


@pytest.mark.parametrize("demo_enabled,debug", [(False, False), (True, False), (False, True)])
def test_production_debugger_uses_provider_evidence(client, monkeypatch, demo_enabled, debug):
    from eval_runner.console.routes import system

    monkeypatch.setattr(config, "ENABLE_DEMO", demo_enabled)
    monkeypatch.setitem(client.application.config, "DEBUG", debug)
    provider_events = [{"event": "run_end", "data": {"status": "PROVIDER_RESULT"}}]
    with (
        patch.object(system, "get_run_store") as get_store,
        patch("eval_runner.console.demo_traces.get_demo_trace") as demo,
    ):
        get_store.return_value.get_events.return_value = provider_events
        response = client.get("/api/debugger/state?run_id=run-loan-demo-hydrate")
    assert response.status_code == 200
    assert response.get_json()["data"]["summary"]["message"] == (
        "Evaluation complete. Status: PROVIDER_RESULT"
    )
    demo.assert_not_called()
