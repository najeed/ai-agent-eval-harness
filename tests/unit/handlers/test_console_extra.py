import pytest
import json
from unittest.mock import patch, MagicMock
from eval_runner.console.app import create_app
from eval_runner.console.routes import DebuggerStateStore
import threading

@pytest.fixture
def client(tmp_path):
    # Pass tmp_path as testing directory if needed in future
    app = create_app()
    app.config["TESTING"] = True
    # Mock API Key for all console tests in this file
    api_key = "test-session-key"
    headers = {"X-AES-API-KEY": api_key}
    with patch("eval_runner.console.routes.config.DASHBOARD_API_KEY", api_key):
        with app.test_client() as client:
            # Inject headers into the client for convenience or use them explicitly
            client.environ_base["HTTP_X_AES_API_KEY"] = api_key
            yield client

# Fixtures

# --- /runs exception branch ---
def test_list_runs_parse_exception(client, tmp_path):
    # Setup corrupted log in isolated dir
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    run_log = runs_dir / "run.jsonl"
    run_log.write_text("{corrupt}\n", encoding="utf-8")
    
    with patch("eval_runner.console.routes.config.RUN_LOG_DIR", runs_dir):
        # The loop will hit a JSONDecodeError and continue, returning 200 with empty list (plus demos)
        res = client.get("/api/runs")
        assert res.status_code == 200

def test_evaluate_background_thread(client, tmp_path):
    # Setup isolated scenario
    scenario_path = tmp_path / "test.json"
    scenario_path.write_text(json.dumps({"scenario_id": "test"}), encoding="utf-8")
    
    with patch("eval_runner.loader.load_scenario", return_value={"scenario_id": "test"}), \
         patch("eval_runner.engine.run_evaluation", new_callable=MagicMock) as mock_eval, \
         patch("eval_runner.console.routes.config.PROJECT_ROOT", tmp_path):
         
         # mock_eval needs to be an async coroutine
         async def dummy_run(*args, **kwargs): pass
         mock_eval.side_effect = dummy_run
         
         res = client.post("/api/evaluate", json={"path": "test.json"})
         assert res.status_code == 200
         assert res.json["status"] == "started"

# --- Ping Route ---
def test_ping_route(client):
    res = client.get("/api/ping")
    assert res.status_code == 200
    assert res.json["status"] == "pong"

# --- /scenarios exception ---
def test_save_scenario_exception(client, tmp_path):
    # Setup directories
    (tmp_path / "industries" / "fin" / "scenarios").mkdir(parents=True)
    with patch("eval_runner.console.routes.config.PROJECT_ROOT", tmp_path), \
         patch("builtins.open", side_effect=Exception("Disk full")):
        res = client.post("/api/scenarios", json={"scenario_id": "test", "industry": "fin"})
        assert res.status_code == 500
        assert "Disk full" in res.json["error"]

# --- DebuggerStateStore ---
def test_debugger_state_store_events():
    class MockEvent:
        def __init__(self, name, data):
            self.name = name
            self.data = data
            
    # Push 51 events to trigger pop
    for i in range(51):
        DebuggerStateStore.handle_event(MockEvent("random", {}))
        
    assert len(DebuggerStateStore._events) == 50
    
    # Specific branches
    from eval_runner.events import CoreEvents
    DebuggerStateStore.handle_event(MockEvent("world_state_change", {"state": "s1", "shared_state": "s2"}))
    assert DebuggerStateStore._last_state["state"] == "s1"
    
    DebuggerStateStore.handle_event(MockEvent(CoreEvents.TURN_START, {"turn_idx": 1, "agent_name": "ag"}))
    assert "ag" in DebuggerStateStore._last_state["current_agent"]
    
    DebuggerStateStore.handle_event(MockEvent(CoreEvents.TOOL_CALL, {"tool": "t1", "arguments": {}}))
    assert DebuggerStateStore._last_state["last_tool"] == "t1"
    
    DebuggerStateStore.handle_event(MockEvent(CoreEvents.RUN_START, {"scenario": "sc1"}))
    assert DebuggerStateStore._last_state["scenario"] == "sc1"
    
    DebuggerStateStore.handle_event(MockEvent(CoreEvents.RUN_END, {"status": "win"}))
    assert "win" in DebuggerStateStore._last_state["message"]

# --- Demo trace generation ---
def test_debugger_dynamic_demo_generation(client, tmp_path):
    with patch("eval_runner.console.demo_traces.get_demo_trace", return_value=[{"event": "test"}]), \
         patch("eval_runner.console.routes.config.RUN_LOG_DIR", tmp_path / "runs"):
        # We don't create the file, so Path.exists() for historical will be False.
        # But we need get_demo_trace to be called.
        res = client.get("/api/debugger/state?run_id=run-loan-risk-pass")
        assert res.status_code == 200

