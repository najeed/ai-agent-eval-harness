from flask import Blueprint, jsonify, request
import os
from pathlib import Path
import json
from datetime import datetime

core_bp = Blueprint("core", __name__, url_prefix="/api")


def register_core_routes(app, nav_registry):
    # Add core navigation items with metadata for dynamic rendering
    from ..config import ENABLE_DEMO

    items = [
        {
            "id": "dashboard",
            "title": "Dashboard",
            "path": "/",
            "icon": "home",
            "type": "internal",
        },
        {
            "id": "scenarios",
            "title": "Scenarios",
            "path": "/scenarios",
            "icon": "file-text",
            "type": "internal",
        },
        {
            "id": "reports",
            "title": "Reports & Traces",
            "path": "/reports",
            "icon": "bar-chart-2",
            "type": "internal",
        },
        {
            "id": "editor",
            "title": "Scenario Editor",
            "path": "/editor",
            "icon": "file-text",
            "type": "internal",
        },
        {
            "id": "debugger",
            "title": "Visual Debugger",
            "path": "/debugger",
            "icon": "activity",
            "type": "internal",
        },
        {
            "id": "docs",
            "title": "Documentation",
            "path": "/docs",
            "icon": "book",
            "type": "internal",
        },
    ]

    if ENABLE_DEMO:
        items.append(
            {
                "id": "demo",
                "title": "Demo Story",
                "path": "/demo",
                "icon": "play",
                "type": "internal",
            }
        )

    items.extend(
        [
            {
                "id": "api_docs",
                "title": "API Reference",
                "path": "/docs/api",
                "icon": "box",
                "type": "internal",
            },
            {
                "id": "community",
                "title": "Community",
                "path": "https://github.com/najeed/ai-agent-eval-harness",
                "icon": "github",
                "type": "external",
            },
        ]
    )

    nav_registry.extend(items)
    app.register_blueprint(core_bp)


@core_bp.route("/scenarios", methods=["GET"])
def list_scenarios():
    """Returns a faceted list of all scenarios."""
    from ..catalog import ScenarioCatalog
    from ..linter import ScenarioLinter

    query = request.args.get("q")
    industry = request.args.get("industry")
    difficulty = request.args.get("difficulty")

    catalog = ScenarioCatalog()
    catalog.load_index()

    results = catalog.search(query=query, industry=industry, difficulty=difficulty)
    total = len(results)

    # Use pre-calculated linting from index for speed
    return jsonify(
        {
            "scenarios": results[:200],  # Return more for searchability
            "total_count": total,
        }
    )


@core_bp.route("/runs", methods=["GET"])
def list_runs():
    """Returns a list of recent run traces."""
    query = request.args.get("q", "").lower()
    runs = []
    run_log = Path("runs") / "run.jsonl"
    if run_log.exists():
        try:
            with open(run_log, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line.strip())
                        if event.get("event") == "run_start":
                            run_id = event.get("run_id")
                            scenario = event.get("scenario")

                            # Filter by query if provided
                            if query and query not in run_id.lower() and query not in scenario.lower():
                                continue

                            runs.append(
                                {
                                    "run_id": run_id,
                                    "scenario": scenario,
                                    "timestamp": event.get("timestamp"),
                                }
                            )
                    except Exception:
                        pass
        except Exception:
            pass
    # Reverse to show newest first
    runs.reverse()
    return jsonify({"runs": runs[:100]})


