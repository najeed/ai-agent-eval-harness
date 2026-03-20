import os
from flask import Flask, send_from_directory
from flask_cors import CORS
from .routes import register_core_routes
from .auth import auth_bp
from eval_runner.plugins import manager


def create_app():
    # Set static_folder to the visual debugger UI directory
    ui_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "ui", "visual-debugger")
    )
    app = Flask(__name__, static_folder=ui_path, static_url_path="")
    CORS(app)
    app.register_blueprint(auth_bp)

    # Load external hooks for zero-touch discovery
    manager.load_plugins()

    @app.route("/")
    @app.route("/scenarios")
    @app.route("/reports")
    @app.route("/editor")
    @app.route("/debugger")
    @app.route("/docs")
    @app.route("/docs/api")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # Core navigation registry
    nav_registry = []

    # Register core routes
    register_core_routes(app, nav_registry)

    # Trigger plugin hook to register additional routes and nav items
    for plugin in manager.plugins:
        method = getattr(plugin, "on_register_console_routes", None)
        if method and callable(method):
            try:
                method(app, nav_registry)
            except Exception as e:
                pass

    # Endpoint to serve the unified navigation menu
    @app.route("/api/nav", methods=["GET"])
    def get_nav():
        import flask

        return flask.jsonify({"nav": nav_registry})

    return app


def run_server(host="127.0.0.1", port=5000):
    app = create_app()
    app.run(host=host, port=port, debug=True, use_reloader=False)


if __name__ == "__main__":
    run_server()
