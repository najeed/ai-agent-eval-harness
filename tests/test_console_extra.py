import pytest
import json
from unittest.mock import patch, MagicMock
from eval_runner.console.app import create_app
from eval_runner.console.routes import DebuggerStateStore

@pytest.fixture
def client(tmp_path):
    # Pass tmp_path as testing directory if needed in future
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

# --- /runs exception branch ---
def test_list_runs_parse_exception(client, tmp_path):
    with patch("eval_runner.console.routes.Path.exists", return_value=True), \
         patch("eval_runner.console.routes.Path.iterdir") as mock_iter, \
         patch("builtins.open") as mock_open:
        
        f = MagicMock()
        f.suffix = ".jsonl"
        f.name = "r1.jsonl"
        f.stat.return_value.st_mtime = 1000
        mock_iter.return_value = [f]
        
        # Make the readlines return corrupted json to trigger exception
        mock_open.return_value.__enter__.return_value = ["{corrupt}\n"]
        res = client.get("/api/runs")
        assert res.status_code == 200

# --- /evaluate inner thread ---
def test_evaluate_background_thread():
    from eval_runner.console.routes import evaluate_scenario
    # The actual inner function `run_in_background` is defined locally so it's tricky,
    # but we can just DONOT mock threading.Thread, and let it run an AsyncMock.
    app = create_app()
    with app.test_request_context(json={"path": "test.json"}):
        with patch("eval_runner.console.routes.Path.exists", return_value=True), \
             patch("eval_runner.console.routes.load_scenario", return_value={"scenario_id": "test"}), \
             patch("eval_runner.console.routes.run_evaluation", new_callable=MagicMock) as mock_eval:
             # We just let it execute threading.Thread! 
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
def test_save_scenario_exception(client):
    with patch("builtins.open", side_effect=Exception("Disk full")):
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
def test_debugger_dynamic_demo_generation(client):
    with patch("eval_runner.console.routes.Path.exists", side_effect=[False, False]), \
         patch("eval_runner.console.demo_traces.get_demo_trace", return_value=[{"event": "test"}]), \
         patch("builtins.open") as mock_open:
        res = client.get("/api/debugger/state?run_id=run-loan-risk-pass")
        assert res.status_code == 200
        mock_open.assert_called()

def test_debugger_missing_demo_fallback(client):
    with patch("eval_runner.console.routes.Path.exists", return_value=False), \
         patch("eval_runner.console.demo_traces.get_demo_trace", return_value=None):
        res = client.get("/api/debugger/state?run_id=unknown-id")
        assert res.status_code == 404

# --- Historical trace load edge cases ---
def test_debugger_historical_trace_parsing(client):
    with patch("eval_runner.console.routes.Path.exists", side_effect=[True]), \
         patch("eval_runner.console.demo_traces.get_demo_trace", return_value=[]), \
         patch("builtins.open") as mock_open, \
         patch("eval_runner.triage.TriageEngine.identify_root_cause", return_value={}):
         
        # empty line test, agent request, agent response
        mock_open.return_value.__enter__.return_value = [
            "\n", 
            json.dumps({"event": "world_state_change", "state": "x", "shared_state": "y"}),
            json.dumps({"event": "agent_request", "content": "help"}),
            json.dumps({"event": "agent_response", "response": {"action": "do"}})
        ]
        
        res = client.get("/api/debugger/state?run_id=run-loan-risk-fail") # specifically tests fail branch
        assert res.status_code == 200

def test_debugger_historical_exception(client):
    with patch("eval_runner.console.routes.Path.exists", return_value=True), \
         patch("builtins.open", side_effect=Exception("Corrupt format")):
        res = client.get("/api/debugger/state?run_id=x")
        assert res.status_code == 500

# --- Docs Branches ---
def test_docs_github_ignore(client):
    with patch("eval_runner.console.routes.Path.rglob") as mock_rglob:
        mock_file = MagicMock()
        mock_file.__str__.return_value = ".github/hidden.md"
        mock_rglob.return_value = [mock_file]
        res = client.get("/api/docs")
        assert res.status_code == 200

def test_docs_read_success(client):
    with patch("eval_runner.console.routes.Path.exists", return_value=True), \
         patch("eval_runner.console.routes.Path.is_file", return_value=True), \
         patch("builtins.open") as mock_open:
        mock_open.return_value.__enter__.return_value.read.return_value = "hello doc"
        res = client.get("/api/docs/some.md")
        assert res.status_code == 200
        assert res.json["content"] == "hello doc"

# --- Info endpoint provider branches ---
def test_get_info_google(client):
    with patch("eval_runner.config.GOOGLE_API_KEY", "x"):
        res = client.get("/api/info")
        assert "Gemini" in res.json["agent_endpoint"]

def test_get_info_anthropic(client):
    with patch("eval_runner.config.ANTHROPIC_API_KEY", "x"):
        res = client.get("/api/info")
        assert "Claude" in res.json["agent_endpoint"]

def test_get_info_openai(client):
    with patch("eval_runner.config.OPENAI_API_KEY", "x"):
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
