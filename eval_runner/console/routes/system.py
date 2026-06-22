import json
import logging
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

from eval_runner import config
from eval_runner.catalog import ScenarioCatalog
from eval_runner.plugins import manager
from eval_runner.simulators import get_simulator_registry

from ..auth_manager import Permission, require_permission

logger = logging.getLogger(__name__)


class DebuggerStateStore:
    """Ephemeral, in-memory store for the Visual Debugger timeline."""

    _events = []
    _last_state = {"message": "Waiting for evaluation..."}

    @classmethod
    def reset(cls):
        cls._events = []
        cls._last_state = {"message": "Waiting for evaluation..."}

    @classmethod
    def post_event(cls, event_data):
        # Industrial Parity: Flatten 'data' into the main event object
        flat_event = event_data.copy()
        if "data" in flat_event and isinstance(flat_event["data"], dict):
            flat_event.update(flat_event.pop("data"))

        cls._events.append(flat_event)
        if len(cls._events) > 50:
            cls._events = cls._events[-50:]

        if event_data.get("event") == "run_start":
            cls._last_state.update(event_data.get("data", {}))
        return cls._last_state

    @classmethod
    def handle_event(cls, event):
        """Standard Forensic Event Handler (AgentV v1.6.0)."""
        # Unwrap object if necessary (for MockEvent compatibility in tests)
        if hasattr(event, "items"):
            name = event.get("event")
            data = event.get("data") or {
                k: v for k, v in event.items() if k not in ["event", "name", "timestamp"]
            }
            timestamp = event.get("timestamp")
        else:
            name = getattr(event, "name", None)
            data = getattr(event, "data", None)
            timestamp = getattr(event, "timestamp", None)

        # Guard: In case event was just a task status or similar
        if not name and hasattr(event, "get"):
            name = event.get("status")

        # Map turning points to last_state
        from eval_runner.events import CoreEvents

        if name == CoreEvents.TURN_START:
            cls._last_state["current_agent"] = f"Agent {data.get('agent_name', 'Unknown')}"
        elif name == CoreEvents.TOOL_CALL:
            cls._last_state["last_tool"] = data.get("tool")
        elif name == CoreEvents.RUN_END:
            cls._last_state["message"] = f"Evaluation complete. Status: {data.get('status')}"
            run_id = data.get("run_id")
            if run_id and run_id.startswith("run-loan"):
                cls._last_state["message"] += " (Industrial Demo Narrative)"
        elif name == "world_state_change":
            cls._last_state.update(data)
        elif name == "run_start":
            cls._last_state.update(data if data else {})

        return cls.post_event({"event": name, "data": data, "timestamp": timestamp})

    @classmethod
    def get_state(cls):
        # Industrial Search: Find explicit root cause in timeline
        root_cause = next((e for e in cls._events if e.get("is_root_cause")), None)
        if root_cause:
            # Add metadata for the UI 'Isolate Root Cause' feature
            idx = cls._events.index(root_cause)
            root_cause_meta = {
                "index": idx,
                "reason": root_cause.get("reason", "Heuristic policy violation identified"),
                "confidence": root_cause.get("confidence", 1.0),
            }
            return {
                "summary": cls._last_state,
                "timeline": cls._events,
                "root_cause": root_cause_meta,
            }

        return {"summary": cls._last_state, "timeline": cls._events}


system_bp = Blueprint("system", __name__)


@system_bp.route("/nav", methods=["GET"])
def get_nav():
    """Returns the consolidated navigation registry."""
    from flask import current_app

    return jsonify({"nav": current_app.config.get("NAV_REGISTRY", [])})


@system_bp.route("/docs", methods=["GET"])
@require_permission(Permission.DOCS_READ)
def list_docs():
    """Lists legacy documentation files with industrial categorization."""
    docs_dir = config.PROJECT_ROOT / "docs-old"
    docs = []
    seen_ids = set()
    if docs_dir.exists():
        for p in docs_dir.rglob("*.md"):
            if ".github" in p.parts:
                continue
            doc_id = p.stem
            if doc_id in seen_ids:
                continue

            rel_path = str(p.relative_to(docs_dir)).replace("\\", "/")

            # Map folder names or filename patterns to AEH Official Categories
            category = "General"
            parent_name = p.parent.name.lower()
            stem_lower = p.stem.lower()

            if "guide" in parent_name or "guide" in stem_lower:
                category = "Guide"
            elif (
                "api" in parent_name
                or "reference" in parent_name
                or "api" in stem_lower
                or "reference" in stem_lower
            ):
                category = "API Reference"
            elif "tutorial" in parent_name:
                category = "Tutorial"

            docs.append({"id": doc_id, "path": rel_path, "category": category})
            seen_ids.add(doc_id)
    return jsonify({"docs": docs})


