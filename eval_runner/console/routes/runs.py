import json
import logging
import os

from flask import Blueprint, jsonify, request

from eval_runner import config
from eval_runner.explainer import explain_trace
from eval_runner.metrics import MetricRegistry

from ..auth_manager import Permission, require_permission

logger = logging.getLogger(__name__)

run_bp = Blueprint("runs", __name__)


@run_bp.route("/v1/metrics", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def list_metrics():
    """Roadmap: List registered evaluation metrics."""
    return jsonify({"metrics": MetricRegistry.list_metrics()})


@run_bp.route("/v1/explain/<run_id>", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def explain_run(run_id):
    """Roadmap: Forensic RCA as a service."""
    # We'll leverage explainer logic here
    run_dir = config.RUN_LOG_DIR / run_id
    trace_path = run_dir / "run.jsonl"
    if not trace_path.exists():
        return jsonify({"error": "Trace not found"}), 404

    try:
        # Invoke the core forensic explainer (RCA Engine)
        analysis = explain_trace(trace_path)

        return jsonify(
            {
                "run_id": run_id,
                "status": "explained",
                "analysis": analysis,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@run_bp.route("/runs", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def list_runs():
    """Returns a list of recent run traces (Consolidated)."""
    query = request.args.get("q", "").lower()
    runs = []

    # 1. Master Log & Direct Fragments
    for p in config.RUN_LOG_DIR.glob("*.jsonl"):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    event = json.loads(line.strip())
                    if event.get("event") == "run_start":
                        rid = event.get("run_id")
                        scenario = event.get("scenario")
                        if query and query not in rid.lower() and query not in scenario.lower():
                            continue
                        runs.append(
                            {
                                "run_id": rid,
                                "scenario": scenario,
                                "timestamp": event.get("timestamp"),
                            }
                        )
        except Exception as e:
            logger.warning(f"Skipping malformed or inaccessible trace fragment {p}: {e}")
            continue

    # 2. Vault Scan
    log_paths = list(config.RUN_LOG_DIR.glob("*/run.jsonl"))
    for p in log_paths:
        if p.name == "run.jsonl" and p.parent == config.RUN_LOG_DIR:
            continue
        try:
            with open(p, encoding="utf-8") as f:
                event = json.loads(f.readline())
                if event.get("event") == "run_start":
                    rid = event.get("run_id")
                    scenario = event.get("scenario")
                    if query and query not in rid.lower() and query not in scenario.lower():
                        continue
                    runs.append(
                        {
                            "run_id": rid,
                            "scenario": scenario,
                            "timestamp": event.get("timestamp"),
                            "path": str(p.relative_to(config.RUN_LOG_DIR)),
                        }
                    )
        except Exception as e:
            logger.warning(f"Skipping malformed or inaccessible vault trace {p}: {e}")
            continue

    runs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return jsonify({"runs": runs[:200]})


@run_bp.route("/v1/runs/<path:run_id>", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_run_status(run_id):
    """Industrial Polling Primitive."""
    vault_trace = config.RUN_LOG_DIR / run_id / "run.jsonl"
    if vault_trace.exists():
        is_finished = False
        size = 0
        mtime = 0
        try:
            size = os.path.getsize(vault_trace)
            mtime = os.path.getmtime(vault_trace)
            with open(vault_trace, "rb") as f:
                if size > 0:
                    f.seek(max(0, size - 2048))
                    if b'"event": "run_end"' in f.read():
                        is_finished = True
        except Exception as e:
            logger.warning(f"Error checking run-end event for {run_id}: {e}")
            pass

        return jsonify(
            {
                "run_id": run_id,
                "status": "COMPLETED" if is_finished else "RUNNING",
                "size": size,
                "mtime": mtime,
            }
        )
    return jsonify({"error": "Run not found"}), 404


@run_bp.route("/v1/certificates/<run_id>", methods=["GET"])
def get_verification_certificate(run_id):
    """Public Trust Protocol endpoint."""
    cert_path = config.REPORTS_DIR / "certificates" / f"{run_id}_vc.json"
    if cert_path.exists():
        try:
            with open(cert_path, encoding="utf-8") as f:
                return jsonify(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Corrupt certificate file {cert_path}: {e}")
            return jsonify({"error": "Corrupt certificate found"}), 500

    vault_manifest = config.RUN_LOG_DIR / run_id / "run_manifest.json"
    if vault_manifest.exists():
        try:
            with open(vault_manifest, encoding="utf-8") as f:
                return jsonify(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Corrupt manifest file {vault_manifest}: {e}")
            return jsonify({"error": "Corrupt manifest found"}), 500
    return jsonify({"error": "Certificate not found"}), 404