@core_bp.route("/evaluate", methods=["POST"])
def evaluate_scenario():
    """Trigger an evaluation in the background."""
    data = request.json or {}
    path_str = data.get("path")
    if not path_str:
        return jsonify({"error": "Missing 'path' parameter"}), 400

    path = Path(path_str)
    if not path.exists():
        # Try relative to root?
        path = Path(__file__).parent.parent.parent / path_str
        if not path.exists():
            return jsonify({"error": f"Scenario not found at {path_str}"}), 404

    from ..loader import load_scenario
    from ..engine import run_evaluation
    import asyncio
    import threading

    def run_in_background(scenario_data):
        # We need a new event loop for the background thread if one doesn't exist
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_evaluation(scenario_data))
        loop.close()

    try:
        scenario_data = load_scenario(path)
        # Launch evaluation in a background thread to avoid blocking Flask
        thread = threading.Thread(target=run_in_background, args=(scenario_data,))
        thread.start()

        return jsonify(
            {
                "status": "started",
                "message": f"Evaluation started for {path.name}",
                "scenario_id": scenario_data.get("scenario_id"),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@core_bp.route("/scenarios", methods=["POST"])
def save_scenario():
    """Saves or updates a scenario JSON file."""
    data = request.json or {}
    scenario_id = data.get("scenario_id")
    if not scenario_id:
        return jsonify({"error": "Missing scenario_id"}), 400

    # Secure path resolution (prevent traversal)
    safe_id = "".join(c for c in scenario_id if c.isalnum() or c in ("-", "_")).strip()
    if not safe_id:
        return jsonify({"error": "Invalid scenario_id"}), 400

    industry = data.get("industry", "generic")
    output_dir = Path("industries") / industry / "scenarios"
    output_dir.mkdir(parents=True, exist_ok=True)

    file_path = output_dir / f"{safe_id}.json"

    # Structure the AES JSON
    scenario_obj = {
        "scenario_id": safe_id,
        "version": data.get("version", "2.0.0"),
        "title": data.get("title", "Untitled Scenario"),
        "industry": industry,
        "description": data.get("description", ""),
        "tasks": data.get("tasks", []),
        "metadata": data.get(
            "metadata",
            {
                "difficulty": data.get("difficulty", 1),
                "tags": data.get("tags", []),
                "created_at": datetime.now().isoformat(),
            },
        ),
    }

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(scenario_obj, f, indent=2)

        # Invalidate catalog index to reflect changes
        from ..catalog import ScenarioCatalog

        ScenarioCatalog().build_index()

        return jsonify(
            {
                "status": "success",
                "path": str(file_path),
                "message": "Scenario saved and indexed.",
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


class DebuggerStateStore:
    """Captured live states from the engine for the Visual Debugger."""

    _last_state = {"message": "Waiting for evaluation..."}
    _events = []
    _is_active = False

    @classmethod
    def handle_event(cls, event):
        from ..events import CoreEvents

        name = event.name
        data = event.data

        # Track history for timeline
        cls._events.append({"event": name, "timestamp": datetime.now().isoformat(), **data})
        # Keep only the last 50 events
        if len(cls._events) > 50:
            cls._events.pop(0)

        # Update summary state
        if name == "world_state_change":
            cls._last_state["state"] = data.get("state")
            cls._last_state["shared_state"] = data.get("shared_state")
        elif name == CoreEvents.TURN_START:
            cls._last_state["message"] = f"Processing Turn {data.get('turn_idx')}..."
            cls._last_state["current_agent"] = data.get("agent_name")
        elif name == CoreEvents.TOOL_CALL:
            cls._last_state["last_tool"] = data.get("tool")
            cls._last_state["last_params"] = data.get("arguments")
        elif name == CoreEvents.RUN_START:
            cls._last_state = {
                "message": "Run started...",
                "scenario": data.get("scenario"),
            }
        elif name == CoreEvents.RUN_END:
            cls._last_state["message"] = f"Run finished: {data.get('status')}"

    @classmethod
    def get_latest(cls):
        return {"summary": cls._last_state, "timeline": cls._events}


# Subscribe to events for the debugger
from ..events import EventEmitter

EventEmitter.subscribe(DebuggerStateStore.handle_event)


@core_bp.route("/ping")
def ping():
    return jsonify(
        {
            "status": "pong",
            "version": "v1.6-verified",
            "cwd": os.getcwd(),
            "file": __file__,
        }
    )


@core_bp.route("/debugger/state", methods=["GET", "POST"])
def get_debugger_state():
    """Retrieve or update realtime or latest interactive debugger state."""
    if request.method == "POST":
        data = request.json or {}

        # Simulate a CoreEvent for the store
        class MockEvent:
            def __init__(self, name, data):
                self.name = name
                self.data = data

        event_name = data.get("event")
        event_data = data.get("data", {})
        if event_name:
            DebuggerStateStore.handle_event(MockEvent(event_name, event_data))
        return jsonify({"status": "updated"})

    # Check for run_id to load historical trace
    run_id = request.args.get("run_id")
    if run_id:
        project_root = Path(__file__).parent.parent.parent
        runs_dir = project_root / "runs"
        demo_dir = runs_dir / "demo"

        # 1. Try standard locations
        paths_to_check = [runs_dir / f"{run_id}.jsonl", demo_dir / f"{run_id}.jsonl"]

        trace_file = next((p for p in paths_to_check if p.exists()), None)

        # 2. Dynamic generation for demo IDs if not found on disk
        if not trace_file and run_id in ["run-loan-risk-fail", "run-loan-risk-pass"]:
            from .demo_traces import get_demo_trace

            events = get_demo_trace(run_id)
            if events:
                try:
                    demo_dir.mkdir(parents=True, exist_ok=True)
                    trace_file = demo_dir / f"{run_id}.jsonl"
                    with open(trace_file, "w", encoding="utf-8") as f:
                        for ev in events:
                            f.write(json.dumps(ev) + "\n")
                    print(f"DEBUG: Dynamically generated demo trace at {trace_file}", flush=True)
                except Exception as e:
                    print(f"ERROR generating demo trace: {e}", flush=True)
                    # Fallback to serving in-memory if disk write fails
                    summary = {"message": f"Demo Narrative: {run_id.replace('-', ' ').title()}"}
                    from ..triage import TriageEngine

                    return jsonify(
                        {
                            "status": "ok",
                            "message": "Demo trace loaded from memory (disk write failed)",
                            "data": {
                                "summary": summary,
                                "timeline": events,
                                "root_cause": TriageEngine.identify_root_cause(events),
                            },
                        }
                    )

        if not trace_file:
            print(f"DEBUG: Trace file MISSING for {run_id}", flush=True)
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"Trace file not found for run_id: {run_id}",
                    }
                ),
                404,
            )

        print(f"DEBUG: Loading trace from {trace_file}", flush=True)
        events = []
        summary = {"message": f"Historical Trace: {run_id}"}
        if run_id.startswith("run-loan-risk"):
            summary["message"] = f"Demo Narrative: {run_id.replace('-', ' ').title()}"
            if run_id == "run-loan-risk-fail":
                summary["message"] = "Demo Narrative: Loan Approval Failure Analysis"

        try:
            with open(trace_file, "r", encoding="utf-8-sig") as f:
                for line in f:
                    clean_line = line.strip()
                    if not clean_line:
                        continue
                    ev = json.loads(clean_line)
                    events.append(ev)
                    # Minimal summary extraction for historical view
                    if ev.get("event") == "world_state_change":
                        summary["state"] = ev.get("state")
                        summary["shared_state"] = ev.get("shared_state")
                    elif ev.get("event") == "agent_request":
                        summary["message"] = f"User: {ev.get('content')}"
                    elif ev.get("event") == "agent_response":
                        summary["last_tool"] = ev.get("response", {}).get("action")

            # Identify root cause using TriageEngine
            from ..triage import TriageEngine

            root_cause = TriageEngine.identify_root_cause(events)

            return jsonify(
                {
                    "status": "ok",
                    "message": "Historical trace loaded",
                    "data": {
                        "summary": summary,
                        "timeline": events,
                        "root_cause": root_cause,
                    },
                }
            )
        except Exception as e:
            import traceback

            print(f"ERROR loading {run_id}: {str(e)}", flush=True)
            traceback.print_exc()
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": str(e),
                        "path": str(trace_file),
                        "traceback": traceback.format_exc(),
                    }
                ),
                500,
            )

    return jsonify(
        {
            "status": "ok",
            "message": "Live data hook is active",
            "data": DebuggerStateStore.get_latest(),
        }
    )


