"""
routes/suites.py

API Endpoints for Regression Suites and Auditable ZIP Bundling.
Provides CRUD for regression suites, staging trace files, rendering reports,
zipping, and Ed25519 manifest signature verification.
"""

import json
import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from eval_runner import config
from eval_runner.artifact_plugin import ArtifactPlugin
from eval_runner.console.pdf_service import generate_bundle_pdf, generate_run_pdf
from eval_runner.explainer import explain_trace

from ..auth_manager import Permission, require_permission
from .runs import resolve_trace_path

logger = logging.getLogger(__name__)
suites_bp = Blueprint("suites", __name__)

SUITES_DIR = config.PROJECT_ROOT / "results" / "suites"
SUITES_DIR.mkdir(parents=True, exist_ok=True)


def _load_suites() -> list[dict]:
    """Loads all suite records from disk."""
    suites = []
    for p in SUITES_DIR.glob("*.json"):
        if p.name.endswith("_manifest.json"):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                suites.append(json.load(f))
        except Exception as e:
            logger.warning(f"Failed to load suite file {p}: {e}")
    suites.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return suites


@suites_bp.route("/v1/suites", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def list_suites():
    """Lists saved regression suites."""
    return jsonify({"suites": _load_suites()})


@suites_bp.route("/v1/suites", methods=["POST"])
@require_permission(Permission.EVAL_TRIGGER)
def create_suite():
    """Creates a new regression suite."""
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    agent_name = body.get("agent_name")
    run_ids = body.get("run_ids", [])

    if not name or not agent_name or not run_ids:
        return jsonify({"error": "Missing required fields: name, agent_name, run_ids"}), 400

    suite_id = f"suite_{uuid.uuid4().hex[:12]}"
    suite_record = {
        "suite_id": suite_id,
        "name": name,
        "agent_name": agent_name,
        "run_ids": run_ids,
        "created_by": "Compliance Officer",
        "created_at": datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
    }

    try:
        suite_path = SUITES_DIR / f"{suite_id}.json"
        with open(suite_path, "w", encoding="utf-8") as f:
            json.dump(suite_record, f, indent=2)
        return jsonify(suite_record), 201
    except Exception as e:
        logger.error(f"Failed to save suite record: {e}")
        return jsonify({"error": str(e)}), 500


@suites_bp.route("/v1/suites/<suite_id>/bundle", methods=["POST"])
@require_permission(Permission.EVAL_TRIGGER)
def bundle_suite(suite_id):
    """Stages run logs and certificates, generates PDFs, and bundles them into a ZIP."""
    suite_path = SUITES_DIR / f"{suite_id}.json"
    if not suite_path.exists():
        return jsonify({"error": "Suite not found"}), 404

    try:
        with open(suite_path, encoding="utf-8") as f:
            suite_data = json.load(f)
    except Exception as e:
        return jsonify({"error": f"Corrupt suite record: {e}"}), 500

    staging_dir = SUITES_DIR / f"tmp_stage_{suite_id}"

    run_list = []
    files_to_include = []

    try:
        # 1. Create unique staging directory
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)
        # 2. Stage trace files for each run
        for run_id in suite_data.get("run_ids", []):
            trace_path = resolve_trace_path(run_id)
            temp_extracted = False
            temp_path = None

            # Fallback: scan master log
            if not trace_path:
                master_log = config.RUN_LOG_DIR / "run.jsonl"
                if master_log.exists():
                    filtered = []
                    try:
                        with open(master_log, encoding="utf-8") as f_master:
                            for line in f_master:
                                if f'"{run_id}"' in line:
                                    try:
                                        ev = json.loads(line.strip())
                                        if ev.get("run_id") == run_id:
                                            filtered.append(line.strip())
                                    except Exception:
                                        logger.debug("Parsing log line error")
                    except Exception:
                        logger.warning("Error reading master log")
                    if filtered:
                        temp_path = SUITES_DIR / f"temp_{run_id}.jsonl"
                        with open(temp_path, "w", encoding="utf-8") as f_temp:
                            f_temp.write("\n".join(filtered))
                        trace_path = temp_path
                        temp_extracted = True

            if not trace_path or not trace_path.exists():
                logger.warning(f"Run {run_id} trace files missing. Skipping.")
                continue

            # Run Analysis
            try:
                analysis = explain_trace(trace_path)
            except Exception as e:
                logger.warning(f"Explain trace warning: {e}")
                analysis = {"root_cause": "Unknown", "suggestion": "N/A", "confidence": 0.5}

            # Fetch basic status info
            status = "COMPLETED"
            timestamp = datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"
            try:
                with open(trace_path, encoding="utf-8") as f_trace:
                    first_line = f_trace.readline()
                    if first_line:
                        ev = json.loads(first_line)
                        timestamp = ev.get("timestamp") or ev.get("_ts_iso") or timestamp
            except Exception as e:
                logger.debug(f"Error reading first trace line: {e}")

            run_data = {
                "run_id": run_id,
                "scenario": run_id,
                "status": status,
                "timestamp": timestamp,
                "analysis": analysis,
            }
            run_list.append(run_data)

            # Create run staging folder
            run_stage = staging_dir / "runs" / run_id
            run_stage.mkdir(parents=True, exist_ok=True)

            # Copy trace
            shutil.copy(trace_path, run_stage / "run.jsonl")
            files_to_include.append(f"runs/{run_id}/run.jsonl")

            # Copy certificate if exists
            cert_src = config.REPORTS_DIR / "certificates" / f"{run_id}_vc.json"
            if cert_src.exists():
                shutil.copy(cert_src, run_stage / "run_manifest.json")
                files_to_include.append(f"runs/{run_id}/run_manifest.json")

            # Generate individual CIO/CISO compliance report PDF
            pdf_dest = run_stage / "report.pdf"
            if generate_run_pdf(run_data, pdf_dest):
                files_to_include.append(f"runs/{run_id}/report.pdf")

            # Cleanup temp extraction
            if temp_extracted and temp_path and temp_path.exists():
                temp_path.unlink()

        # 3. Generate companion bundle PDF
        companion_path = staging_dir / "companion_summary.pdf"
        if generate_bundle_pdf(suite_data, run_list, companion_path):
            files_to_include.append("companion_summary.pdf")

        # 4. Invoke Core signed bundle service
        plugin = ArtifactPlugin()
        bundle_res = plugin.bundle_artifacts(
            target_dir=str(staging_dir),
            files_to_include=files_to_include,
            output_filename=f"{suite_id}_bundle.zip",
            generate_manifest=True,
        )

        # Move output deliverables to suites base directory
        final_zip = SUITES_DIR / f"{suite_id}_bundle.zip"
        final_manifest = SUITES_DIR / f"{suite_id}_audit_manifest.json"

        if Path(bundle_res["bundle_path"]).exists():
            shutil.move(bundle_res["bundle_path"], final_zip)
        if Path(bundle_res["manifest_path"]).exists():
            shutil.move(bundle_res["manifest_path"], final_manifest)

        # Clean staging directory
        shutil.rmtree(staging_dir)

        # Update suite index with bundle presence
        suite_data["zip_file"] = f"results/suites/{suite_id}_bundle.zip"
        suite_data["manifest_file"] = f"results/suites/{suite_id}_audit_manifest.json"
        with open(suite_path, "w", encoding="utf-8") as f:
            json.dump(suite_data, f, indent=2)

        return jsonify(
            {
                "status": "success",
                "zip_file": f"results/suites/{suite_id}_bundle.zip",
                "manifest_file": f"results/suites/{suite_id}_audit_manifest.json",
            }
        )

    except Exception as e:
        logger.error(f"Failed to bundle suite {suite_id}: {e}")
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        return jsonify({"error": str(e)}), 500


