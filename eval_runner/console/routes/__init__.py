from flask import Blueprint, jsonify, request

from eval_runner import config as config
from eval_runner.catalog import ScenarioCatalog as ScenarioCatalog

from .demo import demo_bp as demo_bp
from .demo import execute_demo_command, get_loan_demo_context
from .runs import get_verification_certificate, list_metrics, list_runs
from .runs import run_bp as run_bp
from .scenarios import get_taxonomy, list_scenarios, refresh_index, save_scenario
from .scenarios import scenario_bp as scenario_bp
from .system import (
    DebuggerStateStore as DebuggerStateStore,
)
from .system import (
    cleanup_runs,
    debugger_state,
    get_doctor_audit,
    get_nav,
    get_system_info,
    list_docs,
    ping,
    read_doc,
)
from .system import (
    system_bp as system_bp,
)
from .trust import get_identity_public_key, verify_run_public
from .trust import trust_bp as trust_bp

# Master Blueprint for Legacy Parity (Used by tests)
core_bp = Blueprint("core", __name__)


@core_bp.before_app_request
def security_intercept_core_blueprint():
    """Intercepts traversal attempts for the master core blueprint (Test Parity)."""
    from urllib.parse import unquote

    from flask import request

    raw_uri = request.environ.get("REQUEST_URI", "").lower()
    path = request.path.lower()
    if any(".." in t or "%2e" in t for t in [raw_uri, path, unquote(raw_uri), unquote(path)]):
        return jsonify(
            {"error": "Security: Unauthorized Path Traversal Attempt Detected", "status": 403}
        ), 403


def register_core_routes(app, nav_registry):
    """Consolidated Navigation Registry for the AgentV Console."""
    from eval_runner.config import ENABLE_DEMO

    items = [
        {"id": "dashboard", "title": "Dashboard", "path": "/", "icon": "home", "type": "internal"},
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
        items.extend(
            [
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
                },
            ]
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


def subscribe_debugger():
    """Initializes event subscription for the Visual Debugger."""
    from eval_runner import events

    from .system import DebuggerStateStore

    # [Industrial Hardening] Connect the event bus to the ephemeral state store
    events.subscribe(DebuggerStateStore.handle_event)
    print("      [Console] Visual Debugger subscribed to event bus.")


# PROXY ROUTES FOR CORE_BP (Bypasses prefixing requirements in legacy tests)
@core_bp.route("/api/info")
def proxy_info():
    return get_system_info()


@core_bp.route("/api/nav")
def proxy_nav():
    return get_nav()


@core_bp.route("/api/docs")
def proxy_list_docs():
    return list_docs()


@core_bp.route("/api/docs/<path:filename>")
def proxy_read_doc(filename):
    return read_doc(filename)


@core_bp.route("/api/cleanup-runs", methods=["POST"])
def proxy_cleanup():
    return cleanup_runs()


@core_bp.route("/api/debugger/state", methods=["GET", "POST"])
def proxy_debugger():
    return debugger_state()


@core_bp.route("/api/scenarios", methods=["GET", "POST"])
def proxy_scenarios():
    if request.method == "POST":
        return save_scenario()
    return list_scenarios()


@core_bp.route("/api/v1/doctor")
def proxy_doctor():
    return get_doctor_audit()


@core_bp.route("/api/runs")
def proxy_runs():
    return list_runs()


@core_bp.route("/api/demo/loan/context")
def proxy_demo_context():
    return get_loan_demo_context()


@core_bp.route("/api/demo/execute", methods=["POST"])
def proxy_demo_execute():
    return execute_demo_command()


@core_bp.route("/api/ping")
def proxy_ping():
    return ping()


@core_bp.route("/api/scenarios/refresh", methods=["POST"])
def proxy_refresh():
    return refresh_index()


# --- PUBLIC /v1 SHIMS (Unprotected Root Namespace) ---
@core_bp.route("/v1/doctor")
def shim_doctor():
    """Unprefixed root shim for Industrial Doctor (AgentV v1.5.0 parity)."""
    return get_doctor_audit()


@core_bp.route("/v1/taxonomy")
def shim_taxonomy():
    """Unprefixed root shim for Industrial Taxonomy."""
    return get_taxonomy()


@core_bp.route("/v1/metrics")
def shim_metrics():
    """Unprefixed root shim for Metric Discovery."""
    return list_metrics()


@core_bp.route("/v1/certificates/<run_id>")
def shim_cert(run_id):
    return get_verification_certificate(run_id)


@core_bp.route("/v1/verify/<run_id>")
def shim_verify(run_id):
    return verify_run_public(run_id)


@core_bp.route("/v1/identity/<identity_id>/public_key")
def shim_pubkey(identity_id):
    return get_identity_public_key(identity_id)
