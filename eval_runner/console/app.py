import hashlib
import os

import flask
from dotenv import load_dotenv
from flask import Flask, send_from_directory
from flask_cors import CORS

from eval_runner.plugins import manager

from .. import config
from .auth import auth_bp
from .routes import (
    core_bp,
    demo_bp,
    register_core_routes,
    run_bp,
    scenario_bp,
    subscribe_debugger,
    system_bp,
    trust_bp,
)

# Ensure environment variables are loaded before ANY other configuration usage (R6)
load_dotenv()

print(
    f"--- Flask App Initializing (DASHBOARD_API_KEY: {config.DASHBOARD_API_KEY[:4] if config.DASHBOARD_API_KEY else 'None'})",  # noqa: E501
    flush=True,
)


def create_app():
    # Eager Hydration: Ensure scenarios are loaded before the first request
    from eval_runner.catalog import ScenarioCatalog

    # [STARTUP ACCELERATION]: Bypass heavy indexing for Trust Portal Stability
    if not config.ENABLE_DEMO:
        ScenarioCatalog.get_instance().load_index()
    else:
        print("   [Industrial Start] Lazy Catalog active for Demo Stability.", flush=True)

    # Set static_folder using the project root for absolute reliability
    ui_path = os.path.abspath(config.PROJECT_ROOT / "ui" / "visual-debugger")
    app = Flask(__name__, static_folder=ui_path, static_url_path="/static")

    # Ensure session persistence (v1.2.3 Stabilization)
    api_key = getattr(config, "DASHBOARD_API_KEY", None)
    if api_key:
        app.secret_key = hashlib.sha256(api_key.encode()).hexdigest()
    else:
        # Fallback to a random key if no API key is provided, allowing the app to boot
        app.secret_key = os.urandom(24).hex()

    CORS(app, supports_credentials=True)  # Explicit support for session cookies
    app.register_blueprint(auth_bp)
    app.register_blueprint(system_bp, url_prefix="/api")
    app.register_blueprint(scenario_bp, url_prefix="/api")
    app.register_blueprint(run_bp, url_prefix="/api")
    app.register_blueprint(trust_bp)
    app.register_blueprint(demo_bp)
    app.register_blueprint(core_bp)
    # Mount critical diagnostic shims directly into the Root /v1 namespace
    # to align with documentation.

    @app.before_request
    def trace_request():
        import sys

        sys.stderr.write(
            f"   [Trace] {flask.request.method} {flask.request.path} "
            f"(Endpoint: {flask.request.endpoint})\n"
        )
        sys.stderr.flush()

    @app.after_request
    def trace_response(response):
        import sys

        sys.stderr.write(f"   [Trace] Status: {response.status_code}\n")
        sys.stderr.flush()
        return response

    # Hardened API Error Handlers (Prevents "Unexpected token <" regressions)
    @app.errorhandler(405)
    def handle_405(e):
        import sys

        sys.stderr.write(
            f"   [API] 405 Method Not Allowed - URL: {flask.request.url}, "
            f"Method: {flask.request.method}\n"
        )
        sys.stderr.write(
            f"   [API] 405 DEBUG - Rule: {flask.request.url_rule}, "
            f"Args: {flask.request.view_args}\n"
        )
        sys.stderr.flush()
        return flask.jsonify(
            {
                "error": "Method Not Allowed: This endpoint does not accept the requested HTTP method.",  # noqa: E501
                "status": 405,
            }
        ), 405

    # Hardened Route Precedence (AgentV v1.5.0 Sync)
    # Industrial Standard: Use blueprint-first registration only.

    # Load external hooks for zero-touch discovery
    manager.load_plugins()

    # Core navigation registry
    nav_registry = []

    # Register core routes
    register_core_routes(app, nav_registry)

    # Safely initialize debugger event subscription

    subscribe_debugger()

    # Trigger plugin hook to register additional routes and nav items
    for plugin in manager.plugins:
        method = getattr(plugin, "on_register_console_routes", None)
        if method and callable(method):
            try:
                method(app, nav_registry)
            except Exception as e:
                print(
                    f"   [Console] Warning: Route registration failed for "
                    f"{plugin.__class__.__name__}: {e}"
                )

    # Re-assert core paths and industrial components to prevent plugin overrides
    core_overrides = {
        "community": {"path": "https://github.com/najeed/ai-agent-eval-harness"},
        "demo": {"path": "/demo"},
        "loan_demo": {"path": "/demo/loan"},
    }
    for item in nav_registry:
        if item.get("id") in core_overrides:
            item.update(core_overrides[item.get("id")])

    # Endpoint to serve the unified navigation menu (API Priority)
    app.config["NAV_REGISTRY"] = nav_registry

    # Industrial Diagnostic: Audit the physical route map (v1.4.1 Hardening)
    print("\n--- Industrial Route Map Audit ---", flush=True)
    for rule in app.url_map.iter_rules():
        print(f"   [Route] {rule.rule} ({rule.endpoint})", flush=True)
    print("--- Audit Complete ---\n", flush=True)

    # Frontend Catch-all Routes (Define LAST to prevent API masking)
    @app.route("/", defaults={"path": ""})
    @app.route("/scenarios")
    @app.route("/reports")
    @app.route("/editor")
    @app.route("/debugger")
    @app.route("/demo")
    @app.route("/demo/loan")
    @app.route("/docs")
    @app.route("/docs/api")
    def index(path=""):
        print(f"DEBUG: SPA Navigation - Obtaining industrial route: {flask.request.path}")
        return send_from_directory(app.static_folder, "index.html")

    return app


def manage_pid_file():
    """
    Singleton Process Guard (Leak Prevention).
    Ensures only one instance of the Console API is running.
    """
    import os
    import sys

    import psutil

    pid_path = config.PROJECT_ROOT / ".aes" / "server.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    if pid_path.exists():
        try:
            with open(pid_path) as f:
                old_pid_str = f.read().strip()
                if old_pid_str:
                    old_pid = int(old_pid_str)
                    if psutil.pid_exists(old_pid):
                        proc = psutil.Process(old_pid)
                        # Only kill if it's actually similar to us (python/app)
                        if "python" in proc.name().lower():
                            sys.stderr.write(
                                f"   [Guard] Found stale instance (PID: {old_pid}). "
                                "Terminating...\n"
                            )
                            proc.terminate()
                            try:
                                proc.wait(timeout=5)
                            except psutil.TimeoutExpired:
                                proc.kill()
        except Exception as e:
            sys.stderr.write(f"   [Guard] PID cleanup warning: {e}\n")

    # Register current PID
    with open(pid_path, "w") as f:
        f.write(str(os.getpid()))

    # Cleanup on exit
    import atexit

    def cleanup_pid():
        if pid_path.exists():
            try:
                # Only remove if it's OUR pid
                with open(pid_path) as check_f:
                    if check_f.read().strip() == str(os.getpid()):
                        pid_path.unlink()
            except Exception as e:
                import sys

                sys.stderr.write(f"   [Guard] PID cleanup failed: {e}\n")
                sys.stderr.flush()

    atexit.register(cleanup_pid)


def run_server(host="127.0.0.1", port=5000, debug=False):
    """Entry point for the AES Console Server."""
    manage_pid_file()

    app = create_app()
    # Increase interval to 2s to avoid over-eager site-packages reloads
    app.run(
        host=host, port=port, debug=debug, use_reloader=debug, reloader_interval=2, threaded=True
    )


if __name__ == "__main__":
    run_server()