@system_bp.route("/docs/<path:filename>", methods=["GET"])
@require_permission(Permission.DOCS_READ)
def read_doc(filename):
    """Reads a legacy documentation file (with traversal protection)."""
    from eval_runner.utils import is_path_safe

    docs_dir = (config.PROJECT_ROOT / "docs-old").resolve()
    target = (docs_dir / filename).resolve()

    if not is_path_safe(target, docs_dir):
        return jsonify({"error": "Unauthorized Access"}), 403

    if not target.exists():
        if not filename.endswith(".md"):
            fallback_target = (docs_dir / f"{filename}.md").resolve()
            if is_path_safe(fallback_target, docs_dir) and fallback_target.exists():
                target = fallback_target

    if not target.exists():
        return jsonify({"error": "Not Found"}), 404

    with open(target, encoding="utf-8") as f:
        return jsonify({"id": target.stem, "content": f.read()})


core_bp = system_bp  # Legacy Alias for Tests


@system_bp.before_app_request
def security_intercept_blueprint():
    """Intercepts traversal attempts before normalization or routing."""
    from urllib.parse import unquote

    raw_uri = request.environ.get("REQUEST_URI", "").lower()
    path_info = request.environ.get("PATH_INFO", "").lower()
    path = request.path.lower()
    full_path = request.full_path.lower()
    url = request.url.lower()
    targets = [raw_uri, path_info, path, full_path, url, unquote(raw_uri), unquote(path)]
    if any(".." in t or "%2e" in t for t in targets):
        return jsonify(
            {"error": "Security: Unauthorized Path Traversal Attempt Detected", "status": 403}
        ), 403


