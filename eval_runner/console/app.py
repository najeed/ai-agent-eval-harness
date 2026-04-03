from dotenv import load_dotenv
# Ensure environment variables are loaded before ANY other imports (R6: Environment Portability)
load_dotenv()

import os
import hashlib
import flask
from flask import Flask, send_from_directory
from flask_cors import CORS
from .routes import register_core_routes, core_bp
from .auth import auth_bp
from .auth_manager import Permission, require_permission
from .demo_agent import demo_bp
from eval_runner.plugins import manager
from .. import config

print(f"--- [v1.2.3-BOOT] Flask App Initializing (DASHBOARD_API_KEY: {config.DASHBOARD_API_KEY[:4] if config.DASHBOARD_API_KEY else 'None'})", flush=True)

def create_app():
    # Eager Hydration: Ensure plugins and scenarios are loaded before the first request
    # This eliminates the "0 scenarios" state on initial load.
    manager.load_plugins()
    from eval_runner.catalog import ScenarioCatalog
    ScenarioCatalog.get_instance().load_index()

    # Set static_folder using the project root for absolute reliability
    ui_path = os.path.abspath(config.PROJECT_ROOT / "ui" / "visual-debugger")
    app = Flask(__name__, static_folder=ui_path, static_url_path="")
    
    # Ensure session persistence (v1.2.3 Stabilization)
    app.secret_key = hashlib.sha256(config.DASHBOARD_API_KEY.encode()).hexdigest()
    
    CORS(app, supports_credentials=True) # Explicit support for session cookies
    app.register_blueprint(auth_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(demo_bp)

    # Hardened API Error Handlers (Prevents "Unexpected token <" regressions)
    @app.errorhandler(404)
    def handle_404(e):
        print(f"   [Trace] 404 Error - Path: {flask.request.path}", flush=True)
        return flask.jsonify({"error": "Resource Not Found: The API endpoint requested is invalid.", "status": 404}), 404

    @app.errorhandler(405)
    def handle_405(e):
        return flask.jsonify({"error": "Method Not Allowed: This endpoint does not accept the requested HTTP method.", "status": 405}), 405

    # Hardened Route Precedence (v1.2.3)
    # Explicitly register the login handler to bypass blueprint shadowing/405
    from .auth import login as login_handler
    app.add_url_rule("/api/auth/login", view_func=login_handler, methods=["POST"], strict_slashes=False)


    # Load external hooks for zero-touch discovery
    manager.load_plugins()

    # Core navigation registry
    nav_registry = []

    # Register core routes
    register_core_routes(app, nav_registry)
    
    # Safely initialize debugger event subscription
    from .routes import subscribe_debugger
    subscribe_debugger()

    # Trigger plugin hook to register additional routes and nav items
    for plugin in manager.plugins:
        method = getattr(plugin, "on_register_console_routes", None)
        if method and callable(method):
            try:
                method(app, nav_registry)
            except Exception as e:
                pass

    # Re-assert core paths to prevent plugin overrides
    core_paths = {
        "community": "https://github.com/najeed/ai-agent-eval-harness",
        "demo": "/demo",
        "loan_demo": "/demo/loan"
    }
    for item in nav_registry:
        if item.get('id') in core_paths:
            item['path'] = core_paths[item['id']]

    # Endpoint to serve the unified navigation menu (API Priority)
    app.config["NAV_REGISTRY"] = nav_registry
    
    @app.route("/api/nav")
    def get_nav():
        # Add dynamic markers if needed (e.g. active states)
        return flask.jsonify(app.config["NAV_REGISTRY"])

    # Frontend Catch-all Routes (Define LAST to prevent API masking)
    @app.route("/", defaults={'path': ''})
    @app.route("/scenarios")
    @app.route("/reports")
    @app.route("/editor")
    @app.route("/debugger")
    @app.route("/demo")
    @app.route("/demo/loan")
    @app.route("/docs")
    @app.route("/docs/api")
    def index(path=''):
        print(f"DEBUG: SPA Navigation - Obtaining industrial route: {flask.request.path}")
        return send_from_directory(app.static_folder, "index.html")

    return app


def run_server(host="127.0.0.1", port=5000, debug=False):
    app = create_app()
    # Increase interval to 2s to avoid over-eager site-packages reloads
    app.run(host=host, port=port, debug=debug, use_reloader=debug, reloader_interval=2)


if __name__ == "__main__":
    run_server()
