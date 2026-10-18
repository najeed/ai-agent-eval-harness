import json
import logging
import os
import tempfile
import threading
import time
from io import BytesIO
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_file

from eval_runner import config
from eval_runner.explainer import explain_trace
from eval_runner.metrics import MetricRegistry
from eval_runner.run_index import read_run_index
from eval_runner.services.certification import CertificationService
from eval_runner.services.run_summary import RunSummaryService
from eval_runner.storage_resolver import resolve_run_storage_provider

from ..auth_manager import (
    Permission,
    active_runtime_context,
    require_permission,
    require_sse_permission,
)

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


def _run_is_in_active_context(run_id: str, context: dict[str, str] | None = None) -> bool:
    """Hide a run when the authoritative provider denies the active scope."""
    if context is None:
        context = active_runtime_context()
    if context is None:
        return True
    return _active_run_store().get_run(run_id, context=context) is not None


def _summary_from_provider(run: dict) -> dict:
    """Use provider-native summaries for remote stores; local stores retain forensic enrichment."""
    if run.get("vault_path"):
        return RunSummaryService.compute_summary(run["run_id"], cached_entry=run)
    manifest = run.get("manifest") or {}
    status = str(run.get("status") or manifest.get("status") or "OPEN").upper()
    return {
        **run,
        "scenario": run.get("scenario") or run.get("scenario_id"),
        "timestamp": run.get("created_at") or run.get("timestamp"),
        "status": status,
        "lifecycle": run.get("lifecycle") or status,
        "verification_status": run.get("verification_status", "UNKNOWN"),
        "trace_integrity": run.get("trace_integrity", "PROVIDER_MANAGED"),
        "execution_mode": run.get("execution_mode") or manifest.get("execution_mode"),
        "provisional": bool(run.get("provisional", False)),
        "score_reason": run.get("score_reason"),
        "score_category": run.get("score_category"),
        "failure_reasons": run.get("failure_reasons", []),
        "failed_oracles": run.get("failed_oracles", []),
    }