def test_debugger_missing_demo_fallback(client, tmp_path):
    with patch("eval_runner.console.routes.config.RUN_LOG_DIR", tmp_path / "runs"), \
         patch("eval_runner.console.demo_traces.get_demo_trace", return_value=None):
        res = client.get("/api/debugger/state?run_id=unknown-id")
        assert res.status_code == 404

# --- Historical trace load edge cases ---
def test_debugger_historical_trace_parsing(client, tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    trace_file = runs_dir / "run-loan-risk-fail.jsonl"
    trace_file.write_text(
        "\n" + 
        json.dumps({"event": "world_state_change", "state": "x", "shared_state": "y"}) + "\n" +
        json.dumps({"event": "agent_request", "content": "help"}) + "\n" +
        json.dumps({"event": "agent_response", "response": {"action": "do"}}) + "\n",
        encoding="utf-8"
    )
    
    with patch("eval_runner.console.routes.config.RUN_LOG_DIR", runs_dir), \
         patch("eval_runner.triage.TriageEngine.identify_root_cause", return_value={}):
        
        res = client.get("/api/debugger/state?run_id=run-loan-risk-fail") 
        assert res.status_code == 200

def test_debugger_historical_exception(client, tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "x.jsonl").write_text("bad data", encoding="utf-8")
    
    # Force a strange exception during open or read if needed, but normally
    # routes.py has try-except. Let's force an actual Exception in json.loads
    with patch("eval_runner.console.routes.config.RUN_LOG_DIR", runs_dir), \
         patch("eval_runner.console.routes.json.loads", side_effect=Exception("Corrupt format")):
        res = client.get("/api/debugger/state?run_id=x")
        assert res.status_code == 500

# --- Docs Branches ---
def test_docs_github_ignore(client, tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / ".github").mkdir()
    (docs_dir / ".github" / "hidden.md").write_text("hidden", encoding="utf-8")
    (docs_dir / "visible.md").write_text("visible", encoding="utf-8")
    
    with patch("eval_runner.console.routes.config.PROJECT_ROOT", tmp_path):
        res = client.get("/api/docs")
        assert res.status_code == 200
        # Verify .github is ignored (not in results)
        data = res.get_json()
        docs = data["docs"]
        assert not any(".github" in d["id"] for d in docs)

def test_docs_read_success(client, tmp_path):
    # Setup isolated docs
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    target_doc = docs_dir / "some.md"
    target_doc.write_text("hello doc", encoding="utf-8")
    
    with patch("eval_runner.console.routes.config.PROJECT_ROOT", tmp_path):
        res = client.get("/api/docs/some.md")
        assert res.status_code == 200
        assert res.json["content"] == "hello doc"

# --- Info endpoint provider branches ---
def test_get_info_google(client):
    with patch("eval_runner.config.GOOGLE_API_KEY", "x"), \
         patch("eval_runner.config.ANTHROPIC_API_KEY", None), \
         patch("eval_runner.config.OPENAI_API_KEY", None), \
         patch("eval_runner.config.AGENT_API_URLS", ["http://google.com/ai"]):
        res = client.get("/api/info")
        assert "Gemini" in res.json["agent_endpoint"]

def test_get_info_anthropic(client):
    with patch("eval_runner.config.GOOGLE_API_KEY", None), \
         patch("eval_runner.config.ANTHROPIC_API_KEY", "x"), \
         patch("eval_runner.config.OPENAI_API_KEY", None), \
         patch("eval_runner.config.AGENT_API_URLS", ["http://anthropic.com/api"]):
        res = client.get("/api/info")
        assert "Claude" in res.json["agent_endpoint"]

def test_get_info_openai(client):
    with patch("eval_runner.config.GOOGLE_API_KEY", None), \
         patch("eval_runner.config.ANTHROPIC_API_KEY", None), \
         patch("eval_runner.config.OPENAI_API_KEY", "x"), \
         patch("eval_runner.config.AGENT_API_URLS", ["http://openai.com/v1"]):
        res = client.get("/api/info")
        assert "GPT" in res.json["agent_endpoint"]

# --- Refresh catchall ---
def test_refresh_index_exception(client):
    with patch("eval_runner.catalog.ScenarioCatalog.build_index", side_effect=Exception("DB dead")):
        res = client.post("/api/scenarios/refresh")
        assert res.status_code == 500

# --- App Index and Plugin Exceptions ---
def test_app_index_route(client):
    with patch("eval_runner.console.app.send_from_directory", return_value="index content"):
        res = client.get("/")
        assert res.status_code == 200

def test_app_plugin_registration_exception():
    class BadPlugin:
        def on_register_console_routes(self, app, reg):
            raise Exception("Bad plugin crash")
            
    with patch("eval_runner.console.app.manager.plugins", [BadPlugin()]):
        app = create_app()
        assert app is not None
