import os

import flask
from dotenv import load_dotenv
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from eval_runner.plugins import manager

from .. import config
from .auth import auth_bp
from .routes import (
    agent_targets_bp,
    analyze_bp,
    compliance_packs_bp,
    core_bp,
    demo_bp,
    evidence_bp,
    hitl_bp,
    publish_bp,
    register_core_routes,
    run_bp,
    scenario_bp,
    subscribe_debugger,
    suites_bp,
    system_bp,
    trust_bp,
)

# Ensure environment variables are loaded before ANY other configuration usage (R6)
load_dotenv()
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

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

    # Set visual-console as primary static_folder with fallback to visual-debugger
    v2_ui_dist = os.path.abspath(config.PROJECT_ROOT / "ui" / "visual-console" / "dist")
    fallback_ui = os.path.abspath(config.PROJECT_ROOT / "ui" / "visual-debugger")
    ui_path = v2_ui_dist if os.path.exists(v2_ui_dist) else fallback_ui
    app = Flask(__name__, static_folder=ui_path, static_url_path="/static")

    # Ensure session persistence (v1.2.3 Stabilization)
    api_key = getattr(config, "DASHBOARD_API_KEY", None)
    if api_key:
        from ..utils import crypto

        app.secret_key = crypto.checksum(api_key)
    else:
        # Fallback to a random key if no API key is provided, allowing the app to boot
        app.secret_key = os.urandom(24).hex()

    CORS(app, supports_credentials=True)  # Explicit support for session cookies
    app.register_blueprint(auth_bp)
    app.register_blueprint(system_bp, url_prefix="/api")
    app.register_blueprint(scenario_bp, url_prefix="/api")
    app.register_blueprint(run_bp, url_prefix="/api")
    app.register_blueprint(analyze_bp, url_prefix="/api")
    app.register_blueprint(publish_bp, url_prefix="/api")
    app.register_blueprint(suites_bp, url_prefix="/api")
    app.register_blueprint(compliance_packs_bp, url_prefix="/api")
    app.register_blueprint(hitl_bp, url_prefix="/api")
    app.register_blueprint(evidence_bp, url_prefix="/api")
    app.register_blueprint(agent_targets_bp)
    app.register_blueprint(trust_bp)

    # Demo blueprint is physically absent in production mode (ENABLE_DEMO=false).
    # This prevents demo routes from appearing in the route map at all.
    if config.ENABLE_DEMO:
        app.register_blueprint(demo_bp)
        print("   [Console] Demo mode active: demo_bp registered.", flush=True)
    else:
        print("   [Console] Production mode: demo_bp NOT registered.", flush=True)
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
        # Surface the current operational mode to all clients
        mode = "demo" if config.ENABLE_DEMO else "production"
        response.headers["X-AgentV-Mode"] = mode
        return response

    # [Extension isolation — feasible slice] Document-level CSP for the
    # console shell. The allowlist is exact:
    #   - cdn.jsdelivr.net: Monaco editor assets (@monaco-editor/loader CDN).
    #   - blob: in script-src/worker-src: the extension host mounts SRI-verified
    #     remote modules through ephemeral Blob URLs; this is a deliberate,
    #     documented seam (SRI proves bytes, signed manifests prove trust).
    # Everything else is locked to self. This does NOT authorize arbitrary
    # third-party script origins.
    CONSOLE_CSP = "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' https://cdn.jsdelivr.net blob:",
            "worker-src 'self' blob:",
            "connect-src 'self' https://cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self' data:",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
        ]
    )

    @app.after_request
    def security_headers(response):
        content_type = response.headers.get("Content-Type", "")
        if content_type.startswith("text/html"):
            response.headers.setdefault("Content-Security-Policy", CONSOLE_CSP)
            response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
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

    # Hardened Route Precedence (AgentV v1.6.0 Sync)
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

    # Industrial Diagnostic: Audit the physical route map (v1.6.0 Hardening)
    print("\n--- Industrial Route Map Audit ---", flush=True)
    for rule in app.url_map.iter_rules():
        print(f"   [Route] {rule.rule} ({rule.endpoint})", flush=True)
    print("--- Audit Complete ---\n", flush=True)

    # Assets route for visual-console
    @app.route("/assets/<path:path>")
    def serve_assets(path):
        assets_dir = os.path.join(ui_path, "assets")
        if os.path.exists(assets_dir):
            return send_from_directory(assets_dir, path)
        return jsonify({"error": "Asset Not Found"}), 404

    @app.route("/v2/assets/<path:path>")
    def serve_v2_assets(path):
        assets_dir = os.path.join(v2_ui_dist, "assets")
        if os.path.exists(assets_dir):
            return send_from_directory(assets_dir, path)
        return jsonify({"error": "Asset Not Found"}), 404

    # Direct static asset files from root
    @app.route("/favicon.png")
    @app.route("/logo-premium.png")
    @app.route("/favicon.svg")
    @app.route("/icons.svg")
    def serve_root_icons():
        filename = flask.request.path.lstrip("/")
        if os.path.exists(os.path.join(ui_path, filename)):
            return send_from_directory(ui_path, filename)
        return jsonify({"error": "Icon Not Found"}), 404

    # Compatibility Route: /v2 serves the new console
    @app.route("/v2", defaults={"path": ""}, strict_slashes=False)
    @app.route("/v2/<path:path>", strict_slashes=False)
    def serve_v2(path=""):
        if path:
            full_path = os.path.join(v2_ui_dist, path)
            if os.path.exists(full_path) and os.path.isfile(full_path):
                return send_from_directory(v2_ui_dist, path)
        return send_from_directory(v2_ui_dist, "index.html")

    # Canonical Primary Console Entrypoints & SPA Navigation
    # OSS SPA Navigation — only OSS routes are declared here.
    # Enterprise extension routes (/hitl, /compliance, /packs, /publish, /cicd,
    # /sync, /calibration, /metrics, /benchmarks, /suites, /translate) are NOT
    # registered here; they are served dynamically by the extension host when
    # a Control Plane extension is mounted.
    @app.route("/", defaults={"path": ""}, strict_slashes=False)
    @app.route("/scenarios", strict_slashes=False)
    @app.route("/reports", strict_slashes=False)
    @app.route("/editor", strict_slashes=False)
    @app.route("/debugger", strict_slashes=False)
    @app.route("/runner", strict_slashes=False)
    @app.route("/trust", strict_slashes=False)
    @app.route("/settings", strict_slashes=False)
    @app.route("/spec-import", strict_slashes=False)
    @app.route("/mutator", strict_slashes=False)
    @app.route("/failures", strict_slashes=False)
    @app.route("/triage", strict_slashes=False)
    @app.route("/docs", strict_slashes=False)
    @app.route("/docs/api", strict_slashes=False)
    def index(path=""):
        return send_from_directory(ui_path, "index.html")

    # Demo routes are only registered when ENABLE_DEMO=true
    if config.ENABLE_DEMO:

        @app.route("/demo", strict_slashes=False)
        @app.route("/demo/loan", strict_slashes=False)
        def index_demo(path=""):
            return send_from_directory(ui_path, "index.html")

    return app


def manage_pid_file():
    """
    Singleton Process Guard (Leak Prevention).
    Ensures only one instance of the Console API is running.
    """
    import os
    import sys

    import psutil

    # [Industrial Hardening]: Skip guard logic if we are the child process of the reloader.
    # Otherwise, we kill the parent process that just spawned us.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return

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
                should_unlink = False
                with open(pid_path) as check_f:
                    if check_f.read().strip() == str(os.getpid()):
                        should_unlink = True

                if should_unlink:
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

    # [STABILITY HARDENING]: Exclude log and report directories from reloader
    # to prevent write-triggered feedback loops during evaluations.
    extra_files = []

    # Increase interval to 2s to avoid over-eager site-packages reloads
    app.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=debug,
        reloader_interval=2,
        threaded=True,
        extra_files=extra_files if debug else None,
    )


if __name__ == "__main__":
    run_server()
