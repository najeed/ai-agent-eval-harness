from flask import Blueprint, jsonify, request
import os
from pathlib import Path
import json

core_bp = Blueprint("core", __name__, url_prefix="/api")

def register_core_routes(app, nav_registry):
    # Add core navigation items with metadata for dynamic rendering
    nav_registry.extend([
        {"id": "dashboard", "title": "Dashboard", "path": "/", "icon": "home", "type": "internal"},
        {"id": "scenarios", "title": "Scenarios", "path": "/scenarios", "icon": "file-text", "type": "internal"},
        {"id": "reports", "title": "Reports & Traces", "path": "/reports", "icon": "bar-chart-2", "type": "internal"},
        {"id": "editor", "title": "Scenario Editor", "path": "/editor", "icon": "file-text", "type": "internal"},
        {"id": "debugger", "title": "Visual Debugger", "path": "/debugger", "icon": "activity", "type": "internal"},
        {"id": "docs", "title": "Documentation", "path": "/docs", "icon": "book", "type": "internal"},
        {"id": "api_docs", "title": "API Reference", "path": "/docs/api", "icon": "box", "type": "internal"},
        {"id": "community", "title": "Community", "path": "https://github.com/najeed/ai-agent-eval-harness", "icon": "github", "type": "external"}
    ])
    
    app.register_blueprint(core_bp)

@core_bp.route("/scenarios", methods=["GET"])
def list_scenarios():
    """Returns a faceted list of all scenarios."""
    from ..catalog import ScenarioCatalog
    from ..linter import ScenarioLinter
    
    query = request.args.get("q")
    industry = request.args.get("industry")
    difficulty = request.args.get("difficulty")
    
    catalog = ScenarioCatalog()
    catalog.load_index()
    
    results = catalog.search(query=query, industry=industry, difficulty=difficulty)
    
    # Enrich with real-time lint score for the explorer UI
    linter = ScenarioLinter()
    enriched = []
    for s in results[:100]: # Limit enrichment for performance
        lint_res = linter.lint(s["path"])
        s["lint_score"] = lint_res["score"]
        s["status"] = lint_res["status"]
        enriched.append(s)
        
    return jsonify({"scenarios": enriched})

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
    """Retrieve available documentation guides and API reference."""
    docs = []
    seen_ids = set()
    base = Path("docs")
    
    # Check for auto-generated API docs first to give them priority/specific category
    api_base = base / "api"
    if api_base.exists() and api_base.is_dir():
        for file in api_base.rglob("*.md"):
            doc_id = str(file.relative_to(base))
            if doc_id not in seen_ids:
                docs.append({"id": doc_id, "title": f"API: {file.stem}", "category": "API Reference"})
                seen_ids.add(doc_id)
            
    # Standard Markdown Guides (remaining ones)
    for file in base.rglob("*.md"):
        if ".github" in str(file): continue
        doc_id = str(file.relative_to(base))
        if doc_id not in seen_ids:
            docs.append({"id": doc_id, "title": file.stem, "category": "Guide"})
            seen_ids.add(doc_id)
            
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
