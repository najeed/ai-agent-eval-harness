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
from eval_runner.services.certification import CertificationService
from eval_runner.services.run_summary import RunSummaryService

from ..auth_manager import Permission, require_permission

logger = logging.getLogger(__name__)

run_bp = Blueprint("runs", __name__)


@run_bp.route("/v1/metrics", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def list_metrics():
    """Roadmap: List registered evaluation metrics."""
    return jsonify({"metrics": MetricRegistry.list_metrics()})


def resolve_trace_path(run_id: str) -> Path | None:
    from eval_runner.trace_utils import resolve_trace_path as _rtp

    return _rtp(run_id, allow_master_recovery=False)


@run_bp.route("/v1/explain/<run_id>", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def explain_run(run_id):
    """Roadmap: Forensic RCA as a service."""
    trace_path = resolve_trace_path(run_id)
    temp_path = None

    if not trace_path:
        # Fallback: extract from master log runs/run.jsonl
        master_log = config.RUN_LOG_DIR / "run.jsonl"
        if master_log.exists():
            filtered_lines = []
            try:
                with open(master_log, encoding="utf-8") as f:
                    for line in f:
                        line_str = line.strip()
                        if line_str:
                            try:
                                ev = json.loads(line_str)
                                if ev.get("run_id") == run_id:
                                    filtered_lines.append(line_str)
                            except Exception as e:
                                logger.debug(f"Parsing run line warning: {e}")
            except Exception as e:
                logger.warning(f"Error scanning master log: {e}")

            if filtered_lines:
                import uuid

                temp_path = config.RUN_LOG_DIR / f"temp_explain_{run_id}_{uuid.uuid4().hex}.jsonl"
                try:
                    with open(temp_path, "w", encoding="utf-8") as out:
                        out.write("\n".join(filtered_lines))
                    trace_path = temp_path
                except Exception as e:
                    if temp_path.exists():
                        temp_path.unlink()
                    return jsonify({"error": str(e)}), 500

    if not trace_path:
        return jsonify({"error": "Trace not found"}), 404

    try:
        # Invoke the core forensic explainer (RCA Engine)
        analysis = explain_trace(trace_path)
        if temp_path and temp_path.exists():
            temp_path.unlink()

        return jsonify(
            {
                "run_id": run_id,
                "status": "explained",
                "analysis": analysis,
                "sourced_from_master": temp_path is not None,
            }
        )
    except Exception as e:
        if temp_path and temp_path.exists():
            temp_path.unlink()
        return jsonify({"error": str(e)}), 500


class RunsCache:
    """Thread-safe in-memory cache for recent run logs, updated incrementally."""

    def __init__(self, autostart: bool = False):
        self._lock = threading.Lock()
        self._runs = []
        self._scanned_files = {}  # path -> mtime
        self._last_dir = None
        self._started = False
        self._stop_event = threading.Event()
        self._thread = None
        if autostart:
            self.start()

    def start(self):
        """Starts background updater thread if not already running."""
        with self._lock:
            if self._started:
                return
            self._started = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._update_loop, name="runs-cache-updater", daemon=True
            )
            self._thread.start()

    def stop(self):
        """Stops background updater thread."""
        with self._lock:
            if not self._started:
                return
            self._stop_event.set()
            self._started = False
            self._thread = None

    def get_runs(self, query=None):
        """Retrieves cached runs, ensuring directory freshness."""
        self.update_cache()
        with self._lock:
            results = list(self._runs)

        if query:
            query = query.lower()
            results = [
                r
                for r in results
                if query in r["run_id"].lower() or query in r.get("scenario", "").lower()
            ]
        return results

    def _update_loop(self):
        # Initial scan
        try:
            self.update_cache()
        except Exception as e:
            logger.warning(f"Error in initial runs cache scan: {e}")

        while not self._stop_event.is_set():
            time.sleep(1.0)
            try:
                self.update_cache()
            except Exception as e:
                logger.warning(f"Error in runs cache background update: {e}")

    def update_cache(self):
        """Scans RUN_LOG_DIR differentially for changes."""
        from eval_runner import config

        if not config.RUN_LOG_DIR or not config.RUN_LOG_DIR.exists():
            with self._lock:
                self._runs = []
                self._scanned_files = {}
                self._last_dir = config.RUN_LOG_DIR
            return

        with self._lock:
            # If the monitored directory path changed (e.g. reconfigured in runtime), reset state
            if self._last_dir != config.RUN_LOG_DIR:
                self._runs = []
                self._scanned_files = {}
                self._last_dir = config.RUN_LOG_DIR

        new_runs_map = {}
        changes = False

        # 1. Scan direct fragments (.jsonl files)
        for p in config.RUN_LOG_DIR.glob("*.jsonl"):
            try:
                mtime = p.stat().st_mtime
                cached_mtime = self._scanned_files.get(str(p))
                if cached_mtime == mtime:
                    continue

                changes = True
                self._scanned_files[str(p)] = mtime

                with open(p, encoding="utf-8") as f:
                    for line in f:
                        line_str = line.strip()
                        if not line_str:
                            continue
                        try:
                            event = json.loads(line_str)
                            if event.get("event") == "run_start":
                                rid = event.get("run_id") or ""
                                scenario = event.get("scenario") or ""
                                timestamp = event.get("timestamp") or event.get("_ts_iso") or ""
                                new_runs_map[rid] = {
                                    "run_id": rid,
                                    "scenario": scenario,
                                    "timestamp": timestamp,
                                    "_fragment_path": str(p.relative_to(config.RUN_LOG_DIR)),
                                }
                        except Exception as e:
                            logger.debug(f"Parsing run line warning: {e}")
                            continue
            except Exception as e:
                logger.debug(f"Parsing fragment warning: {e}")
                continue

        # 2. Scan vault folders (*/run.jsonl)
        for p in config.RUN_LOG_DIR.glob("*/run.jsonl"):
            try:
                mtime = p.stat().st_mtime
                cached_mtime = self._scanned_files.get(str(p))
                if cached_mtime == mtime:
                    continue

                changes = True
                self._scanned_files[str(p)] = mtime

                with open(p, encoding="utf-8") as f:
                    first_line = f.readline()
                    if not first_line.strip():
                        continue
                    event = json.loads(first_line)
                    rid = event.get("run_id") or p.parent.name or ""
                    scenario = event.get("scenario")

                    # [G5] Primary identifiers: agent identity + terminal
                    # result/duration from the authoritative run_end event.
                    identifier = event.get("identifier") or ""
                    duration_seconds = None
                    result_status = None
                    # Capture execution_mode from the run_start event so list endpoints
                    # can surface it without a per-row truth-level lookup.
                    execution_mode_cached = (
                        event.get("execution_mode")
                        or (event.get("data") or {}).get("execution_mode")
                        or (event.get("metadata") or {}).get("execution_mode")
                    )
                    if p.stat().st_size < 512 * 1024:
                        lines = f.readlines()
                        for ln in reversed(lines):
                            ln = ln.strip()
                            if not ln:
                                continue
                            try:
                                last_ev = json.loads(ln)
                            except Exception:
                                continue
                            if last_ev.get("event") == "run_end":
                                data_block = last_ev.get("data", {})
                                duration_seconds = data_block.get("duration")
                                result_status = "PASS" if data_block.get("passed") else "FAIL"
                            break

                    if not scenario and rid.startswith("run-"):
                        parts = rid.split("-")
                        if len(parts) > 2:
                            scenario = "-".join(parts[1:-1])
                        else:
                            scenario = parts[1]
                    elif not scenario:
                        scenario = rid

                    scenario = scenario or ""
                    timestamp = event.get("timestamp") or event.get("_ts_iso") or ""
                    new_runs_map[rid] = {
                        "run_id": rid,
                        "scenario": scenario,
                        "timestamp": timestamp,
                        "path": str(p.relative_to(config.RUN_LOG_DIR)),
                        "identifier": identifier,
                        "duration_seconds": duration_seconds,
                        "result_status": result_status,
                        "execution_mode": execution_mode_cached,
                    }
            except Exception as e:
                logger.debug(f"Parsing vault run warning: {e}")
                continue

        if changes or new_runs_map or True:  # Always audit cache integrity
            with self._lock:
                # Merge new runs into existing runs
                existing_map = {r["run_id"]: r for r in self._runs}
                existing_map.update(new_runs_map)

                # Filter out runs that no longer exist on disk
                pruned_map = {}
                for rid, r in existing_map.items():
                    path_val = r.get("path") or r.get("_fragment_path")
                    if path_val:
                        tp = config.RUN_LOG_DIR / path_val
                    else:
                        tp = resolve_trace_path(rid)
                    if tp and tp.exists():
                        pruned_map[rid] = r

                # Sort runs by timestamp descending
                sorted_runs = list(pruned_map.values())
                sorted_runs.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)

                # Cap the cache to the most recent 500 runs
                self._runs = sorted_runs[:500]
                self._last_scan_time = time.time()


