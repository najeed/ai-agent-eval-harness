import asyncio
import json
import logging
import threading
from pathlib import Path

from flask import Blueprint, jsonify, request

from eval_runner import engine, loader, mutator, spec_parser, taxonomy
from eval_runner.catalog import ScenarioCatalog

from ..auth_manager import Permission, require_permission

logger = logging.getLogger(__name__)

scenario_bp = Blueprint("scenarios", __name__)


def get_catalog():
    return ScenarioCatalog.get_instance()


@scenario_bp.route("/scenarios", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def list_scenarios():
    """Returns a faceted list of all scenarios."""
    query = request.args.get("q")
    industry = request.args.get("industry")
    difficulty = request.args.get("difficulty")
    limit = int(request.args.get("limit", 50))
    page = int(request.args.get("page", 1))
    offset = (page - 1) * limit

    catalog = get_catalog()
    if not catalog.scenarios:
        catalog.load_index()

    results = catalog.search(
        query=query, industry=industry, difficulty=difficulty, limit=limit, offset=offset
    )
    return jsonify(
        {"scenarios": results, "total_count": len(catalog.scenarios), "page": page, "limit": limit}
    )


@scenario_bp.route("/scenarios", methods=["POST"])
@require_permission(Permission.SCENARIOS_WRITE)
def save_scenario():
    """Industrial persistence for new/modified scenarios."""
    import re

    data = request.json or {}
    scen_id = data.get("id")
    industry = data.get("industry", "generic")

    if not scen_id or not re.match(r"^[a-zA-Z0-9_\-]+$", scen_id):
        return jsonify({"error": "Invalid or missing scenario ID"}), 400

    # Sanitize ID anyway for safety (R6)
    scen_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", scen_id)

    from eval_runner import config

    # Follow AEH v1.5.0 structure: industries/{industry}/scenarios/{id}.json
    save_dir = config.PROJECT_ROOT / "industries" / industry / "scenarios"
    save_dir.mkdir(parents=True, exist_ok=True)

    save_path = save_dir / f"{scen_id}.json"
    try:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save scenario {scen_id}: {e}")
        return jsonify({"error": f"Failed to save scenario: {str(e)}"}), 500

    ScenarioCatalog.get_instance().build_index()
    return jsonify({"status": "success", "path": str(save_path)})


@scenario_bp.route("/scenarios/refresh", methods=["POST"])
@require_permission(Permission.SCENARIOS_READ)
def refresh_index():
    """Triggers catalog re-indexing."""
    try:
        ScenarioCatalog.get_instance().build_index()
        return jsonify(
            {"status": "success", "scenario_count": len(ScenarioCatalog.get_instance().scenarios)}
        )
    except Exception as e:
        logger.error(f"Catalog refresh failed: {e}")
        return jsonify({"error": str(e)}), 500


@scenario_bp.route("/v1/evaluate", methods=["POST"])
@require_permission(Permission.EVAL_TRIGGER)
def evaluate_scenario():
    """Triggers an asynchronous evaluation run (Industrial Protocol)."""
    data = request.json or {}
    path = data.get("path")
    if not path:
        return jsonify({"error": "Missing scenario path"}), 400

    # Industrial Trigger: Prioritize Scenario ID resolution (v1.5.0)
    catalog = ScenarioCatalog.get_instance()
    abs_path = catalog.get_absolute_path(path)

    if abs_path:
        exists_physically = abs_path.exists()
        path = str(abs_path)
    else:
        # Fallback to filesystem lookup (R6)
        from eval_runner import config

        target = Path(path)
        if not target.is_absolute():
            target = config.PROJECT_ROOT / path

        exists_physically = target.exists()
        path = str(target)

    if not exists_physically:
        msg = f"Scenario not found: {path} (Check Industrial Catalog)"
        return jsonify({"error": msg, "message": msg}), 404

    try:
        # Validate load synchronously before async handoff (R6)
        scen = loader.load_scenario(path)
    except Exception as e:
        logger.error(f"Scenario load failed: {e}")
        return jsonify({"error": f"Failed to load scenario: {str(e)}", "message": str(e)}), 500

    def run_wrapper(scenario_obj, turns):
        try:
            asyncio.run(engine.run_evaluation(scenario_obj, max_turns=turns))
        except Exception as e:
            logger.error(f"Async evaluation failed: {e}")

    thread = threading.Thread(target=run_wrapper, args=(scen, data.get("max_turns", 10)))
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started", "message": f"Evaluation of {path} initiated."})


@scenario_bp.route("/v1/taxonomy", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def get_taxonomy():
    """Roadmap: Display the official AEH failure taxonomy."""
    return jsonify({"categories": taxonomy.CATEGORIES})


@scenario_bp.route("/v1/mutate", methods=["POST"])
@require_permission(Permission.SCENARIOS_READ)
def mutate_scenario():
    """Roadmap: Programmatic mutation with raw content or file support."""
    data = request.json or {}
    mutation_type = data.get("type", "typo")

    # Support raw content or input path
    raw_content = data.get("raw_json")
    if raw_content:
        scenario = raw_content
    else:
        input_path = data.get("input_path")
        if not input_path or not Path(input_path).exists():
            return jsonify({"error": "Missing input_path or raw_json"}), 400
        with open(input_path, encoding="utf-8") as f:
            scenario = json.load(f)

    try:
        mutated = mutator.mutate_scenario(scenario, mutation_type)

        # Optionally save to output path
        output_path = data.get("output_path")
        if output_path:
            mutator.save_mutated_scenario(mutated, Path(output_path))

        return jsonify({"status": "success", "mutated": mutated})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@scenario_bp.route("/v1/spec-to-eval", methods=["POST"])
@require_permission(Permission.SCENARIOS_READ)
def spec_to_eval():
    """Roadmap: Markdown PRD/Spec to AES JSON conversion."""
    data = request.json or {}
    markdown_text = data.get("markdown")

    if not markdown_text:
        input_path = data.get("input_path")
        if not input_path or not Path(input_path).exists():
            return jsonify({"error": "Missing markdown text or input_path"}), 400
        with open(input_path, encoding="utf-8") as f:
            markdown_text = f.read()

    try:
        # Wrap async call for Flask compatibility
        scenario = asyncio.run(spec_parser.parse_markdown_to_scenario(markdown_text))

        output_path = data.get("output_path")
        if output_path:
            spec_parser.save_scenario_json(scenario, Path(output_path))

        return jsonify({"status": "success", "scenario": scenario})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
