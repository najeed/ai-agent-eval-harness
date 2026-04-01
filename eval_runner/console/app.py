import os
import hashlib
import flask
from flask import Flask, send_from_directory
from flask_cors import CORS
from .routes import register_core_routes, core_bp
from .auth import auth_bp
from .auth_manager import Role, require_permission
from .demo_agent import demo_bp
from eval_runner.plugins import manager
from .. import config


def create_app():
    # Set static_folder to the visual debugger UI directory
    ui_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ui", "visual-debugger"))
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
        return flask.jsonify({"error": "Resource Not Found: The API endpoint requested is invalid.", "status": 404}), 404

    @app.errorhandler(405)
    def handle_405(e):
        return flask.jsonify({"error": "Method Not Allowed: This endpoint does not accept the requested HTTP method.", "status": 405}), 405

    # Hardened Route Precedence (v1.2.3-ULTIMATE)
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
    @app.route("/api/nav", methods=["GET"])
    @require_permission(Role.DOCS_READ)
    def get_nav():
        import flask
        return flask.jsonify({"nav": nav_registry})

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
        return send_from_directory(app.static_folder, "index.html")

    return app


def run_server(host="127.0.0.1", port=5000, debug=False):
    app = create_app()
    # Increase interval to 2s to avoid over-eager site-packages reloads
    app.run(host=host, port=port, debug=debug, use_reloader=debug, reloader_interval=2)


if __name__ == "__main__":
    run_server()
