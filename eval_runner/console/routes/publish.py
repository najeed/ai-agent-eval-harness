"""
routes/publish.py

Publish & Integrate group API endpoints:
  - Long-running Conductor execution (background job)
  - CI/CD YAML workflow generator
  - Regulatory standards registry sync & updates
"""

import json
import logging
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from eval_runner import config
from eval_runner.handlers.environment import scaffold
from eval_runner.registry_sync import add_standard_to_registry, load_registry

from ..auth_manager import Permission, require_permission

logger = logging.getLogger(__name__)

publish_bp = Blueprint("publish", __name__)

# Global in-memory background job tracking
JOBS = {}


def _run_publication_job(job_id, cmd, log_path):
    """Background worker thread executing the publication suite script."""
    JOBS[job_id]["status"] = "running"
    JOBS[job_id]["progress"] = "Initializing batch conductor..."

    try:
        # Redirect stdout and stderr to log file for user display
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
            )
            JOBS[job_id]["_proc"] = proc

            # Read output stream in real-time
            for line in proc.stdout:
                log_file.write(line)
                log_file.flush()

                # Check keywords or progress counters to update state progress
                if "Running run" in line or "Completed run" in line or "runs complete" in line:
                    clean_line = line.strip()
                    # Extract the x/y part
                    parts = clean_line.split("]")
                    if len(parts) > 1:
                        prog_text = parts[1].strip()
                        # e.g. "Conducting evaluations (Running run 1/5...)"
                        # or   "Conducting evaluations (Completed run 1/5...)"
                        JOBS[job_id]["progress"] = f"Conducting evaluations ({prog_text})"
                elif "Phase 1" in line:
                    JOBS[job_id]["progress"] = "Conducting evaluation suite..."
                elif "Phase 2" in line:
                    JOBS[job_id]["progress"] = "Aggregating metrics and scoring..."
                elif "Phase 3" in line:
                    JOBS[job_id]["progress"] = "Building Recharts leaderboards..."
                elif "Phase 4" in line:
                    JOBS[job_id]["progress"] = "Generating signed regulatory ZIP bundle..."

            proc.wait()

        # Clean up process reference
        if "_proc" in JOBS[job_id]:
            del JOBS[job_id]["_proc"]

        if proc.returncode == 0:
            # Locate the newly created batch directory under results/
            results_path = config.PROJECT_ROOT / "results"
            batches = sorted(
                [d for d in results_path.iterdir() if d.is_dir() and d.name.startswith("batch_")],
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )

            if batches:
                batch_dir = batches[0]
                manifest_path = batch_dir / "manifest.json"
                manifest_data = {}
                if manifest_path.exists():
                    try:
                        with open(manifest_path, encoding="utf-8") as f:
                            manifest_data = json.load(f)
                    except Exception as e:
                        logger.warning(f"Failed to read manifest for job {job_id}: {e}")

                zip_path = batch_dir / "publication_artifact_bundle.zip"
                leaderboard_path = batch_dir / (
                    "pilot_preview.html" if "pilot" in cmd else "leaderboard.html"
                )

                JOBS[job_id]["status"] = "completed"
                JOBS[job_id]["progress"] = "Publication completed successfully."
                JOBS[job_id]["results"] = {
                    "batch_id": batch_dir.name,
                    "manifest": manifest_data,
                    "zip_file": str(zip_path.relative_to(config.PROJECT_ROOT))
                    if zip_path.exists()
                    else None,
                    "leaderboard_html": str(leaderboard_path.relative_to(config.PROJECT_ROOT))
                    if leaderboard_path.exists()
                    else None,
                }
            else:
                JOBS[job_id]["status"] = "failed"
                JOBS[job_id]["progress"] = "Publication failed."
                JOBS[job_id]["error"] = "Process completed, but results batch folder was not found."
        else:
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["progress"] = "Publication failed."
            JOBS[job_id]["error"] = f"Publication script failed with exit code: {proc.returncode}"
    except Exception as e:
        logger.error(f"[Publish Job] Failure executing job {job_id}: {e}")
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["progress"] = "Publication failed."
        JOBS[job_id]["error"] = str(e)