# Thread-safe runs cache instance
runs_cache = RunsCache()


@run_bp.route("/runs", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def list_runs():
    """Returns a list of recent run traces (Consolidated).

    Every row carries a server-authoritative ``verification_status``
    computed by comparing the certificate/manifest trace_hash against the
    CURRENT trace bytes (SHA3-256). Presence of a certificate alone is never
    treated as proof; unverifiable runs report UNKNOWN.
    """
    query = request.args.get("q", "").lower()
    runs = runs_cache.get_runs(query=query)
    enriched = []
    for run in runs[:200]:
        rid = run.get("run_id") or ""
        summary = RunSummaryService.compute_summary(rid, cached_entry=run)
        enriched.append(summary)
    return jsonify({"runs": enriched})


def _authoritative_verdict(run_id: str) -> str:
    """
    Authoritative verification computation. Full literal set:
        VERIFIED | VERIFIED_PROVISIONAL | FAILED_VERIFICATION | NOT_EXECUTED | ERROR | UNKNOWN
    """
    return RunSummaryService.get_authoritative_verdict(run_id)


@run_bp.route("/v1/runs/stream-list", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def stream_runs_list():
    """Streams the run list incrementally in chunks every 1 second (SSE)."""

    def generate():
        runs = runs_cache.get_runs()
        chunk_size = 10  # Yield 10 runs at a time
        for i in range(0, len(runs), chunk_size):
            chunk = runs[i : i + chunk_size]
            resolved_chunk = []
            for run in chunk:
                run_id = run["run_id"]
                summary = RunSummaryService.compute_summary(run_id, cached_entry=run)
                resolved_chunk.append(
                    {
                        "run_id": run_id,
                        "scenario": summary.get("scenario", run.get("scenario")),
                        "timestamp": summary.get("timestamp", run.get("timestamp")),
                        "status": summary["status"],
                        "lifecycle": summary["lifecycle"],
                        "verification_status": summary["verification_status"],
                        "trace_integrity": summary["trace_integrity"],
                        "execution_mode": summary["execution_mode"],
                        "provisional": summary["provisional"],
                    }
                )
            yield f"data: {json.dumps(resolved_chunk)}\n\n"
            time.sleep(1.0)

    return Response(generate(), mimetype="text/event-stream")


@run_bp.route("/v1/runs/<path:run_id>", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_run_status(run_id):
    """Industrial Polling Primitive."""
    vault_trace = resolve_trace_path(run_id)
    scenario_data = None

    if vault_trace:
        is_finished = False
        size = 0
        mtime = 0
        try:
            size = os.path.getsize(vault_trace)
            mtime = os.path.getmtime(vault_trace)
            window = 128 * 1024
            with open(vault_trace, "rb") as f:
                if size <= window:
                    raw_bytes = f.read()
                else:
                    f.seek(size - window)
                    raw_bytes = f.read()

            tail_text = raw_bytes.decode("utf-8", errors="replace")
            for line in tail_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if not line.startswith("{"):
                    idx = line.find("{")
                    if idx != -1:
                        line = line[idx:]
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                event_type = ev.get("event")
                if event_type in ("run_end", "session_decision", "evaluation_result"):
                    is_finished = True
                    data = ev.get("data", {}) or {}
                    raw_status = data.get("status") or ev.get("status") or ""
                    if str(raw_status).lower() in ("fail", "failed", "failure", "error"):
                        pass
                elif event_type in ("verification_certificate_issued", "trace_sealed"):
                    is_finished = True
        except Exception as e:
            logger.warning(f"Error parsing run trace for status of {run_id}: {e}")

        summary = RunSummaryService.compute_summary(run_id)
        status = "COMPLETED" if summary["status"] == "PASSED" else summary["status"]

        resolved_scen_path = config.RUN_LOG_DIR / run_id / "scenario_resolved.json"
        orig_scen_path = config.RUN_LOG_DIR / run_id / "scenario_original.json"
        for path_cand in [resolved_scen_path, orig_scen_path]:
            if path_cand.exists():
                try:
                    with open(path_cand, encoding="utf-8") as f_scen:
                        scenario_data = json.load(f_scen)
                        break
                except Exception as e:
                    logger.debug(f"Error parsing resolved scenario: {e}")

        return jsonify(
            {
                "run_id": run_id,
                "status": status,
                "size": size,
                "mtime": mtime,
                "has_certificate": summary["has_certificate"],
                "sourced_from_master": False,
                "scenario": scenario_data,
                "execution_mode": summary["execution_mode"],
                "provisional": summary["provisional"],
                "verification_status": summary["verification_status"],
            }
        )

    # Fallback: scan master log runs/run.jsonl for presence of this run_id
    master_log = config.RUN_LOG_DIR / "run.jsonl"
    if master_log.exists():
        is_finished = False
        has_events = False
        try:
            with open(master_log, encoding="utf-8") as f:
                for line in f:
                    if f'"{run_id}"' in line:
                        try:
                            ev = json.loads(line.strip())
                            if ev.get("run_id") == run_id:
                                has_events = True
                                if ev.get("event") in [
                                    "run_end",
                                    "verification_certificate_issued",
                                ]:
                                    is_finished = True
                        except Exception as e:
                            logger.debug(f"Parsing run line warning: {e}")
        except Exception as e:
            logger.warning(f"Error checking run status in master log: {e}")

        if has_events:
            status = "COMPLETED" if is_finished else "RUNNING"
            if not is_finished and not is_run_alive(run_id):
                status = "STALLED"

            scenario = None
            if run_id.startswith("run-"):
                parts = run_id.split("-")
                if len(parts) > 2:
                    scenario = "-".join(parts[1:-1])
                else:
                    scenario = parts[1]
            else:
                scenario = run_id

            scenario_data = None
            if scenario:
                from eval_runner.catalog import ScenarioCatalog

                catalog = ScenarioCatalog.get_instance()
                scen_rec = catalog.get_scenario(scenario)
                if scen_rec:
                    abs_path = catalog.get_absolute_path(scen_rec["id"])
                    if abs_path and abs_path.exists():
                        try:
                            with open(abs_path, encoding="utf-8") as f_scen:
                                scenario_data = json.load(f_scen)
                        except Exception as e:
                            logger.debug(f"Error parsing scenario from catalog: {e}")

            cert_path = config.REPORTS_DIR / "certificates" / f"{run_id}_vc.json"
            # O1 fix: same truth-level enrichment as the vault branch.
            em_ml, prov_ml = CertificationService.read_run_truth_level(run_id)
            return jsonify(
                {
                    "run_id": run_id,
                    "status": status,
                    "size": os.path.getsize(master_log),
                    "mtime": os.path.getmtime(master_log),
                    "has_certificate": cert_path.exists(),
                    "sourced_from_master": True,
                    "scenario": scenario_data,
                    "execution_mode": em_ml,
                    "provisional": prov_ml,
                    "verification_status": _authoritative_verdict(run_id),
                }
            )

    # Check active execution backend in-memory state before returning 404
    try:
        from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

        backend = InProcessExecutionBackend.get_instance()
        st = backend.status(run_id)
        if st and st.get("status") != "UNKNOWN":
            return jsonify(
                {
                    "run_id": run_id,
                    "status": st.get("status"),
                    "size": 0,
                    "mtime": 0,
                    "has_certificate": False,
                    "sourced_from_master": False,
                    "scenario": st.get("scenario_data"),
                }
            )
    except Exception as e:
        logger.debug(f"Backend status query error: {e}")

    return jsonify({"error": "Run not found"}), 404


@run_bp.route("/v1/runs/<path:run_id>/cancel", methods=["POST"])
@require_permission(Permission.RUNS_WRITE)
def cancel_run(run_id):
    """Cancels an active execution run via ExecutionBackend."""
    from eval_runner.reference.inprocess_backend import get_execution_backend

    data = request.json or {}
    reason = data.get("reason", "Cancelled via Console API")
    backend = get_execution_backend()
    success = backend.cancel(run_id, reason=reason)
    if not success:
        return (
            jsonify(
                {
                    "error": f"Run '{run_id}' is not active or could not be cancelled",
                    "run_id": run_id,
                }
            ),
            404,
        )
    return jsonify({"status": "ABORTED", "run_id": run_id, "reason": reason})


@run_bp.route("/v1/runs/<path:run_id>/resume", methods=["POST"])
@require_permission(Permission.RUNS_WRITE)
def resume_run(run_id):
    """Resumes a paused or checkpointed evaluation run via ExecutionBackend."""
    from eval_runner.reference.inprocess_backend import get_execution_backend

    data = request.json or {}
    resumption_token = data.get("resumption_token")
    backend = get_execution_backend()
    resumed = backend.resume(run_id, resumption_token=resumption_token, background=True)
    if resumed is None:
        return (
            jsonify(
                {
                    "error": f"No checkpoint found to resume run '{run_id}'",
                    "run_id": run_id,
                }
            ),
            404,
        )
    return jsonify({"status": "RUNNING", "run_id": run_id, "result": resumed})


@run_bp.route("/v1/certificates/<run_id>", methods=["GET"])
def get_verification_certificate(run_id):
    """Public Trust Protocol endpoint."""
    from eval_runner.verifier import locate_certificate_file

    cert_path = locate_certificate_file(run_id)
    if cert_path and cert_path.exists():
        try:
            with open(cert_path, encoding="utf-8") as f:
                return jsonify(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Corrupt certificate file {cert_path}: {e}")
            if cert_path.name.endswith("run_manifest.json"):
                return jsonify({"error": "Corrupt manifest found"}), 500
            return jsonify({"error": "Corrupt certificate found"}), 500
    return jsonify({"error": "Certificate not found"}), 404


def is_run_alive(run_id: str) -> bool:
    """Helper to detect if the runner is active in the process space."""
    return any(t.name == f"eval-{run_id}" for t in threading.enumerate())


TERMINAL_TRACE_EVENTS = {
    "run_end",
    "run_completed",
    "trace_sealed",
    "verification_certificate_issued",
    "certification_failed",
}


def _extract_canonical_event_info(line: str, fallback_seq: int) -> tuple[int, bool]:
    """
    Extracts authoritative event _seq and checks if terminal from raw JSONL line.
    Never regenerates forensic identity at read time.
    """
    try:
        ev = json.loads(line)
    except Exception:
        ev = None

    if isinstance(ev, dict):
        raw_seq = ev.get("_seq")
        if raw_seq is None:
            raw_seq = ev.get("seq_id") or ev.get("id")
        if raw_seq is not None:
            try:
                seq = int(raw_seq)
            except (ValueError, TypeError):
                seq = fallback_seq
        else:
            seq = fallback_seq

        ev_name = str(ev.get("event") or "")
        is_term = ev_name in TERMINAL_TRACE_EVENTS
        return seq, is_term

    is_term = any(f'"event": "{name}"' in line for name in TERMINAL_TRACE_EVENTS)
    return fallback_seq, is_term


def tail_file_generator(
    log_path: Path, run_id: str, last_event_id: int = 0, target_run_id: str | None = None
):
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
    seq_id = 0

    # 2. Open and Stream with Catch-up Replay
    try:
        f = open(log_path, encoding="utf-8")
    except OSError as e:
        logger.warning(f"[Streaming] Failed to open {log_path} for tailing: {e}")
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        return

    with f:
        # Step A: Stream historical events, skipping events received before last_event_id.
        # Contract: an unterminated trailing line (mid-write) is NEVER broadcast.
        # We rewind to its start offset so the tail loop re-reads it once the
        # writer has flushed the complete JSONL frame.
        matched_any = False
        while True:
            try:
                pos = f.tell()
            except OSError:
                pos = None
            line = f.readline()
            if not line:
                break
            if not line.endswith("\n"):
                if pos is not None:
                    f.seek(pos)
                break
            stripped = line.strip()
            if stripped:
                if target_run_id:
                    try:
                        ev = json.loads(stripped)
                        if ev.get("run_id") != target_run_id:
                            continue
                    except Exception:
                        continue
                matched_any = True
                seq_id += 1
                _, is_term = _extract_canonical_event_info(stripped, seq_id)
                if seq_id > last_event_id:
                    yield f"id: {seq_id}\ndata: {stripped}\n\n"
                if is_term:
                    return

        # If target_run_id specified, but no events exist and process is dead, return not_found
        if target_run_id and not matched_any and not is_run_alive(target_run_id):
            payload = json.dumps(
                {
                    "event": "not_found",
                    "message": "Execution log file not found. Waiting for trace data.",
                }
            )
            yield f"data: {payload}\n\n"
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

            try:
                pos = f.tell()
            except OSError:
                pos = None
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

            # Contract: a line not yet terminated by its writer is never
            # broadcast. Rewind so the complete frame can be re-read intact.
            if pos is not None and not line.endswith("\n"):
                f.seek(pos)
                time.sleep(0.1)
                continue

            idle_cycles = 0
            stripped = line.strip()
            if stripped:
                if target_run_id:
                    try:
                        ev = json.loads(stripped)
                        if ev.get("run_id") != target_run_id:
                            continue
                    except Exception:
                        continue
                seq_id += 1
                _, is_term = _extract_canonical_event_info(stripped, seq_id)
                if seq_id > last_event_id:
                    yield f"id: {seq_id}\ndata: {stripped}\n\n"
                if is_term:
                    break


@run_bp.route("/v1/runs/<path:run_id>/stream", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def stream_run_logs(run_id):
    """SSE streaming endpoint for live run traces with Last-Event-ID replay support."""
    last_id_str = (
        request.headers.get("Last-Event-ID")
        or request.args.get("last_event_id")
        or request.args.get("since")
    )
    try:
        last_event_id = int(last_id_str) if last_id_str is not None else 0
    except (ValueError, TypeError):
        last_event_id = 0

    log_path = resolve_trace_path(run_id)
    if log_path:
        return Response(
            tail_file_generator(log_path, run_id, last_event_id=last_event_id),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # Fallback: stream matching events from master log runs/run.jsonl directly
    master_log = config.RUN_LOG_DIR / "run.jsonl"
    if master_log.exists():
        return Response(
            tail_file_generator(
                master_log, run_id, target_run_id=run_id, last_event_id=last_event_id
            ),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    def stream_not_found():
        import json as _json

        payload = _json.dumps(
            {
                "event": "not_found",
                "message": "Execution log file not found. Waiting for trace data.",
            }
        )
        yield f"data: {payload}\n\n"

    return Response(stream_not_found(), mimetype="text/event-stream")


@run_bp.route("/v1/runs/<path:run_id>/verify", methods=["GET", "POST"])
@require_permission(Permission.RUNS_READ)
def verify_run(run_id):
    """Server-Authoritative Cryptographic Verification Endpoint."""
    from eval_runner.verifier import TraceVerifier

    run_dir = config.RUN_LOG_DIR / run_id
    res = TraceVerifier.verify_run_directory(run_dir)
    status_code = 404 if res.get("verification_status") == "NOT_FOUND" else 200
    return jsonify(res), status_code
