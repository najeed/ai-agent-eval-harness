from flask import Blueprint, jsonify, request
import os
from pathlib import Path
import json

core_bp = Blueprint("core", __name__, url_prefix="/api")

def register_core_routes(app, nav_registry):
    # Add core navigation items
    nav_registry.extend([
        {"id": "dashboard", "title": "Dashboard", "path": "/", "icon": "home"},
        {"id": "scenarios", "title": "Scenarios", "path": "/scenarios", "icon": "file-text"},
        {"id": "reports", "title": "Reports & Traces", "path": "/reports", "icon": "bar-chart-2"},
        {"id": "debugger", "title": "Visual Debugger", "path": "/debugger", "icon": "activity"},
        {"id": "docs", "title": "Documentation", "path": "/docs", "icon": "book"},
        {"id": "community", "title": "Community", "path": "https://github.com", "icon": "github"}
    ])
    
    app.register_blueprint(core_bp)

@core_bp.route("/scenarios", methods=["GET"])
def list_scenarios():
    """Returns a list of all scenarios in the industries directory."""
    scenarios = []
    industries_dir = Path("industries")
    if industries_dir.exists():
        for industry_dir in industries_dir.iterdir():
            if industry_dir.is_dir():
                scen_dir = industry_dir / "scenarios"
                if scen_dir.exists():
                    for scen_file in scen_dir.glob("*.json"):
                        try:
                            with open(scen_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                                scenarios.append({
                                    "scenario_id": data.get("scenario_id", scen_file.stem),
                                    "title": data.get("title", scen_file.stem),
                                    "industry": industry_dir.name,
                                    "file_path": str(scen_file)
                                })
                        except Exception:
                            pass
    return jsonify({"scenarios": scenarios})

@core_bp.route("/runs", methods=["GET"])
def list_runs():
    """Returns a list of recent run traces."""
    runs = []
    run_log = Path("runs") / "run.jsonl"
    if run_log.exists():
        try:
            with open(run_log, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line.strip())
                        if event.get("event") == "run_start":
                            runs.append({
                                "run_id": event.get("run_id"),
                                "scenario": event.get("scenario"),
                                "timestamp": event.get("timestamp")
                            })
                    except Exception:
                        pass
        except Exception:
            pass
    # Reverse to show newest first
    runs.reverse()
    return jsonify({"runs": runs[:100]})

@core_bp.route("/evaluate", methods=["POST"])
def evaluate_scenario():
    """Trigger an evaluation."""
    data = request.json or {}
    path = data.get("path")
    if not path:
        return jsonify({"error": "Missing 'path' parameter"}), 400
        
    # Async evaluation scheduling logic placeholder
    return jsonify({"status": "queued", "message": f"Evaluation triggered for {path}"})

@core_bp.route("/debugger/state", methods=["GET"])
def get_debugger_state():
    """Retrieve realtime or latest interactive debugger state."""
    # Placeholder: hook into the last evaluation context or a live stream
    return jsonify({"status": "ok", "message": "Debugger data hook is active", "state": {}})

@core_bp.route("/docs", methods=["GET"])
def list_docs():
    """Retrieve available documentation guides."""
    docs = []
    base = Path("docs")
    for file in base.rglob("*.md"):
        docs.append({"id": str(file.relative_to(base)), "title": file.stem})
    return jsonify({"docs": docs})

@core_bp.route("/docs/<path:doc_path>", methods=["GET"])
def read_doc(doc_path):
    """Read a specific documentation markdown file."""
    base = Path("docs")
    target = base / doc_path
    
    # Simple path traversal protection
    if not str(target.resolve()).startswith(str(base.resolve())):
        return jsonify({"error": "Unauthorized"}), 403
        
    if not target.exists() or not target.is_file():
        return jsonify({"error": "Document not found"}), 404
        
    with open(target, "r", encoding="utf-8") as f:
        content = f.read()
    return jsonify({"content": content})