# ---------------------------------------------------------------------------
# Conductor / Publication Suite Jobs
# ---------------------------------------------------------------------------


@publish_bp.route("/publish", methods=["POST"])
@require_permission(Permission.EVAL_TRIGGER)
def start_publish_run():
    """
    Spawns a publication suite conductor background job and returns {job_id}.
    Inputs include mode, path, agent name, protocol, endpoint, parallel.
    """
    # Enforce single active job constraint
    active_jobs = [jid for jid, j in JOBS.items() if j.get("status") in ["queued", "running"]]
    if active_jobs:
        return jsonify(
            {
                "error": (
                    "Another publication job is currently running. "
                    "Please wait for it to complete or stop it before launching a new one."
                ),
                "active_job_id": active_jobs[0],
            }
        ), 400

    body = request.get_json(silent=True) or {}

    mode = body.get("mode", "standard")
    path = body.get("path", "scenarios/")
    agent_name = body.get("agent_name", "Verified-Adapter-v1")
    protocol = body.get("protocol", "http")
    agent = body.get("agent", "http://localhost:5001/execute_task")
    parallel = body.get("parallel", 4)

    job_id = f"pub_job_{uuid.uuid4().hex[:12]}"

    # Setup job tracking
    JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": "Pending launch...",
        "params": {
            "mode": mode,
            "path": path,
            "agent_name": agent_name,
            "protocol": protocol,
            "agent": agent,
            "parallel": parallel,
        },
        "results": None,
        "error": None,
    }

    # Spawn background process
    suite_dir = Path(__file__).parent.parent.parent / "publication_suite"
    cmd = [
        sys.executable,
        "-u",
        str(suite_dir / "publication_suite.py"),
        "--mode",
        mode,
        "--path",
        path,
        "--agent-name",
        agent_name,
        "--protocol",
        protocol,
        "--agent",
        agent,
        "--parallel",
        str(parallel),
    ]

    log_dir = config.PROJECT_ROOT / "results" / "jobs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{job_id}.log"

    # Launch execution thread
    thread = threading.Thread(target=_run_publication_job, args=(job_id, cmd, log_path))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id, "status": "queued"})


