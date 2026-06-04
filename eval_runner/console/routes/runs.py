import json
import logging
import os
import threading
import time
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

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

    runs.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)
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

            # Dynamic Tail Resolution (AgentV v1.6.0 Industrial)
            # For small logs (< 128KB), read entirely. For large logs, seek to last 128KB.
            window = 128 * 1024  # 128KB
            with open(vault_trace, "rb") as f:
                if size <= window:
                    buffer = f.read()
                else:
                    f.seek(size - window)
                    buffer = f.read()

                # Scan for termination events in the retrieved tail
                if (
                    b'"event": "run_end"' in buffer
                    or b'"event": "verification_certificate_issued"' in buffer
                ):
                    is_finished = True
        except Exception as e:
            logger.warning(f"Error checking run status for {run_id}: {e}")
            pass

        import time

        status = "RUNNING"
        if is_finished:
            status = "COMPLETED"
        elif mtime > 0 and time.time() - mtime > 300:
            # [Industrial Heuristic] If no terminal event and no disk activity for 5m,
            # the engine has likely crashed or hung.
            status = "STALLED"

        return jsonify(
            {
                "run_id": run_id,
                "status": status,
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


def is_run_alive(run_id: str) -> bool:
    """Helper to detect if the runner is active in the process space."""
    return any(t.name == f"eval-{run_id}" for t in threading.enumerate())


def tail_file_generator(log_path: Path, run_id: str):
    # 1. Wait for log creation with a 10s safety threshold
    timeout = 10.0
    start_time = time.time()
    while not log_path.exists():
        if time.time() - start_time > timeout:
            yield 'data: {"event": "timeout", "message": "Execution log file not found"}\n\n'
            return
        time.sleep(0.5)

    # Resolve starting inode safely
    try:
        last_inode = log_path.stat().st_ino
    except OSError:
        last_inode = None

    # Track overall stream lifetime to prevent dead socket accumulation (Tab Safety)
    stream_start = time.time()
    max_lifetime_seconds = 3600  # 1-hour hard stop to reclaim sockets

    # 2. Open and Stream
    with open(log_path, encoding="utf-8") as f:
        # Step A: Stream all existing historical events (Immediate Catch-Up)
        for line in f:
            if line.strip():
                yield f"data: {line.strip()}\n\n"
                if '"event": "run_end"' in line or '"event": "strategy_end"' in line:
                    return

        # Step B: Enter tail loop
        idle_cycles = 0
        while True:
            # Safeguard: Terminate long-running zombie streams
            if time.time() - stream_start > max_lifetime_seconds:
                yield (
                    'data: {"event": "error", '
                    '"message": "Stream exceeded max connection lifetime"}\n\n'
                )
                break

            # Safeguard: Check if the file was deleted or rotated
            if not log_path.exists():
                yield 'data: {"event": "error", "message": "Log file deleted"}\n\n'
                break

            if last_inode:
                try:
                    current_inode = log_path.stat().st_ino
                    if current_inode != last_inode:
                        yield 'data: {"event": "error", "message": "Log file rotated"}\n\n'
                        break
                except OSError:
                    # Ignore transient file access errors
                    pass

            line = f.readline()
            if not line:
                time.sleep(0.1)
                idle_cycles += 1

                # Send heartbeat every 15 seconds to prevent gateway drops
                if idle_cycles >= 150:
                    yield ": heartbeat\n\n"
                    idle_cycles = 0

                    # Zombie Check: Verify if the thread is still active
                    if not is_run_alive(run_id):
                        yield (
                            'data: {"event": "run_end", "status": "aborted", '
                            '"error": "Process thread terminated abruptly"}\n\n'
                        )
                        break
                continue

            idle_cycles = 0
            yield f"data: {line.strip()}\n\n"

            if '"event": "run_end"' in line or '"event": "strategy_end"' in line:
                break


@run_bp.route("/v1/runs/<path:run_id>/stream", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def stream_run_logs(run_id):
    """SSE streaming endpoint for live run traces."""
    log_path = config.RUN_LOG_DIR / run_id / "run.jsonl"
    return Response(tail_file_generator(log_path, run_id), mimetype="text/event-stream")
