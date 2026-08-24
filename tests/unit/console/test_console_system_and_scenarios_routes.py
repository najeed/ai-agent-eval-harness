"""
tests/unit/console/test_console_system_and_scenarios_routes.py
Behavioral test suite for System, Documentation, Diagnostic,
and Scenario endpoints in the Visual Console.
"""

import json
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
    docs = root / "docs-v1-deprecated-reference"

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


# ---------------------------------------------------------------------------
# 1. Debugger State Store Ingest and Formatting
# ---------------------------------------------------------------------------


def test_debugger_state_handle_event_non_dict_fallback():
    """Verify DebuggerStateStore extracts fields when event object is non-dict."""

    class MockEvent:
        def __init__(self):
            self.name = "mock_event"
            self.data = {"val": 123}
            self.timestamp = "time_stamp"

    DebuggerStateStore.handle_event(MockEvent())
    state = DebuggerStateStore.get_state()
    assert state["timeline"][0]["event"] == "mock_event"
    assert state["timeline"][0]["val"] == 123


def test_debugger_state_handle_event_status_attribute_fallback():
    """Verify DebuggerStateStore falls back to status when event name is absent."""
    e = {"status": "in_progress", "foo": "bar"}
    DebuggerStateStore.handle_event(e)
    state = DebuggerStateStore.get_state()
    assert state["timeline"][0]["event"] == "in_progress"


def test_debugger_state_root_cause_extraction():
    """Verify DebuggerStateStore extracts and isolates root cause event telemetry."""
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


def test_debugger_state_store_post_event_non_dict_data_handling():
    """Verify DebuggerStateStore.post_event safely ingests non-dict data payloads."""
    DebuggerStateStore.reset()
    DebuggerStateStore.post_event({"event": "test"})
    DebuggerStateStore.post_event({"event": "test", "data": "string_not_dict"})
    assert len(DebuggerStateStore._events) == 2


def test_debugger_state_loan_narrative_formatting(client):
    """Verify loan narrative summary formatting for industrial demo runs."""
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
    assert "(Industrial Demo Narrative)" in msg


def test_debugger_state_demo_trace_hydration_bypass(client):
    """Verify debugger state serves demo traces directly when present."""
    demo_events = [{"event": "run_start", "data": {}}]
    with patch("eval_runner.console.demo_traces.get_demo_trace", return_value=demo_events):
        res = client.get("/api/debugger/state?run_id=run-loan-demo-hydrate")
    assert res.status_code == 200
    body = res.get_json()
    assert "data" in body
    assert "timeline" in body["data"]


def test_debugger_state_nested_glob_and_empty_line_handling(client, console_jail):
    """Verify trace parsing tolerates empty lines and discovers traces via nested glob."""
    runs_dir = console_jail["runs"]
    nested_dir = runs_dir / "nested_folder" / "glob_run_id"
    nested_dir.mkdir(parents=True, exist_ok=True)
    (nested_dir / "run.jsonl").write_text(
        '\n\n{"event": "run_start", "data": {}}\n\n', encoding="utf-8"
    )

    res = client.get("/api/debugger/state?run_id=glob_run_id")
    assert res.status_code == 200
    assert len(res.get_json()["data"]["timeline"]) == 1