@publish_bp.route("/publish/<job_id>", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_publish_job(job_id: str):
    """Returns the current status, progress, and results of a publication job."""
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": f"Job '{job_id}' not found"}), 404

    # Attempt to read log file to return output streams
    log_path = config.PROJECT_ROOT / "results" / "jobs" / f"{job_id}.log"
    log_content = ""
    if log_path.exists():
        try:
            with open(log_path, encoding="utf-8") as f:
                raw_log = f.read()

            project_root_str = str(config.PROJECT_ROOT)
            normalized_root = project_root_str.lower().replace("\\", "/")

            lines = []
            for line in raw_log.splitlines():
                norm_line = line.replace("\\", "/")
                idx = norm_line.lower().find(normalized_root)
                if idx != -1:
                    orig_root_str = line[idx : idx + len(project_root_str)]
                    line = line.replace(orig_root_str, ".")
                lines.append(line)
            log_content = "\n".join(lines)
        except Exception as e:
            logger.warning(f"Failed to read log file for job {job_id}: {e}")

    # Filter out non-serializable objects (like the _proc Popen handle)
    serializable_job = {k: v for k, v in job.items() if not k.startswith("_")}
    response = jsonify({**serializable_job, "logs": log_content})
    if job.get("status") in ["completed", "failed"]:
        response.headers["X-Poll-Stop"] = "true"
    return response


@publish_bp.route("/publish/<job_id>/stop", methods=["POST"])
@require_permission(Permission.EVAL_TRIGGER)
def stop_publish_job(job_id: str):
    """Gracefully terminates a running publication conductor subprocess."""
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": f"Job '{job_id}' not found"}), 404

    if job["status"] not in ["queued", "running"]:
        return jsonify({"message": f"Job is already finished with status '{job['status']}'."}), 200

    proc = job.get("_proc")
    if proc:
        try:
            import psutil

            # Force kill child processes recursively (including parallel scenario tasks)
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except Exception as e:
                    logger.debug(f"Failed to kill child process: {e}")
            parent.kill()

            # Wait for cleanup
            psutil.wait_procs(children, timeout=3)
            parent.wait(timeout=3)
        except Exception as e:
            logger.warning(f"Process termination cleanup warning: {e}")
            if proc:
                try:
                    proc.kill()
                except Exception as e:
                    logger.debug(f"Failed to kill fallback process: {e}")

    job["status"] = "failed"
    job["error"] = "Job aborted by user request."
    job["progress"] = "Job stopped."

    if "_proc" in job:
        del job["_proc"]

    return jsonify({"status": "stopped", "message": "Job terminated successfully."})


@publish_bp.route("/publish/<job_id>/bundle", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def download_job_bundle(job_id: str):
    """Streams the signed ZIP output artifact created by the job once finished."""
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": f"Job '{job_id}' not found"}), 404

    if job["status"] != "completed" or not job["results"] or not job["results"].get("zip_file"):
        return jsonify({"error": "Job bundle is not yet complete or has failed"}), 400

    zip_path = config.PROJECT_ROOT / job["results"]["zip_file"]
    if not zip_path.exists():
        return jsonify({"error": "ZIP bundle file was not found on server disk"}), 404

    return send_file(
        str(zip_path),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"agentv_bundle_{job['results']['batch_id']}.zip",
    )


# ---------------------------------------------------------------------------
# CI/CD Workflow Generation
# ---------------------------------------------------------------------------


@publish_bp.route("/ci/generate", methods=["POST"])
@require_permission(Permission.EVAL_TRIGGER)
def generate_ci_workflow():
    """
    Generates a GitHub Actions workflow YAML configuration file,
    writes it locally using the core scaffold, and returns the YAML content.
    """
    try:
        # Run the scaffold CI generator
        scaffold.generate_github_action()

        # Read the generated file contents
        workflow_path = config.PROJECT_ROOT / ".github" / "workflows" / "eval_harness_ci.yml"
        if not workflow_path.exists():
            return jsonify({"error": "YAML file generation failed to write to disk"}), 500

        with open(workflow_path, encoding="utf-8") as f:
            yaml_content = f.read()

        return jsonify(
            {
                "status": "success",
                "file_path": str(workflow_path.relative_to(config.PROJECT_ROOT)),
                "yaml": yaml_content,
            }
        )
    except Exception as e:
        logger.error(f"[CI/CD] Workflow generation failed: {e}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Registry Sync (Standards Reference Browser)
# ---------------------------------------------------------------------------


@publish_bp.route("/registry", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def get_registry():
    """Returns the categorized standards registry tree loaded from disk."""
    try:
        registry = load_registry()
        return jsonify(registry)
    except Exception as e:
        logger.error(f"[Registry] Loading failed: {e}")
        return jsonify({"error": str(e)}), 500


@publish_bp.route("/registry", methods=["POST"])
@require_permission(Permission.SCENARIOS_WRITE)
def add_standard():
    """
    Adds a new compliance standard (regulatory requirement) to the central registry.
    Gated to System Admin users via SCENARIOS_WRITE permissions.
    """
    body = request.get_json(silent=True) or {}

    standard_id = body.get("id")
    name = body.get("name")
    industry = body.get("industry")
    description = body.get("description")
    category = body.get("category")

    if not standard_id or not name or not industry or not description:
        return jsonify({"error": "Fields id, name, industry, description are required"}), 400

    try:
        success = add_standard_to_registry(
            standard_id=standard_id,
            name=name,
            industry=industry,
            description=description,
            category=category,
        )
        if success:
            return jsonify(
                {"status": "success", "message": f"Added standard '{standard_id}' successfully."}
            )
        else:
            return jsonify({"error": f"Standard '{standard_id}' already exists in registry."}), 400
    except Exception as e:
        logger.error(f"[Registry] Add standard failed: {e}")
        return jsonify({"error": str(e)}), 500
