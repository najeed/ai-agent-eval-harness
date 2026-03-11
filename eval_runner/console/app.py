from flask import Flask
from flask_cors import CORS
from .routes import register_core_routes
from eval_runner.plugins import manager

def create_app():
    app = Flask(__name__)
    CORS(app)
    
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
                print(f"[Console] Error registering routes for plugin {plugin.__class__.__name__}: {e}")
                
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