def test_debugger_state_corrupt_trace_error_reporting(client, console_jail):
    """Verify 500 error reporting when historical trace contains invalid JSON."""
    run_id = "broken_trace_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("invalid json lines here{", encoding="utf-8")

    res = client.get(f"/api/debugger/state?run_id={run_id}")
    assert res.status_code == 500
    assert "Failed to parse trace file" in res.get_json()["error"]


def test_debugger_state_missing_trace_404(client):
    """Verify 404 response when requesting non-existent run ID trace."""
    res = client.get("/api/debugger/state?run_id=missing_run_id_for_debugger")
    assert res.status_code == 404
    assert "Trace file not found" in res.get_json()["error"]


# ---------------------------------------------------------------------------
# 2. Navigation, Docs, and System Info Routes
# ---------------------------------------------------------------------------


def test_navigation_registry_delivery(client):
    """Verify /api/nav delivers configured navigation manifest."""
    with patch.dict(client.application.config, {"NAV_REGISTRY": ["item1", "item2"]}):
        res = client.get("/api/nav")
        assert res.status_code == 200
        assert res.get_json()["nav"] == ["item1", "item2"]


def test_list_docs_categorization_and_hidden_file_filtering(client, console_jail):
    """Verify list_docs categorizes documentation and filters hidden directories."""
    docs_dir = console_jail["docs"]
    github_doc = docs_dir / ".github" / "workflows" / "ci.md"
    github_doc.parent.mkdir(parents=True, exist_ok=True)
    github_doc.write_text("ci", encoding="utf-8")

    api_doc = docs_dir / "api" / "ref.md"
    api_doc.write_text("ref", encoding="utf-8")

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


def test_list_docs_duplicate_stem_deduplication(client, console_jail):
    """Verify list_docs deduplicates document items sharing the same stem."""
    docs_dir = console_jail["docs"]
    doc1 = docs_dir / "dup.md"
    doc2 = docs_dir / "guides" / "dup.md"
    doc1.write_text("dup1", encoding="utf-8")
    doc2.write_text("dup2", encoding="utf-8")

    res = client.get("/api/docs")
    assert res.status_code == 200
    docs = res.get_json()["docs"]
    stems = [d["id"] for d in docs]
    assert stems.count("dup") == 1


def test_list_docs_missing_directory_graceful_empty_list(client):
    """Verify list_docs returns empty array when documentation root is missing."""
    with patch.object(config, "PROJECT_ROOT", Path("non_existent_folder_xyz")):
        res = client.get("/api/docs")
        assert res.status_code == 200
        assert res.get_json()["docs"] == []


def test_read_doc_extension_fallback(client, console_jail):
    """Verify read_doc automatically appends .md extension when omitted."""
    docs_dir = console_jail["docs"]
    doc = docs_dir / "my_guide.md"
    doc.write_text("my guide content", encoding="utf-8")

    res = client.get("/api/docs/my_guide")
    assert res.status_code == 200
    assert res.get_json()["content"] == "my guide content"


def test_read_doc_not_found(client):
    """Verify read_doc returns 404 when markdown file does not exist."""
    res = client.get("/api/docs/nonexistent_doc_file_path.md")
    assert res.status_code == 404
    assert res.get_json()["error"] == "Not Found"


def test_security_intercept_path_traversal_attempts(client):
    """Verify security interceptor blocks directory traversal attempts in routes."""
    res = client.get("/api/docs/..%2fetc/passwd")
    assert res.status_code == 403
    assert "Security: Unauthorized Path Traversal" in res.get_json()["error"]


def test_system_info_agent_provider_inference(client):
    """Verify /api/info accurately identifies configured LLM provider and endpoints."""
    from eval_runner.catalog import ScenarioCatalog

    catalog = ScenarioCatalog.get_instance()
    catalog.clear_instance()
    catalog = ScenarioCatalog.get_instance()
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
    finally:
        catalog.scenarios = []


def test_system_ping(client):
    """Verify /api/ping responds with status pong."""
    res = client.get("/api/ping")
    assert res.status_code == 200
    assert res.get_json()["status"] == "pong"


# ---------------------------------------------------------------------------
# 3. Cleanup, Diagnostics, and Ollama Routes
# ---------------------------------------------------------------------------


def test_cleanup_runs_files_and_plugin_notification(client, console_jail):
    """Verify cleanup_runs removes stale run artifacts and triggers plugin hooks."""
    runs_dir = console_jail["runs"]
    (runs_dir / "run_dir_1").mkdir(parents=True, exist_ok=True)
    (runs_dir / "run_1.jsonl").write_text("{}", encoding="utf-8")
    (runs_dir / "run_2.txt").write_text("{}", encoding="utf-8")

    class CrashingCleanupPlugin:
        def on_cleanup_runs(self):
            raise ValueError("Plugin cleanup failed")

    from eval_runner.plugins import manager

    plugin = CrashingCleanupPlugin()
    manager.plugins.append(plugin)

    try:
        res = client.post("/api/cleanup-runs")
        assert res.status_code == 200
        assert res.get_json()["count"] >= 2
        assert not (runs_dir / "run_dir_1").exists()
        assert not (runs_dir / "run_1.jsonl").exists()
        assert (runs_dir / "run_2.txt").exists()
    finally:
        manager.plugins.remove(plugin)


def test_cleanup_runs_missing_directory_returns_zero(client, monkeypatch):
    """Verify cleanup_runs returns count 0 when RUN_LOG_DIR is non-existent."""
    monkeypatch.setattr(config, "RUN_LOG_DIR", Path("/nonexistent_dir_xyz_aes"))
    res = client.post("/api/cleanup-runs")
    assert res.status_code == 200
    assert res.get_json()["count"] == 0


def test_cleanup_runs_exception_returns_500(client):
    """Verify cleanup_runs returns 500 on filesystem error."""
    with patch.object(Path, "exists", side_effect=Exception("Disk locked")):
        res = client.post("/api/cleanup-runs")
        assert res.status_code == 500
        assert "Disk locked" in res.get_json()["message"]


def test_doctor_audit_exception_handling(client):
    """Verify /api/v1/doctor returns 500 when diagnostics registry encounters fatal failure."""
    with patch(
        "eval_runner.console.routes.system.get_simulator_registry",
        side_effect=RuntimeError("Doctor audit failed"),
    ):
        res = client.get("/api/v1/doctor")
        assert res.status_code == 500
        assert "Doctor audit failed" in res.get_json()["error"]


def test_ollama_status_connectivity_matrix(client):
    """Verify ollama status check across valid server, unreachable server, and non-http protocol."""

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

    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        res2 = client.get("/api/system/ollama-status")
    assert res2.status_code == 200
    assert res2.get_json()["available"] is False

    with patch.object(config, "OLLAMA_BASE_URL", "grpc://localhost:9000", create=True):
        res3 = client.get("/api/system/ollama-status")
    assert res3.status_code == 200
    assert res3.get_json()["available"] is False


# ---------------------------------------------------------------------------
# 4. Auto-Translate and Scenario Mutation Routes
# ---------------------------------------------------------------------------


def test_auto_translate_success_flow(client):
    """Verify /api/v1/auto-translate converts specification markdown into scenario."""
    mock_scenario = {"id": "scenario-1", "title": "Mock Title"}

    async def mock_translate(*args, **kwargs):
        return mock_scenario

    with patch("eval_runner.auto_translate.translate_to_scenario", side_effect=mock_translate):
        res = client.post("/api/v1/auto-translate", json={"text": "raw specs", "model": "m1"})
        assert res.status_code == 200
        assert res.get_json() == mock_scenario


def test_auto_translate_missing_text_returns_400(client):
    """Verify /api/v1/auto-translate rejects requests lacking input text."""
    res = client.post("/api/v1/auto-translate", json={"model": "m1"})
    assert res.status_code == 400
    assert "Missing required field: text" in res.get_json()["error"]


def test_scenarios_evaluate_by_scenario_id(client, console_jail):
    """Verify /api/v1/evaluate resolves scenarios by ID from catalog index."""
    from eval_runner.catalog import ScenarioCatalog

    cat = ScenarioCatalog.get_instance()
    scen_dir = console_jail["root"] / "industries" / "generic" / "scenarios"
    scen_dir.mkdir(parents=True, exist_ok=True)
    scen_file = scen_dir / "scen_evaluate_id.json"
    scen_file.write_text('{"id": "scen_evaluate_id", "title": "Scen Title"}', encoding="utf-8")

    # Hermetic: restore singleton state so xdist workers are not polluted.
    prev_scenarios = cat.scenarios
    cat.scenarios = [
        {"id": "scen_evaluate_id", "path": "industries/generic/scenarios/scen_evaluate_id.json"}
    ]
    try:
        from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

        backend = InProcessExecutionBackend.get_instance()
        with (
            patch("eval_runner.loader.load_scenario", return_value={"id": "scen_evaluate_id"}),
            # The route submits through the InProcessExecutionBackend;
            # intercept at that boundary so no real dispatch can leak.
            patch.object(backend, "submit", return_value="queued") as mock_submit,
        ):
            res = client.post("/api/v1/evaluate", json={"path": "scen_evaluate_id"})
            assert res.status_code == 200
            assert res.get_json()["status"] == "started"
            assert mock_submit.called
    finally:
        cat.scenarios = prev_scenarios


def test_scenarios_mutate_by_scenario_id(client, console_jail):
    """Verify /api/v1/mutate resolves scenario by ID and performs mutation."""
    from eval_runner.catalog import ScenarioCatalog

    cat = ScenarioCatalog.get_instance()
    scen_dir = console_jail["root"] / "scenarios"
    scen_dir.mkdir(parents=True, exist_ok=True)
    scen_file = scen_dir / "scen_mutate_id.json"
    scen_file.write_text('{"id": "scen_mutate_id", "title": "Original"}', encoding="utf-8")

    prev_scenarios = cat.scenarios
    cat.scenarios = [{"id": "scen_mutate_id", "path": "scenarios/scen_mutate_id.json"}]
    try:
        with patch(
            "eval_runner.mutator.mutate_scenario",
            return_value={"id": "scen_mutate_id", "title": "Mutated"},
        ):
            res = client.post(
                "/api/v1/mutate", json={"scenario_id": "scen_mutate_id", "type": "typo"}
            )
            assert res.status_code == 200
            assert res.get_json()["mutated"]["title"] == "Mutated"
    finally:
        cat.scenarios = prev_scenarios


def test_scenarios_mutate_by_id_not_found(client):
    """Verify /api/v1/mutate returns 404 when scenario ID is not in catalog."""
    res = client.post("/api/v1/mutate", json={"scenario_id": "nonexistent_mutate_id"})
    assert res.status_code == 404
    assert "not found" in res.get_json()["error"]


# ---------------------------------------------------------------------------
# 5. Deep AES Schema & Semantic Invariant Validation Tests
# ---------------------------------------------------------------------------


def test_validate_scenario_structure_branches():
    from eval_runner.console.routes.scenarios import validate_scenario_structure

    # 1. Non-dict root
    valid, errs = validate_scenario_structure("not_a_dict")  # type: ignore
    assert not valid
    assert "must be a JSON object" in errs[0]

    # 2. Missing metadata.id
    valid, errs = validate_scenario_structure({"metadata": {}})
    assert not valid
    assert any("metadata.id" in e for e in errs)

    # 3. Empty or non-list nodes
    valid, errs = validate_scenario_structure(
        {"metadata": {"id": "test_s"}, "workflow": {"nodes": []}}
    )
    assert not valid
    assert any("at least one task node" in e for e in errs)

    # 4. Non-dict node, missing node id, duplicate node id
    valid, errs = validate_scenario_structure(
        {
            "metadata": {"id": "test_s"},
            "workflow": {
                "nodes": [
                    "not_a_dict",
                    {"prompt": "do task"},
                    {"id": "node1", "task_description": "task 1"},
                    {"id": "node1", "task_description": "task 1 dup"},
                    {"id": "node2"},  # Missing prompt
                    {"id": "node3", "prompt": "p3", "required_tools": "not_a_list"},
                ]
            },
        }
    )
    assert not valid
    assert any("Node at index 0 must be an object" in e for e in errs)
    assert any("missing required string 'id'" in e for e in errs)
    assert any("Duplicate node id 'node1'" in e for e in errs)
    assert any("missing 'task_description' or prompt" in e for e in errs)
    assert any("required_tools must be a list" in e for e in errs)

    # 5. Edge validation: non-dict edge, unknown source/target
    valid, errs = validate_scenario_structure(
        {
            "metadata": {"id": "test_s"},
            "workflow": {
                "nodes": [
                    {"id": "n1", "prompt": "p1"},
                    {"id": "n2", "prompt": "p2"},
                ],
                "edges": [
                    "not_a_dict",
                    {"source": "unknown_src", "target": "n2"},
                    {"source": "n1", "target": "unknown_tgt"},
                ],
            },
        }
    )
    assert not valid
    assert any("Edge at index 0 must be an object" in e for e in errs)
    assert any("unknown source node" in e for e in errs)
    assert any("unknown target node" in e for e in errs)

    # 6. Cycle detection (A -> B -> A)
    valid, errs = validate_scenario_structure(
        {
            "metadata": {"id": "cyclic_scenario"},
            "workflow": {
                "nodes": [
                    {"id": "nodeA", "prompt": "A"},
                    {"id": "nodeB", "prompt": "B"},
                ],
                "edges": [
                    {"source": "nodeA", "target": "nodeB"},
                    {"source": "nodeB", "target": "nodeA"},
                ],
            },
        }
    )
    assert not valid
    assert any("contains a cycle; must be a valid DAG" in e for e in errs)

    # 7. Non-list evaluation.assertions
    valid, errs = validate_scenario_structure(
        {
            "metadata": {"id": "test_eval"},
            "workflow": {"nodes": [{"id": "n1", "prompt": "p1"}]},
            "evaluation": {"assertions": "not_a_list"},
        }
    )
    assert not valid
    assert any("evaluation.assertions' must be a list" in e for e in errs)

    # 8. Fully Valid Complex DAG
    valid, errs = validate_scenario_structure(
        {
            "metadata": {"id": "valid_dag"},
            "workflow": {
                "nodes": [
                    {"id": "start", "prompt": "Start task", "required_tools": ["t1"]},
                    {"id": "branch1", "task_description": "Branch 1"},
                    {"id": "branch2", "prompt": "Branch 2"},
                    {"id": "end", "task_description": "End task"},
                ],
                "edges": [
                    {"source": "start", "target": "branch1"},
                    {"source": "start", "target": "branch2"},
                    {"source": "branch1", "target": "end"},
                    {"source": "branch2", "target": "end"},
                ],
            },
            "evaluation": {"assertions": [{"name": "assert_success", "type": "exact_match"}]},
        }
    )
    assert valid
    assert len(errs) == 0


def test_check_execution_readiness_branches(client, console_jail, monkeypatch):
    """Verify readiness probes with configured signer key and custom protocols."""
    from eval_runner import config

    # With configured persistent SIGNING_KEY
    monkeypatch.setattr(config, "SIGNING_KEY", "ed25519_sk_0123456789abcdef", raising=False)

    scen_data = {
        "metadata": {"id": "scen_ready_check", "status": "Ready"},
        "workflow": {"nodes": [{"id": "n1", "prompt": "task 1"}]},
    }
    scen_path = console_jail["root"] / "scenarios" / "scen_ready_check.json"
    scen_path.parent.mkdir(parents=True, exist_ok=True)
    scen_path.write_text(json.dumps(scen_data), encoding="utf-8")

    res = client.post(
        "/api/scenarios/readiness",
        json={
            "scenario_id": "scen_ready_check",
            "scenario_data": scen_data,
            "agent_config": {"protocol": "custom_agent_protocol", "endpoint": "http://custom:9999"},
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ready"] is True
    checks = {c["name"]: c for c in data["checks"]}

    # Verify persistent SIGNED sealer
    assert checks["Cryptographic Sealer"]["status"] == "PASSED"
    assert checks["Cryptographic Sealer"]["signer_type"] == "SIGNED"

    # Verify custom protocol warning: configured but not proven reachable
    # (preflight tiers: CONFIGURED < REACHABLE < EXECUTABLE < VERIFIABLE)
    agent_check = checks["Agent Endpoint"]
    assert agent_check["status"] == "WARNING"
    assert agent_check["tier"] == "CONFIGURED"
    assert "custom_agent_protocol" in agent_check["message"]
