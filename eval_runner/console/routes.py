from flask import Blueprint, jsonify, request
import os
from pathlib import Path
import json
import subprocess
import shlex
from datetime import datetime
from .. import config

from functools import wraps

core_bp = Blueprint("core", __name__, url_prefix="/api")

def require_api_key(f):
    """Decorator to enforce X-AES-API-KEY authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("X-AES-API-KEY")
        # In development/demo mode, a missing key might be allowed if explicitly configured,
        # but here we enforce strict compliance as per Phase 3 rules.
        if not config.DASHBOARD_API_KEY:
             # If no key is configured in env, we allow it ONLY if in explicit insecure mode
             # (not implemented yet, defaulting to block for safety)
             return jsonify({"error": "Unauthorized: No secure API key configured on server."}), 501
        
        if api_key != config.DASHBOARD_API_KEY:
            return jsonify({"error": "Unauthorized: Invalid or missing API Key"}), 401
        return f(*args, **kwargs)
    return decorated_function

@core_bp.route("/demo/loan/context", methods=["GET"])
@require_api_key
def get_loan_demo_context():
    """Retrieve dynamic context files for the Loan Approval Demo."""
    demo_dir = config.PROJECT_ROOT / "sample_agent" / "loan_agent_demo"
    
    prd_path = demo_dir / "loan_prd.md"
    aes_path = demo_dir / "loan_approval.aes.yaml"
    scenario_path = demo_dir / "loan_approval_scenario.json"
    
    context = {
        "prd": prd_path.read_text(encoding="utf-8") if prd_path.exists() else "# PRD missing",
        "aes": aes_path.read_text(encoding="utf-8") if aes_path.exists() else "# AES missing",
        "scenario": scenario_path.read_text(encoding="utf-8") if scenario_path.exists() else "{}",
        "updated_at": datetime.now().isoformat()
    }
    return jsonify(context)

@core_bp.route("/demo/execute", methods=["POST"])
@require_api_key
def execute_demo_command():
    """Execute a CLI command for the demo and return results."""
    data = request.json or {}
    cmd = data.get("command")
    if not cmd:
        return jsonify({"error": "Missing command"}), 400
    
    # Simple whitelist for demo safety
    allowed_prefixes = ["multiagent-eval spec-to-eval", "multiagent-eval evaluate", "multiagent-eval triage", "python ", "copy ", "cp ", "type ", "cat ", "type", "cat"]
    allowed_files = ["loan_agent.py", "loan_agent_fixed.py", "loan_approval.aes.yaml", "loan_prd.md", "loan_approval_scenario.json"]
    
    # Secure Remediation (R2.1): Robust Path Traversal Protection
    def is_path_safe(target_str, base_dir):
        try:
            target = Path(target_str).resolve()
            base = Path(base_dir).resolve()
            return base in target.parents or target == base
        except Exception:
            return False

    demo_dir = Path(__file__).parent.parent.parent / "sample_agent" / "loan_agent_demo"
    
    # Check prefixes
    if not any(cmd.lower().startswith(a.lower()) for a in allowed_prefixes):
         return jsonify({"error": f"Command not allowed: {cmd}"}), 403
    
    # Secure Validation of paths
    parts = cmd.split()
    for part in parts:
        if "/" in part or "\\" in part or "." in part:
             # If it looks like a path, resolve and check jail
             if not is_path_safe(part, demo_dir) and not any(f.lower() in part.lower() for f in allowed_files):
                  return jsonify({"error": f"Security: Access outside demo jail denied: {part}"}), 403

    try:
        # Secure Remediation (R0.1): Eliminate shell=True RCE
        cmd_args = shlex.split(cmd)
        result = subprocess.run(cmd_args, shell=False, capture_output=True, text=True, timeout=60)
        return jsonify({
            "status": "success" if result.returncode == 0 else "error",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "code": result.returncode
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
        items.extend([
            {
                "id": "demo",
                "title": "Demo: Risk Check",
                "path": "/demo",
                "icon": "shield-check",
                "type": "internal",
            },
            {
                "id": "loan_demo",
                "title": "Demo: Loan Approval",
                "path": "/demo/loan",
                "icon": "play",
                "type": "internal",
            }
        ])

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


@core_bp.route("/scenarios", methods=["GET"])
@require_api_key
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
@require_api_key
def list_runs():
    """Returns a list of recent run traces."""
    query = request.args.get("q", "").lower()
    runs = []
    run_log = config.RUN_LOG_DIR / "run.jsonl"
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
    # Add static demo traces to the list for visibility/quick-access
    from .demo_traces import DEMO_IDS
    for d_id in DEMO_IDS:
        scenario_name = d_id.replace("run-", "").replace("-", " ").title()
        # Filter demo traces by query as well
        if query and query not in d_id.lower() and query not in scenario_name.lower():
            continue

        runs.append({
            "run_id": d_id,
            "scenario": scenario_name,
            "timestamp": datetime.now().isoformat(),
            "is_demo": True
        })

    # Reverse to show newest first
    runs.reverse()
    return jsonify({"runs": runs[:100]})


@core_bp.route("/evaluate", methods=["POST"])
@require_api_key
def evaluate_scenario():
    """Trigger an evaluation in the background."""
    data = request.json or {}
    path_str = data.get("path")
    if not path_str:
        return jsonify({"error": "Missing 'path' parameter"}), 400

    path = Path(path_str)
    if not path.exists():
        # Try relative to root?
        path = config.PROJECT_ROOT / path_str
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
                "scenario_id": scenario_data.get("scenario_id") or scenario_data.get("metadata", {}).get("id"),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@core_bp.route("/scenarios", methods=["POST"])
@require_api_key
def save_scenario():
    """Saves or updates a scenario JSON file."""
    data = request.json or {}
    metadata_block = data.get("metadata", {})
    scenario_id = data.get("scenario_id") or metadata_block.get("id")
    if not scenario_id:
        return jsonify({"error": "Missing scenario_id"}), 400

    # Secure path resolution (prevent traversal)
    safe_id = "".join(c for c in scenario_id if c.isalnum() or c in ("-", "_")).strip()
    if not safe_id:
        return jsonify({"error": "Invalid scenario_id"}), 400

    industry = data.get("industry", "generic")
    # Secure Remediation (R2.2): Sanitize industry path to prevent traversal
    safe_industry = "".join(c for c in industry if c.isalnum() or c in ("-", "_")).strip()
    if not safe_industry:
        safe_industry = "generic"

    output_dir = config.PROJECT_ROOT / "industries" / safe_industry / "scenarios"
    
    # Final jail check
    if not str(output_dir.resolve()).startswith(str((config.PROJECT_ROOT / "industries").resolve())):
        return jsonify({"error": "Security: Invalid industry path"}), 403

    output_dir.mkdir(parents=True, exist_ok=True)

    file_path = output_dir / f"{safe_id}.json"

    # Structure the AES JSON (v1.2 compliant)
    scenario_obj = {
        "aes_version": 1.2,
        "metadata": {
            "id": safe_id,
            "name": data.get("title") or metadata_block.get("name") or "Untitled Scenario",
            "compliance_level": metadata_block.get("compliance_level", "Standard"),
            "industry": industry,
            "tags": metadata_block.get("tags") or data.get("tags", []),
            "created_at": datetime.now().isoformat(),
        },
        "description": data.get("description", ""),
        "industry": industry,
        "workflow": data.get("workflow") or {
            "nodes": [
                {
                    "id": t.get("task_id") or f"node_{i}",
                    "task_description": t.get("description"),
                    "expected_outcome": {
                        "type": "typed_value",
                        "data_type": "object",
                        "value": t.get("expected_outcome")
                    }
                } for i, t in enumerate(data.get("tasks", []))
            ],
            "edges": [] # Simple linear edges could be inferred but we keep it clean
        }
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
    def reset(cls):
        """Reset state for testing stabilization."""
        cls._last_state = {"message": "Waiting for evaluation..."}
        cls._events = []
        cls._is_active = False

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
_debugger_subscribed = False

def subscribe_debugger():
    global _debugger_subscribed
    if not _debugger_subscribed:
        from ..events import EventEmitter
        EventEmitter.subscribe(DebuggerStateStore.handle_event)
        _debugger_subscribed = True


@core_bp.route("/ping")
def ping():
    return jsonify(
        {
            "status": "pong",
            "version": "v1.6-verified"
        }
    )


@core_bp.route("/debugger/state", methods=["GET", "POST"])
@require_api_key
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
        runs_dir = config.RUN_LOG_DIR
        demo_dir = runs_dir / "demo"

        # 1. Try standard locations
        paths_to_check = [runs_dir / f"{run_id}.jsonl", demo_dir / f"{run_id}.jsonl"]

        trace_file = next((p for p in paths_to_check if p.exists()), None)

        # 2. Dynamic generation for demo IDs if not found on disk
        from .demo_traces import DEMO_IDS, get_demo_trace

        if not trace_file and run_id in DEMO_IDS:
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
        if run_id.startswith("run-loan-") or run_id.startswith("run-alice-"):
            summary["message"] = f"Demo Narrative: {run_id.replace('-', ' ').title()}"
            if "fail" in run_id:
                summary["message"] = f"Demo Narrative: {run_id.split('-')[2].title()} Failure Analysis"
            elif "pass" in run_id:
                summary["message"] = f"Demo Narrative: {run_id.split('-')[2].title()} Verification (Success)"

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
    base = config.PROJECT_ROOT / "docs"

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
@require_api_key
def read_doc(doc_path):
    """Read a specific documentation markdown file."""
    base = config.PROJECT_ROOT / "docs"
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
    """Returns basic system info with multi-agent detection."""
    from ..config import (
        ENABLE_DEMO,
        AGENT_API_URLS,
        GOOGLE_API_KEY,
        ANTHROPIC_API_KEY,
        OPENAI_API_KEY,
    )

    agents = []
    for url in AGENT_API_URLS:
        label = "Custom Endpoint"
        provider = "custom"
        
        if GOOGLE_API_KEY and ("google" in url or "gemini" in url or "localhost" in url):
            label = "Gemini Pro (Cloud)"
            provider = "google"
        elif ANTHROPIC_API_KEY and "anthropic" in url:
            label = "Claude 3.5 (Cloud)"
            provider = "anthropic"
        elif OPENAI_API_KEY and "openai" in url:
            label = "GPT-4o (Cloud)"
            provider = "openai"
        elif "localhost:11434" in url:
            label = "Ollama (Local)"
            provider = "ollama"
        elif "localhost:5001" in url:
            label = "Default Dev Agent (Local)"
            provider = "local"
        elif "localhost" in url:
            label = "Local Host Agent"
            provider = "local"
            
        agents.append({"label": label, "url": url, "provider": provider})

    from ..simulators import get_simulator_registry

    # Legacy compatibility fields
    primary_agent = agents[0] if agents else {"label": "None", "url": "", "provider": "none"}

    return jsonify(
        {
            "version": "v1.2.0-stable",
            "status": "active",
            "world_shims": len(get_simulator_registry()),
            "agent_endpoint": primary_agent["label"],
            "api_url": primary_agent["url"],
            "agents": agents,
            "agent_count": len(agents),
            "enable_demo": ENABLE_DEMO,
            "uptime": datetime.now().isoformat(),
        }
    )


@core_bp.route("/scenarios/refresh", methods=["POST"])
@require_api_key
def refresh_index():
    """Manually re-builds the scenario catalog index."""
    try:
        from ..catalog import ScenarioCatalog

        ScenarioCatalog().build_index()
        return jsonify({"status": "success", "message": "Index refreshed."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