@system_bp.route("/info", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def get_system_info():
    """Returns system metadata and configuration status (Authoritative Consolidated)."""
    manager.load_plugins()
    catalog = ScenarioCatalog.get_instance()
    catalog.check_for_updates(force=False)
    if not catalog.scenarios:
        catalog.load_index()

    agent_endpoint = "Local (Simulator)"
    legacy_provider = "local"
    if config.GOOGLE_API_KEY:
        agent_endpoint = "Gemini (Google)"
        legacy_provider = "google"
    elif config.ANTHROPIC_API_KEY:
        agent_endpoint = "Claude (Anthropic)"
        legacy_provider = "anthropic"
    elif config.OPENAI_API_KEY:
        agent_endpoint = "GPT (OpenAI)"
        legacy_provider = "openai"
    elif any("11434" in str(url) for url in config.AGENT_API_URLS):
        agent_endpoint = "Llama (Ollama)"
        legacy_provider = "ollama"

    all_plugins = manager.plugins
    adapters = [p for p in all_plugins if "Adapter" in p.__class__.__name__]
    utilities = [p for p in all_plugins if p not in adapters]
    agent_info = [
        {"label": p.__class__.__name__, "provider": getattr(p, "provider", legacy_provider)}
        for p in all_plugins
    ]
    shims_count = len(get_simulator_registry())
    last_indexed = getattr(catalog, "manifest", {}).get("updated_at", "unknown")

    def mask_path(path_val):
        try:
            p = Path(path_val).resolve()
            root = Path(config.PROJECT_ROOT).resolve()
            if p.is_relative_to(root) or str(p).lower().startswith(str(root).lower()):
                try:
                    rel_path = os.path.relpath(p, root)
                    return f"./{Path(rel_path).as_posix()}"
                except ValueError:
                    rel_part = str(p)[len(str(root)) :].lstrip("\\/")
                    return f"./{Path(rel_part).as_posix()}"
            return Path(p.name).as_posix()
        except Exception:
            return "hidden"

    return jsonify(
        {
            "status": "active",
            "version": config._get_project_version(),
            "agent_count": len(all_plugins),
            "adapter_count": len(adapters),
            "utility_count": len(utilities),
            "agents": agent_info,
            "world_shims": shims_count,
            "agent_endpoint": agent_endpoint,
            "enable_demo": config.ENABLE_DEMO,
            "runs_dir": mask_path(config.RUN_LOG_DIR),
            "trajectories_dir": mask_path(config.TRAJECTORIES_DIR),
            "scenario_count": len(catalog.scenarios),
            "last_indexed_at": last_indexed,
            "debug_mode": config.DEBUG_MODE,
        }
    )


@system_bp.route("/cleanup-runs", methods=["POST"])
@require_permission(Permission.DEMO_EXECUTE)
def cleanup_runs():
    """Industrial-grade log cleanup (v1.2.3)"""
    try:
        count = 0
        if config.RUN_LOG_DIR.exists():
            for item in config.RUN_LOG_DIR.iterdir():
                if item.is_dir():
                    import shutil

                    shutil.rmtree(item)
                    count += 1
                elif item.is_file() and item.suffix in (".jsonl", ".json"):
                    item.unlink()
                    count += 1

        # Trigger plugin hooks for cleanup
        from eval_runner.plugins import manager

        for plugin in manager.plugins:
            method = getattr(plugin, "on_cleanup_runs", None)
            if method and callable(method):
                try:
                    method()
                except Exception as pe:
                    logger.warning(f"Plugin cleanup failed for {plugin.__class__.__name__}: {pe}")

        return jsonify(
            {"status": "success", "message": f"Pruned {count} historical traces.", "count": count}
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@system_bp.route("/v1/doctor", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def get_doctor_audit():
    """Roadmap: Environmental health check (AgentV v1.6.0)."""
    try:
        # Perform basic health checks (Sync wrapper for potential async logic)
        audit = {
            "status": "healthy",
            "project_root": str(config.PROJECT_ROOT),
            "plugins_loaded": manager._loaded,
            "catalog_size": len(ScenarioCatalog.get_instance().scenarios),
            "simulator_count": len(get_simulator_registry()),
            "pid": os.getpid(),
        }
        return jsonify(audit)
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


@system_bp.route("/debugger/state", methods=["GET", "POST"])
def debugger_state():
    """Visual Debugger ephemeral state sink/source."""
    if request.method == "POST":
        data = request.json or {}
        DebuggerStateStore.handle_event(data)
        return jsonify({"status": "updated"})

    run_id = request.args.get("run_id")
    if run_id:
        # Load historical trace if it exists
        from ..demo_traces import get_demo_trace

        trace = get_demo_trace(run_id)
        if not trace:
            # Check physical storage
            trace_path = config.RUN_LOG_DIR / run_id / "run.jsonl"
            if not trace_path.exists():
                # Try direct run_id.jsonl
                trace_path = config.RUN_LOG_DIR / f"{run_id}.jsonl"

            if not trace_path.exists():
                # Recursive glob fallback for nested subdirectories (e.g. runs/demo/)
                matches = list(config.RUN_LOG_DIR.glob(f"**/{run_id}/run.jsonl")) + list(
                    config.RUN_LOG_DIR.glob(f"**/{run_id}.jsonl")
                )
                if matches:
                    trace_path = matches[0]

            if trace_path.exists():
                try:
                    trace = []
                    with open(trace_path, encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                trace.append(json.loads(line))
                except Exception as e:
                    logger.error(f"Failed to parse historical trace {run_id}: {e}")
                    msg = "Failed to parse trace file"
                    return jsonify({"error": msg, "message": msg}), 500

        if trace:
            # Rehydrate DebuggerStateStore with historical timeline
            DebuggerStateStore.reset()
            if run_id.startswith("run-loan"):
                DebuggerStateStore._last_state["message"] = (
                    "Waiting for evaluation... (Industrial Demo Narrative)"
                )

            for event in trace:
                DebuggerStateStore.handle_event(event)

            return jsonify({"data": DebuggerStateStore.get_state()})
        msg = "Trace file not found"
        return jsonify({"error": msg, "message": msg}), 404

    return jsonify({"data": DebuggerStateStore.get_state()})


@system_bp.route("/ping", methods=["GET"])
def ping():
    """Public diagnostic check."""
    return jsonify({"status": "pong", "version": config._get_project_version(), "pid": os.getpid()})