@core_bp.route("/docs", methods=["GET"])
def list_docs():
    """Retrieve available documentation guides and API reference."""
    docs = []
    seen_ids = set()
    base = Path("docs")

    # Check for auto-generated API docs first to give them priority/specific category
    api_base = base / "api"
    if api_base.exists() and api_base.is_dir():
        for file in api_base.rglob("*.md"):
            doc_id = str(file.relative_to(base))
            if doc_id not in seen_ids:
                docs.append(
                    {
                        "id": doc_id,
                        "title": f"API: {file.stem}",
                        "category": "API Reference",
                    }
                )
                seen_ids.add(doc_id)

    # Standard Markdown Guides (remaining ones)
    for file in base.rglob("*.md"):
        if ".github" in str(file):
            continue
        doc_id = str(file.relative_to(base))
        if doc_id not in seen_ids:
            docs.append({"id": doc_id, "title": file.stem, "category": "Guide"})
            seen_ids.add(doc_id)

    return jsonify({"docs": docs})


@core_bp.route("/docs/<path:doc_path>", methods=["GET"])
def read_doc(doc_path):
    """Read a specific documentation markdown file."""
    base = Path("docs")
    target = base / doc_path

    # Simple path traversal protection
    if not str(target.resolve()).startswith(str(base.resolve())):
        return jsonify({"error": "Unauthorized"}), 403

    if not target.exists() or not target.is_file():
        return jsonify({"error": "Document not found"}), 404

    with open(target, "r", encoding="utf-8") as f:
        content = f.read()
    return jsonify({"content": content})


@core_bp.route("/info", methods=["GET"])
def get_info():
    """Returns basic system info with dynamic provider detection."""
    from ..config import (
        ENABLE_DEMO,
        AGENT_API_URL,
        GOOGLE_API_KEY,
        ANTHROPIC_API_KEY,
        OPENAI_API_KEY,
    )

    agent = "Custom Endpoint"
    if GOOGLE_API_KEY:
        agent = "Gemini Pro (Active)"
    elif ANTHROPIC_API_KEY:
        agent = "Claude 3.5 (Active)"
    elif OPENAI_API_KEY:
        agent = "GPT-4o (Active)"

    from ..simulators import get_simulator_registry

    return jsonify(
        {
            "version": "v1.2.0-stable",
            "status": "active",
            "world_shims": len(get_simulator_registry()),
            "agent_endpoint": agent,
            "api_url": AGENT_API_URL,
            "enable_demo": ENABLE_DEMO,
            "uptime": datetime.now().isoformat(),
        }
    )


@core_bp.route("/scenarios/refresh", methods=["POST"])
def refresh_index():
    """Manually re-builds the scenario catalog index."""
    try:
        from ..catalog import ScenarioCatalog

        ScenarioCatalog().build_index()
        return jsonify({"status": "success", "message": "Index refreshed."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