@run_bp.route("/v1/explain/<run_id>", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def explain_run(run_id):
    """Roadmap: Forensic RCA as a service."""
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Not found"}), 404
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
        events = _active_run_store().get_events(
            run_id, offset=0, limit=10_000_000, context=active_runtime_context()
        )
        if events:
            import uuid

            temp_path = config.RUN_LOG_DIR / f"temp_explain_{run_id}_{uuid.uuid4().hex}.jsonl"
            try:
                with open(temp_path, "w", encoding="utf-8") as out:
                    for ev in events:
                        out.write(json.dumps(ev, default=str, separators=(",", ":")) + "\n")
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


def _active_run_store():
    """Resolve the process-wide authoritative run storage provider."""
    return resolve_run_storage_provider()


@run_bp.route("/runs", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def list_runs():
    """Returns a list of recent run traces (Consolidated).

    Every row carries a server-authoritative ``verification_status``
    computed by comparing the certificate/manifest trace_hash against the
    CURRENT trace bytes (SHA3-256). Presence of a certificate alone is never
    treated as proof; unverifiable runs report UNKNOWN.
    """
    query = request.args.get("q", "")
    runs = _active_run_store().search_runs(query=query, limit=200, context=active_runtime_context())
    enriched = []
    for run in runs[:200]:
        rid = run.get("run_id") or ""
        if not _run_is_in_active_context(rid):
            continue
        summary = _summary_from_provider(run)
        enriched.append(summary)
    return jsonify({"runs": enriched})


def _authoritative_verdict(run_id: str) -> str:
    """
    Authoritative verification computation. Full literal set:
        VERIFIED | VERIFIED_PROVISIONAL | FAILED_VERIFICATION | NOT_EXECUTED | ERROR | UNKNOWN
    """
    return RunSummaryService.get_authoritative_verdict(run_id)


@run_bp.route("/v1/runs/stream-list", methods=["GET"])
@require_sse_permission(Permission.RUNS_READ)
def stream_runs_list():
    """Streams the run list incrementally in chunks every 1 second (SSE)."""
    request_context = active_runtime_context()

    def generate():
        runs = _active_run_store().list_runs(limit=200, context=request_context)
        chunk_size = 10  # Yield 10 runs at a time
        for i in range(0, len(runs), chunk_size):
            chunk = runs[i : i + chunk_size]
            resolved_chunk = []
            for run in chunk:
                run_id = run["run_id"]
                if request_context is not None and not _run_is_in_active_context(
                    run_id, request_context
                ):
                    continue
                summary = _summary_from_provider(run)
                resolved_chunk.append(
                    {
                        "run_id": run_id,
                        "scenario": summary.get("scenario", run.get("scenario")),
                        "timestamp": summary.get("timestamp", run.get("timestamp")),
                        "start_time": summary.get("timestamp", run.get("timestamp")),
                        "identifier": summary.get("identifier")
                        or run.get("identifier")
                        or summary.get("timestamp"),
                        "status": summary["status"],
                        "lifecycle": summary["lifecycle"],
                        "verification_status": summary["verification_status"],
                        "trace_integrity": summary["trace_integrity"],
                        "execution_mode": summary["execution_mode"],
                        "provisional": summary["provisional"],
                        "duration_seconds": summary.get("duration_seconds"),
                        "score": summary.get("score"),
                    }
                )
            yield f"data: {json.dumps(resolved_chunk)}\n\n"
            time.sleep(1.0)

    return Response(generate(), mimetype="text/event-stream")


@run_bp.route("/v1/runs/<path:run_id>/report.pdf", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def download_run_report_pdf(run_id: str):
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Not found"}), 404
    """Generate a human-readable PDF report without mutating the sealed run vault."""
    trace_path = resolve_trace_path(run_id)
    if trace_path is None or not trace_path.exists():
        run = _active_run_store().get_run(run_id, context=active_runtime_context())
        if run is None:
            return jsonify({"error": "Run not found"}), 404
        summary = _summary_from_provider(run)
    else:
        summary = RunSummaryService.compute_summary(run_id)

    from eval_runner.console.pdf_service import generate_run_pdf

    report_data = {
        **summary,
        "run_id": run_id,
        "passed": summary["status"] in {"CERTIFIED", "SEALED", "PASSED"},
        "has_certificate": summary["has_certificate"],
        "is_certified": summary["status"] == "CERTIFIED",
        "verification_status": summary["verification_status"],
    }

    # The report is a derived presentation artifact.  It must never be written
    # into an evidence vault, particularly after the certification seal.
    with tempfile.TemporaryDirectory(prefix="agentv-run-report-") as temp_dir:
        report_path = Path(temp_dir) / "report.pdf"
        if not generate_run_pdf(report_data, report_path) or not report_path.exists():
            logger.error("Could not generate PDF report for run %s", run_id)
            return jsonify({"error": "PDF report generation failed"}), 503

        report_bytes = report_path.read_bytes()

    if not report_bytes.startswith(b"%PDF-"):
        logger.error("PDF generator produced a non-PDF artifact for run %s", run_id)
        return jsonify({"error": "No PDF rendering engine is available"}), 503

    return send_file(
        BytesIO(report_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{run_id}-compliance-report.pdf",
    )


@run_bp.route("/v1/runs/<path:run_id>", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_run_status(run_id):
    """Industrial Polling Primitive."""
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Not found"}), 404
    store = _active_run_store()
    context = active_runtime_context()
    run = store.get_run(run_id, context=context)
    if run is not None and not run.get("vault_path"):
        events = store.get_events(run_id, offset=0, limit=10_000_000, context=context)
        manifest = store.get_manifest(run_id, context=context) or run.get("manifest") or {}
        summary = _summary_from_provider(run)
        event_count = len(events)
        terminal_events = {
            "run_end",
            "session_decision",
            "evaluation_result",
            "verification_certificate_issued",
            "trace_sealed",
        }
        terminal = any(event.get("event") in terminal_events for event in events)
        raw_status = str(run.get("status") or manifest.get("status") or "OPEN").upper()
        if terminal and raw_status in {"OPEN", "RUNNING"}:
            status = "COMPLETED"
        elif raw_status == "OPEN" and events:
            status = "RUNNING"
        else:
            status = raw_status
        scenario = manifest.get("scenario_data") or run.get("scenario_data")
        return jsonify(
            {
                "run_id": run_id,
                "status": status,
                "size": event_count,
                "mtime": run.get("updated_at") or run.get("created_at"),
                "has_certificate": bool(manifest.get("verification_package")),
                "sourced_from_master": False,
                "scenario": scenario,
                "execution_mode": summary.get("execution_mode") or manifest.get("execution_mode"),
                "provisional": bool(summary.get("provisional", manifest.get("provisional", False))),
                "verification_status": summary.get("verification_status", "PROVIDER_MANAGED"),
                "duration_seconds": summary.get("duration_seconds"),
                "score": summary.get("score") or (manifest.get("compliance") or {}).get("score"),
                "score_reason": summary.get("score_reason"),
                "score_category": summary.get("score_category"),
                "failure_reasons": summary.get("failure_reasons", []),
                "failed_oracles": summary.get("failed_oracles", []),
                "timestamp": summary.get("timestamp") or run.get("created_at"),
                "start_time": summary.get("timestamp") or run.get("created_at"),
                "identifier": summary.get("identifier") or run.get("run_id"),
            }
        )

    index_record = read_run_index(run_id)
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
                "duration_seconds": summary.get("duration_seconds"),
                "score": summary.get("score"),
                "score_reason": summary.get("score_reason"),
                "score_category": summary.get("score_category"),
                "failure_reasons": summary.get("failure_reasons", []),
                "failed_oracles": summary.get("failed_oracles", []),
                "timestamp": summary.get("timestamp"),
                "start_time": summary.get("timestamp"),
                "identifier": summary.get("identifier") or summary.get("timestamp"),
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

    # Durable acceptance record survives restarts and provides an immediate,
    # stable representation before any trace artifact exists.
    if index_record is not None:
        return jsonify(
            {
                "run_id": run_id,
                "status": index_record.get("status", "PENDING"),
                "size": 0,
                "mtime": 0,
                "has_certificate": False,
                "sourced_from_master": False,
                "scenario": None,
                "provisional": True,
                "verification_status": "NOT_EXECUTED",
                "timestamp": index_record.get("created_at"),
                "start_time": index_record.get("created_at"),
                "identifier": index_record.get("scenario_id"),
            }
        )

    # Check active execution backend in-memory state before returning 404
    try:
        from agentv_runtime.discovery import resolve_extension
        from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

        backend = resolve_extension(
            "execution_backends",
            default_factory=InProcessExecutionBackend.get_instance,
        )
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
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Not found"}), 404
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
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Not found"}), 404
    """Resumes a paused or checkpointed evaluation run via ExecutionBackend."""
    from eval_runner.reference.approval_store import get_default_approval_store
    from eval_runner.reference.inprocess_backend import get_execution_backend
    from eval_runner.session_components.approval_manager import SessionApprovalManager

    data = request.json or {}
    resumption_token = data.get("resumption_token") or data.get("approval_token")
    decision = (data.get("decision") or "APPROVED").upper()
    reviewer = data.get("reviewer") or "console_user"
    reviewer_role = data.get("reviewer_role")
    reviewer_credentials = data.get("reviewer_credentials") or {}
    reason = data.get("reason")

    if decision not in {"APPROVED", "REJECTED"}:
        return jsonify({"error": "decision must be APPROVED or REJECTED"}), 400
    if not resumption_token:
        return jsonify({"error": "A durable approval token is required to resume a run"}), 400

    store = get_default_approval_store()
    req = store.get_request(resumption_token)
    if not req:
        return jsonify({"error": "Approval token was not found"}), 404
    if req.run_id != run_id:
        return jsonify({"error": "Approval token is not bound to this run"}), 409
    if req.status != "PENDING":
        return jsonify({"error": "Approval token has already been resolved"}), 409
    if req.required_role and reviewer_role != req.required_role:
        return jsonify({"error": "Reviewer role does not satisfy the approval requirement"}), 403
    if req.reviewer_credentials and reviewer_credentials != req.reviewer_credentials:
        return jsonify(
            {"error": "Reviewer credentials do not satisfy the approval requirement"}
        ), 403

    try:
        # Keep all durable approval resolutions on the runtime's generic
        # approval boundary.  This ensures the same interceptor checks apply
        # to Console, CLI, and in-session resumption paths.
        from eval_runner import plugins

        SessionApprovalManager(
            run_id=run_id,
            approval_store=store,
            plugin_manager=plugins.manager,
        ).resolve_durable_request(
            approval_token=resumption_token,
            decision=decision,
            decided_by=reviewer,
            decision_reason=reason,
        )
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except (KeyError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 409
    if decision == "REJECTED":
        return jsonify(
            {
                "status": "REJECTED",
                "run_id": run_id,
                "approval_token": resumption_token,
                "reason": reason or "Rejected via review gate",
            }
        )

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
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Not found"}), 404
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
@require_sse_permission(Permission.RUNS_READ)
def stream_run_logs(run_id):
    """SSE streaming endpoint for live run traces with Last-Event-ID replay support."""
    req_context = active_runtime_context()
    if not _run_is_in_active_context(run_id, req_context):
        return jsonify({"error": "Not found"}), 404
    last_id_str = (
        request.headers.get("Last-Event-ID")
        or request.args.get("last_event_id")
        or request.args.get("since")
    )
    try:
        last_event_id = int(last_id_str) if last_id_str is not None else 0
    except (ValueError, TypeError):
        last_event_id = 0

    provider = _active_run_store()
    run_record = provider.get_run(run_id, context=req_context)
    log_path = resolve_trace_path(run_id)
    has_trace = bool(
        (run_record and run_record.get("has_trace")) or (log_path and log_path.exists())
    )

    def provider_events():
        next_offset = last_event_id
        for _ in range(300):  # Five-minute bounded connection; clients may reconnect.
            emitted = False
            for index, event in enumerate(
                provider.stream_events(run_id, from_seq=next_offset, context=req_context),
                start=next_offset + 1,
            ):
                event_id = int(event.get("_seq", index))
                next_offset = max(next_offset + 1, event_id)
                emitted = True
                yield f"id: {event_id}\ndata: {json.dumps(event)}\n\n"
                if event.get("event") in TERMINAL_TRACE_EVENTS:
                    return
            record = provider.get_run(run_id, context=req_context) or {}
            terminal_states = {
                "SEALED",
                "FAILED",
                "CANCELLED",
                "COMPLETED",
                "PASSED",
                "PASS",
                "FAIL",
            }
            if str(record.get("status", "")).upper() in terminal_states:
                return
            if not emitted and not is_run_alive(run_id):
                return
            if not emitted:
                yield ": heartbeat\n\n"
            time.sleep(1.0)

    if has_trace:
        return Response(
            provider_events(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    master_log = config.RUN_LOG_DIR / "run.jsonl"
    if master_log.exists():
        has_master_events = False
        try:
            with open(master_log, encoding="utf-8") as mf:
                for line in mf:
                    if f'"{run_id}"' in line:
                        has_master_events = True
                        break
        except Exception as exc:
            logger.debug(f"Failed scanning master log for run '{run_id}': {exc}")
        if has_master_events:
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
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Not found"}), 404
    from eval_runner.verifier import TraceVerifier

    run_dir = config.RUN_LOG_DIR / run_id
    res = TraceVerifier.verify_run_directory(run_dir)
    status_code = 404 if res.get("verification_status") == "NOT_FOUND" else 200
    return jsonify(res), status_code
