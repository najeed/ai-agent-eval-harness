import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from eval_runner import config
from eval_runner.catalog import ScenarioCatalog
from eval_runner.plugins import manager
from eval_runner.simulators import get_simulator_registry

from ..auth_manager import Permission, require_permission

logger = logging.getLogger(__name__)


class DebuggerStateStore:
    """Run-scoped, thread-safe store for the Visual Debugger timeline with historical fallback."""

    _run_states: dict[str, dict[str, Any]] = {}
    _latest_run_id: str | None = None
    _events: list[dict[str, Any]] = []
    _last_state: dict[str, Any] = {"message": "Waiting for evaluation..."}
    _lock = threading.Lock()

    @classmethod
    def reset(cls, run_id: str | None = None):
        with cls._lock:
            if run_id:
                cls._run_states.pop(run_id, None)
                if cls._latest_run_id == run_id:
                    cls._latest_run_id = next(iter(cls._run_states.keys()), None)
            else:
                cls._run_states = {}
                cls._latest_run_id = None
                cls._events = []
                cls._last_state = {"message": "Waiting for evaluation..."}

    @classmethod
    def post_event(cls, event_data: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
        flat_event = event_data.copy()
        if "data" in flat_event and isinstance(flat_event["data"], dict):
            flat_event.update(flat_event.pop("data"))

        effective_run_id = run_id or flat_event.get("run_id") or cls._latest_run_id or "default"

        with cls._lock:
            cls._latest_run_id = effective_run_id
            if effective_run_id not in cls._run_states:
                cls._run_states[effective_run_id] = {
                    "events": [],
                    "last_state": dict(cls._last_state),
                }

            run_record = cls._run_states[effective_run_id]
            run_record["events"].append(flat_event)
            if len(run_record["events"]) > 50:
                run_record["events"] = run_record["events"][-50:]

            cls._events.append(flat_event)
            if len(cls._events) > 50:
                cls._events = cls._events[-50:]

            if event_data.get("event") == "run_start":
                run_record["last_state"].update(event_data.get("data", {}))
                cls._last_state.update(event_data.get("data", {}))

            return run_record["last_state"]

    @classmethod
    def handle_event(cls, event: Any, run_id: str | None = None) -> dict[str, Any]:
        """Standard Forensic Event Handler (AgentV v2.0.0)."""
        if hasattr(event, "items"):
            name = event.get("event")
            data = event.get("data") or {
                k: v for k, v in event.items() if k not in ["event", "name", "timestamp"]
            }
            timestamp = event.get("timestamp")
            extracted_run_id = event.get("run_id") or (
                data.get("run_id") if isinstance(data, dict) else None
            )
        else:
            name = getattr(event, "name", None)
            data = getattr(event, "data", None)
            timestamp = getattr(event, "timestamp", None)
            extracted_run_id = getattr(event, "run_id", None) or (
                data.get("run_id") if isinstance(data, dict) else None
            )

        if not name and hasattr(event, "get"):
            name = event.get("status")

        effective_run_id = run_id or extracted_run_id or cls._latest_run_id or "default"

        with cls._lock:
            if effective_run_id not in cls._run_states:
                cls._run_states[effective_run_id] = {
                    "events": [],
                    "last_state": {"message": "Waiting for evaluation..."},
                }
            last_state = cls._run_states[effective_run_id]["last_state"]

            from eval_runner.events import CoreEvents

            if name == CoreEvents.TURN_START and isinstance(data, dict):
                last_state["current_agent"] = f"Agent {data.get('agent_name', 'Unknown')}"
            elif name == CoreEvents.TOOL_CALL and isinstance(data, dict):
                last_state["last_tool"] = data.get("tool")
            elif name == CoreEvents.RUN_END and isinstance(data, dict):
                last_state["message"] = f"Evaluation complete. Status: {data.get('status')}"
                r_id = data.get("run_id") or effective_run_id
                if r_id and str(r_id).startswith("run-loan"):
                    last_state["message"] += " (Industrial Demo Narrative)"
            elif name == "world_state_change" and isinstance(data, dict):
                last_state.update(data)
            elif name == "run_start" and isinstance(data, dict):
                last_state.update(data)

            # Keep global _last_state synchronized for backward-compatibility
            cls._last_state.update(last_state)

        return cls.post_event(
            {"event": name, "data": data, "timestamp": timestamp, "run_id": effective_run_id},
            run_id=effective_run_id,
        )

    @classmethod
    def get_state(cls, run_id: str | None = None) -> dict[str, Any]:
        with cls._lock:
            effective_run_id = run_id
            if effective_run_id and effective_run_id in cls._run_states:
                events = cls._run_states[effective_run_id]["events"]
                last_state = cls._run_states[effective_run_id]["last_state"]
            else:
                events = cls._events
                last_state = cls._last_state

            root_cause = next((e for e in events if e.get("is_root_cause")), None)
            if root_cause:
                idx = events.index(root_cause)
                root_cause_meta = {
                    "index": idx,
                    "reason": root_cause.get("reason", "Heuristic policy violation identified"),
                    "confidence": root_cause.get("confidence", 1.0),
                }
                return {
                    "summary": last_state,
                    "timeline": events,
                    "root_cause": root_cause_meta,
                    "run_id": effective_run_id,
                }

            return {"summary": last_state, "timeline": events, "run_id": effective_run_id}


system_bp = Blueprint("system", __name__)


@system_bp.route("/nav", methods=["GET"])
def get_nav():
    """Returns the consolidated navigation registry."""
    from flask import current_app

    return jsonify({"nav": current_app.config.get("NAV_REGISTRY", [])})


def _resolve_legacy_docs_dir() -> Path:
    d = config.PROJECT_ROOT / "docs-v1-deprecated-reference"
    if d.exists():
        return d
    return config.PROJECT_ROOT / "docs-old"


@system_bp.route("/docs", methods=["GET"])
@require_permission(Permission.DOCS_READ)
def list_docs():
    """Lists legacy documentation files with industrial categorization."""
    docs_dir = _resolve_legacy_docs_dir()
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

    docs_dir = _resolve_legacy_docs_dir().resolve()
    target = (docs_dir / filename).resolve()

    if not is_path_safe(target, docs_dir):
        return jsonify({"error": "Unauthorized Access"}), 403

    if not target.exists():
        if not filename.endswith(".md"):
            fallback_target = (docs_dir / f"{filename}.md").resolve()
            if fallback_target.exists():
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


def _runtime_health() -> dict[str, Any]:
    """
    [C2] Authoritative RuntimeHealth probe (shared by /status and /doctor).

    Performs REAL dependency checks — signing-key persistence, run-vault
    writability, scenario-catalog resolvability — and derives the overall
    status from their outcomes. Never returns an unconditional healthy.
    """
    from datetime import UTC, datetime

    version = config._get_project_version()
    mode = "demo" if getattr(config, "ENABLE_DEMO", False) else "production"

    dependencies: dict[str, str] = {}
    details: list[str] = []

    # Signing backend: ephemeral in-memory signer is NOT audit-grade.
    signing_backend = "ephemeral"
    if os.environ.get("EVAL_SIGNING_KEY") or getattr(config, "SIGNING_KEY", None):
        signing_backend = "persistent"
    else:
        details.append(
            "Signing key not configured (SIGNING_KEY/EVAL_SIGNING_KEY): runs are "
            "Executable/Verifiable but not Cryptographically Attested."
        )
    dependencies["signing"] = "HEALTHY" if signing_backend == "persistent" else "DEGRADED"

    # Run vault writability
    try:
        probe = Path(config.RUN_LOG_DIR) / ".health_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        dependencies["run_vault"] = "HEALTHY"
    except Exception as exc:  # noqa: BLE001
        dependencies["run_vault"] = "FAILED"
        details.append(f"Run vault not writable: {exc}")

    # Scenario catalog resolvable
    try:
        scenarios_root = Path(config.PROJECT_ROOT) / "scenarios"
        scenarios_root.mkdir(exist_ok=True)
        dependencies["scenario_catalog"] = "HEALTHY"
    except Exception as exc:  # noqa: BLE001
        dependencies["scenario_catalog"] = "FAILED"
        details.append(f"Scenario catalog unavailable: {exc}")

    failed = [k for k, v in dependencies.items() if v == "FAILED"]
    degraded = [k for k, v in dependencies.items() if v == "DEGRADED"]
    if failed:
        status = "UNREACHABLE"
    elif degraded:
        status = "DEGRADED"
    else:
        status = "HEALTHY"

    return {
        "status": status,
        "mode": mode,
        "version": version,
        "last_heartbeat": datetime.now(UTC).isoformat(),
        "dependencies": dependencies,
        "signing_backend": signing_backend,
        "details": details,
    }


@system_bp.route("/status", methods=["GET"])
def runtime_status():
    """
    Authoritative RuntimeHealth.

    The GUI header may render READY only when this object reports HEALTHY.
    Never derived client-side; never unconditional.
    """
    return jsonify(_runtime_health())


@system_bp.route("/v1/doctor", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def get_doctor_audit():
    """
    [C2] Environmental health audit derived from REAL RuntimeHealth probes.

    The status field reflects actual dependency outcomes (signing-key
    persistence, run-vault writability, catalog resolvability) and is never
    an unconditional 'healthy'. Legacy diagnostic fields are preserved.
    """
    try:
        health = _runtime_health()
        audit = {
            **health,
            "project_root": f"./{Path(config.PROJECT_ROOT).name}",
            "plugins_loaded": bool(getattr(manager, "_loaded", False)),
            "catalog_size": len(ScenarioCatalog.get_instance().scenarios),
            "simulator_count": len(get_simulator_registry()),
            "pid": os.getpid(),
        }
        return jsonify(audit)
    except Exception as e:
        return jsonify({"status": "UNREACHABLE", "error": str(e)}), 500


@system_bp.route("/debugger/state", methods=["GET", "POST"])
def debugger_state():
    """Visual Debugger ephemeral state sink/source."""
    import os
    import re

    from flask import session

    from eval_runner.utils import is_path_safe

    from ..auth_manager import Permission, get_auth_provider

    if os.getenv("AGENTV_TEST_AUTH_BYPASS") != "1":
        provider = get_auth_provider()
        user = session.get("user")
        if not user:
            auth_header = request.headers.get("Authorization", "")
            api_key = request.headers.get("X-AES-API-KEY") or request.headers.get("X-API-Key")
            if auth_header.startswith("Bearer "):
                user = provider.verify_token(auth_header[7:].strip())
            elif api_key:
                user = provider.authenticate(api_key.strip())

        required_perm = (
            Permission.DEBUG_EVENT if request.method == "POST" else Permission.DEBUG_READ
        )
        has_perm = user and (
            provider.has_permission(user, required_perm)
            or provider.has_permission(user, Permission.RUNS_WRITE)
            or provider.has_permission(user, Permission.RUNS_READ)
        )
        if not has_perm:
            return jsonify({"error": f"Unauthorized: {required_perm} permission required"}), 403

    if request.method == "POST":
        data = request.json or {}
        DebuggerStateStore.handle_event(data)
        return jsonify({"status": "updated"})

    run_id = request.args.get("run_id")
    if run_id:
        if not re.match(r"^[a-zA-Z0-9_\-]+$", str(run_id)):
            return jsonify({"error": "Invalid run_id format: must be alphanumeric"}), 400

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
                if not is_path_safe(trace_path, config.RUN_LOG_DIR):
                    return jsonify({"error": "Path traversal detected"}), 400
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
            # Rehydrate DebuggerStateStore with historical timeline for this specific run_id
            DebuggerStateStore.reset(run_id=run_id)
            for event in trace:
                DebuggerStateStore.handle_event(event, run_id=run_id)

            if run_id.startswith("run-loan"):
                state = DebuggerStateStore.get_state(run_id=run_id)
                state["summary"]["message"] = (
                    "Waiting for evaluation... (Industrial Demo Narrative)"
                )
                return jsonify({"data": state})

            return jsonify({"data": DebuggerStateStore.get_state(run_id=run_id)})

        msg = "Trace file not found"
        return jsonify({"error": msg, "message": msg}), 404

    return jsonify({"data": DebuggerStateStore.get_state()})


@system_bp.route("/ping", methods=["GET"])
def ping():
    """Public diagnostic check."""
    return jsonify({"status": "pong", "version": config._get_project_version(), "pid": os.getpid()})


@system_bp.route("/system/ollama-status", methods=["GET"])
def ollama_status():
    """
    Health check for the Ollama LLM runtime.
    Returns {available: bool, endpoint: str, models: list} - used by the Auto-Translate
    screen to gate the upload form and show available local models.
    """
    import urllib.request

    endpoint = getattr(config, "OLLAMA_BASE_URL", None) or os.environ.get(
        "OLLAMA_BASE_URL", "http://localhost:11434"
    )

    available = False
    models = []

    try:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            req = urllib.request.Request(f"{endpoint}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:  # nosec B310
                if resp.status == 200:
                    available = True
                    import json

                    try:
                        resp_data = json.loads(resp.read().decode("utf-8"))
                        models = [
                            m.get("name") for m in resp_data.get("models", []) if m.get("name")
                        ]
                    except Exception as e:
                        logger.debug(f"Ollama models parse error: {e}")
    except Exception as e:
        logger.debug(f"Ollama connection error: {e}")

    return jsonify({"available": available, "endpoint": endpoint, "models": models})