@suites_bp.route("/v1/suites/<suite_id>/download", methods=["GET"])
def download_suite_bundle(suite_id):
    """Downloads the compiled signed ZIP bundle."""
    zip_path = SUITES_DIR / f"{suite_id}_bundle.zip"
    if not zip_path.exists():
        return jsonify({"error": "Bundle not found"}), 404
    return send_file(zip_path, as_attachment=True)


@suites_bp.route("/v1/bundles/verify", methods=["POST"])
def verify_bundle():
    """Accepts uploaded audit_manifest.json and verifies cryptographic signature and file hashes."""
    if "file" not in request.files:
        return jsonify({"error": "No manifest file uploaded"}), 400

    file = request.files["file"]
    temp_path = SUITES_DIR / f"verify_tmp_{uuid.uuid4().hex}.json"
    try:
        file.save(temp_path)
        plugin = ArtifactPlugin()
        res = plugin.verify_integrity(str(temp_path))
        temp_path.unlink()
        return jsonify(res)
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        return jsonify({"status": "error", "message": str(e)}), 500


@suites_bp.route("/v1/runs/<run_id>/report.pdf", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_run_report_pdf(run_id):
    """Generates and streams the CIO/CISO compliance overview PDF report for a run."""
    trace_path = resolve_trace_path(run_id)
    temp_extracted = False
    temp_path = None

    # Fallback: scan master log
    if not trace_path:
        master_log = config.RUN_LOG_DIR / "run.jsonl"
        if master_log.exists():
            filtered = []
            try:
                with open(master_log, encoding="utf-8") as f_master:
                    for line in f_master:
                        if f'"{run_id}"' in line:
                            try:
                                ev = json.loads(line.strip())
                                if ev.get("run_id") == run_id:
                                    filtered.append(line.strip())
                            except Exception as e:
                                logger.debug(f"Parsing run line warning: {e}")
            except Exception as e:
                logger.warning(f"Error scanning master log: {e}")
            if filtered:
                temp_path = SUITES_DIR / f"temp_pdf_{run_id}.jsonl"
                with open(temp_path, "w", encoding="utf-8") as f_temp:
                    f_temp.write("\n".join(filtered))
                trace_path = temp_path
                temp_extracted = True

    if not trace_path or not trace_path.exists():
        return jsonify({"error": "Run not found"}), 404

    # Run Analysis
    try:
        analysis = explain_trace(trace_path)
    except Exception as e:
        logger.warning(f"Explain trace warning: {e}")
        analysis = {"root_cause": "Unknown", "suggestion": "N/A", "confidence": 0.5}

    status = "COMPLETED"
    timestamp = datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"
    try:
        with open(trace_path, encoding="utf-8") as f:
            first_line = f.readline()
            if first_line:
                ev = json.loads(first_line)
                timestamp = ev.get("timestamp") or ev.get("_ts_iso") or timestamp
    except Exception as e:
        logger.debug(f"Error reading first trace line: {e}")

    run_data = {
        "run_id": run_id,
        "scenario": run_id,
        "status": status,
        "timestamp": timestamp,
        "analysis": analysis,
    }

    pdf_path = SUITES_DIR / f"report_{run_id}.pdf"
    try:
        success = generate_run_pdf(run_data, pdf_path)
        if temp_extracted and temp_path and temp_path.exists():
            temp_path.unlink()

        if not success or not pdf_path.exists():
            return jsonify({"error": "Failed to compile report PDF"}), 500

        return send_file(
            pdf_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"report_{run_id}.pdf",
        )
    except Exception as e:
        if temp_extracted and temp_path and temp_path.exists():
            temp_path.unlink()
        return jsonify({"error": str(e)}), 500
