import json
import logging
import os
import tempfile
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, request, send_file

from agentv_runtime.discovery import get_registered_extension, set_extension
from agentv_runtime.manifest import resolve_artifact_scope
from eval_runner.explainer import explain_events
from eval_runner.metrics import MetricRegistry

from ..auth_manager import (
    Permission,
    active_runtime_context,
    active_runtime_scope,
    require_permission,
    require_sse_permission,
)
from ..providers import get_run_store

logger = logging.getLogger(__name__)

run_bp = Blueprint("runs", __name__)

_report_action_provider: Any = None


def register_report_action_provider(provider: Any) -> None:
    """Register an optional governed report-action provider for Console run views."""
    global _report_action_provider
    set_extension("report_action_provider", provider)
    _report_action_provider = provider


def resolve_run_report_actions(
    run_id: str, context: dict[str, str] | None = None
) -> dict[str, Any]:
    """
    Resolve the active report download actions for a run
    (basic fallback if no provider is registered).
    """
    provider = _report_action_provider
    if provider is None:
        provider = get_registered_extension("report_action_provider")
    if callable(provider):
        try:
            try:
                resolved = provider(run_id, context)
            except TypeError:
                resolved = provider(run_id)
            if isinstance(resolved, dict) and (
                resolved.get("download_url") or resolved.get("href")
            ):
                if "download_url" not in resolved and "href" in resolved:
                    resolved["download_url"] = resolved["href"]
                return resolved
        except Exception as exc:
            logger.debug("Report action provider failed for %s: %s", run_id, exc, exc_info=True)
    default_href = f"/api/v1/runs/{run_id}/report.pdf"
    return {
        "mode": "basic",
        "label": "Download Basic Run Report (PDF)",
        "download_url": default_href,
        "href": default_href,
        "default_profile": "basic",
        "profiles": [
            {
                "id": "basic",
                "label": "Basic Compliance Report (PDF)",
                "description": "Human-readable summary derived from this run's evidence.",
                "href": default_href,
            }
        ],
    }


@run_bp.route("/v1/metrics", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def list_metrics():
    """Roadmap: List registered evaluation metrics."""
    return jsonify({"metrics": MetricRegistry.list_metrics()})


def _run_is_in_active_context(run_id: str, context: dict[str, str] | None = None) -> bool:
    """Hide a run when the authoritative provider denies the active scope."""
    if context is None:
        context = active_runtime_context()
    if context is not None:
        return _active_run_store().get_run(run_id, context=context) is not None
    run = _active_run_store().get_run(run_id)
    if run is None:
        return False
    run_context = run.get("context") or (run.get("metadata") or {}).get("runtime_context")
    if isinstance(run_context, dict) and any(
        run_context.get(k) for k in ("org_id", "tenant_id", "workspace_id")
    ):
        return False
    return True


def _finalization_from_events(events: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Return the signed finalization payload from its canonical trace carrier."""
    for event in reversed(events or []):
        event_name = event.get("event")
        event_data = event.get("data") if isinstance(event.get("data"), dict) else event
        if event_name == "evaluator_finalization" and isinstance(event_data, dict):
            return event_data
        if event_name in {"run_end", "end"}:
            finalization = event_data.get("finalization")
            if isinstance(finalization, dict):
                return finalization
            finalization = event.get("finalization")
            if isinstance(finalization, dict):
                return finalization
    return {}


def _summary_from_provider(run: dict, events: list[dict[str, Any]] | None = None) -> dict:
    """Build a console summary exclusively from provider-owned metadata."""
    manifest = run.get("manifest") or {}
    execution_manifest = manifest.get("execution_manifest") or {}
    if not isinstance(execution_manifest, dict):
        execution_manifest = {}
    runtime_config = execution_manifest.get("runtime_config") or {}
    if not isinstance(runtime_config, dict):
        runtime_config = {}
    agent_config = execution_manifest.get("agent_config") or {}
    if not isinstance(agent_config, dict):
        agent_config = {}
    compliance = manifest.get("compliance") or {}
    package = manifest.get("verification_package") or {}
    finalization = _finalization_from_events(events)
    oracle_results = package.get("executed_oracle_results") or []
    failed_oracles = [
        result
        for result in oracle_results
        if isinstance(result, dict)
        and (result.get("passed") is False or str(result.get("outcome", "")).upper() == "FAIL")
    ]
    failure_reasons = [
        f"Oracle failed: {result.get('oracle_id', 'unknown')}" for result in failed_oracles
    ]
    execution_mode = (
        run.get("execution_mode")
        or manifest.get("execution_mode")
        or runtime_config.get("execution_mode")
        or execution_manifest.get("metadata", {}).get("execution_mode")
    )
    provisional = bool(run.get("provisional") or manifest.get("provisional"))
    # The execution manifest is the authoritative source when an older run
    # record predates its display metadata.  Unknown/simulated modes remain
    # conservative and provisional.
    if str(execution_mode or "unknown").lower() not in {"live", "hybrid"}:
        provisional = True
    scenario = next(
        (
            value
            for value in (
                run.get("scenario"),
                run.get("scenario_id"),
                manifest.get("scenario_id"),
                execution_manifest.get("scenario_id"),
            )
            if value and str(value).strip().lower() != "unknown"
        ),
        "unknown",
    )
    status = str(run.get("status") or manifest.get("status") or "OPEN").upper()
    score = run.get("score")
    if score is None:
        score = manifest.get("score", compliance.get("score"))
    if score is None:
        score = finalization.get("score")
    return {
        **run,
        "scenario": scenario,
        "timestamp": run.get("created_at") or run.get("timestamp"),
        "status": status,
        "lifecycle": run.get("lifecycle") or status,
        "verification_status": run.get("verification_status", "UNKNOWN"),
        "trace_integrity": run.get("trace_integrity", "PROVIDER_MANAGED"),
        "has_certificate": bool(
            manifest.get("verification_package")
            or manifest.get("vc_version")
            or manifest.get("certificate")
        ),
        "identifier": (
            run.get("identifier")
            or run.get("agent_id")
            or agent_config.get("agent_id")
            or agent_config.get("agent_name")
        ),
        "execution_mode": execution_mode,
        "provisional": provisional,
        "score": score,
        "score_reason": run.get("score_reason")
        or (failure_reasons[0] if failure_reasons else None),
        "score_category": run.get("score_category")
        or ("ORACLE_DEFECT" if failed_oracles else None),
        "failure_reasons": run.get("failure_reasons") or failure_reasons,
        "failed_oracles": run.get("failed_oracles") or failed_oracles,
        "target": (
            run.get("target")
            or agent_config.get("configured_model_id")
            or agent_config.get("model")
            or agent_config.get("agent_name")
            or agent_config.get("agent_id")
        ),
        "model": (
            run.get("model") or agent_config.get("configured_model_id") or agent_config.get("model")
        ),
        "agent": (
            run.get("agent") or agent_config.get("agent_name") or agent_config.get("agent_id")
        ),
    }


@run_bp.route("/v1/explain/<run_id>", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def explain_run(run_id):
    """Roadmap: Forensic RCA as a service."""
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Not found"}), 404
    events = _active_run_store().get_events(
        run_id, offset=0, limit=10_000_000, context=active_runtime_context()
    )
    if not events:
        return jsonify({"error": "Trace not found"}), 404

    try:
        analysis = explain_events(events)

        return jsonify(
            {
                "run_id": run_id,
                "status": "explained",
                "analysis": analysis,
                "sourced_from_master": False,
            }
        )
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as e:
        logger.debug("explain_run failed", extra={"operation": "explain_run"}, exc_info=True)
        return jsonify({"error": str(e)}), 500


def _active_run_store():
    """Return the provider injected by the console app factory."""
    return get_run_store()


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
    store = _active_run_store()
    context = active_runtime_context()
    runs = store.search_runs(query=query, limit=200, context=context)
    enriched = []
    from eval_runner.services.run_summary import RunSummaryService

    for run in runs[:200]:
        rid = run.get("run_id") or ""
        if not _run_is_in_active_context(rid):
            continue
        try:
            manifest = store.get_manifest(rid, context=context) or run.get("manifest") or {}
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
            logger.debug("list_runs failed", extra={"operation": "list_runs"}, exc_info=True)
            manifest = run.get("manifest") or {}
        summary = _summary_from_provider({**run, "manifest": manifest})
        if summary["has_certificate"]:
            summary["verification_status"] = RunSummaryService.get_authoritative_verdict(
                rid,
                run_store=store,
                context=context,
            )
        enriched.append(summary)
    return jsonify({"runs": enriched})


@run_bp.route("/v1/runs/stream-list", methods=["GET"])
@require_sse_permission(Permission.RUNS_READ)
def stream_runs_list():
    """Streams the run list incrementally in chunks every 1 second (SSE)."""
    request_context = active_runtime_context()
    store = _active_run_store()

    def generate():
        runs = store.list_runs(limit=200, context=request_context)
        from eval_runner.services.run_summary import RunSummaryService

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
                manifest = (
                    store.get_manifest(run_id, context=request_context) or run.get("manifest") or {}
                )
                summary = _summary_from_provider({**run, "manifest": manifest})
                if summary["has_certificate"]:
                    summary["verification_status"] = RunSummaryService.get_authoritative_verdict(
                        run_id,
                        run_store=store,
                        context=request_context,
                    )
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
    """Generate a human-readable PDF report from provider-owned run data."""
    store = _active_run_store()
    context = active_runtime_context()
    run = store.get_run(run_id, context=context)
    if run is None:
        return jsonify({"error": "Run not found"}), 404
    manifest_data = store.get_manifest(run_id, context=context) or run.get("manifest") or {}
    summary = _summary_from_provider({**run, "manifest": manifest_data})

    from eval_runner.console.pdf_service import generate_run_pdf

    execution_manifest: dict[str, Any] = {}
    candidate = manifest_data.get("execution_manifest")
    if isinstance(candidate, dict):
        execution_manifest = candidate

    verif_status = str(summary.get("verification_status") or "").upper()
    status_val = str(summary.get("status") or "").upper()
    is_passed = verif_status in {"VERIFIED", "CERTIFIED_PASS", "CERTIFIED"} or (
        status_val in {"CERTIFIED", "PASSED"}
        and verif_status not in {"ATTESTED_FAIL", "FAILED", "FAILED_VERIFICATION", "POLICY_BREACH"}
    )

    events = store.get_events(run_id, offset=0, limit=10_000, context=context) or []
    analysis = {}
    if events and not is_passed:
        try:
            analysis = explain_events(events)
        except Exception as e:
            logger.debug("Failed explaining events for run report %s: %s", run_id, e, exc_info=True)

    report_data = {
        **summary,
        "run_id": run_id,
        "scenario": (
            execution_manifest.get("scenario_id")
            or summary.get("scenario")
            or summary.get("scenario_id")
            or run_id
        ),
        "passed": is_passed,
        "has_certificate": summary["has_certificate"],
        "is_certified": status_val == "CERTIFIED" and is_passed,
        "verification_status": summary["verification_status"],
        "analysis": analysis,
        "events": events,
        **resolve_artifact_scope(manifest_data),
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


@run_bp.route("/v1/runs/<path:run_id>/report-actions", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_run_report_actions(run_id: str):
    """Return the active report download action(s) and available profiles for a run."""
    context = active_runtime_context()
    store = _active_run_store()
    if (
        context is not None
        and store.get_run(run_id, context=None) is not None
        and not _run_is_in_active_context(run_id, context=context)
    ):
        return jsonify({"error": "Not found"}), 404
    return jsonify(resolve_run_report_actions(run_id, context=context))


@run_bp.route("/v1/runs/<path:run_id>", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_run_status(run_id):
    """Industrial Polling Primitive."""
    context = active_runtime_context()
    if context is not None and not _run_is_in_active_context(run_id, context=context):
        return jsonify({"error": "Not found"}), 404
    store = _active_run_store()
    run = store.get_run(run_id, context=context)
    if run is not None:
        events = store.get_events(run_id, offset=0, limit=10_000_000, context=context)
        manifest = store.get_manifest(run_id, context=context) or run.get("manifest") or {}
        summary = _summary_from_provider({**run, "manifest": manifest}, events=events)
        # Detail inspection is an explicit verification read.  Use the
        # provider-native verifier instead of treating a stored certificate as
        # proof; list views remain conservative until inspected.
        from eval_runner.services.run_summary import RunSummaryService

        summary["verification_status"] = RunSummaryService.get_authoritative_verdict(
            run_id, run_store=store, context=context
        )
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
        # A provisional index is only an accepted-work authorization record.
        # Once it has neither provider events nor a live in-process writer,
        # reporting its launch-time RUNNING value is false.  Match the stream
        # contract's terminal ``trace_unavailable`` determination instead.
        mtime_val = None
        try:
            mtime_val = float(run.get("updated_at") or run.get("created_at") or 0)
        except (ValueError, TypeError):
            mtime_val = None
        if (
            bool(run.get("provisional"))
            and not events
            and not is_run_alive(run_id)
            and raw_status in {"OPEN", "RUNNING"}
        ):
            status = "STALLED"
        elif (
            not terminal
            and mtime_val
            and (time.time() - mtime_val > 300)
            and not is_run_alive(run_id)
        ):
            status = "STALLED"
        elif terminal and raw_status in {"OPEN", "RUNNING"}:
            status = "COMPLETED"
        elif raw_status == "OPEN" and events:
            status = "RUNNING"
        else:
            status = raw_status
        scenario = manifest.get("scenario_data") or run.get("scenario_data")
        evidence_nodes = 0
        try:
            from agentv_runtime.evidence_graph import build_evidence_graph_from_events

            ev_graph = build_evidence_graph_from_events(events)
            evidence_nodes = ev_graph.get("total_nodes", 0)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
            logger.debug(
                "get_run_status failed", extra={"operation": "get_run_status"}, exc_info=True
            )
            evidence_nodes = 0
        return jsonify(
            {
                "run_id": run_id,
                "status": status,
                "size": event_count,
                "evidence_nodes": evidence_nodes,
                "can_certify": evidence_nodes > 0,
                "mtime": run.get("updated_at") or run.get("created_at"),
                "has_certificate": bool(
                    manifest.get("verification_package")
                    or manifest.get("vc_version")
                    or manifest.get("certificate")
                ),
                "sourced_from_master": False,
                "scenario": scenario,
                "execution_mode": summary.get("execution_mode") or manifest.get("execution_mode"),
                "provisional": bool(summary.get("provisional", manifest.get("provisional", False))),
                "verification_status": summary.get("verification_status", "PROVIDER_MANAGED"),
                "verdict": summary.get("verification_status", "PROVIDER_MANAGED"),
                "target": summary.get("target") or run.get("target"),
                "model": summary.get("model") or run.get("model"),
                "agent": summary.get("agent") or run.get("agent"),
                "duration_seconds": summary.get("duration_seconds"),
                "score": (
                    summary["score"]
                    if summary.get("score") is not None
                    else (manifest.get("compliance") or {}).get("score")
                ),
                "score_reason": summary.get("score_reason"),
                "report_actions": resolve_run_report_actions(run_id, context=context),
                "score_category": summary.get("score_category"),
                "failure_reasons": summary.get("failure_reasons", []),
                "failed_oracles": summary.get("failed_oracles", []),
                "timestamp": summary.get("timestamp") or run.get("created_at"),
                "start_time": summary.get("timestamp") or run.get("created_at"),
                "identifier": summary.get("identifier") or run.get("run_id"),
            }
        )

    return jsonify({"error": "Run not found"}), 404


@run_bp.route("/v1/runs/<path:run_id>/cancel", methods=["POST"])
@require_permission(Permission.RUNS_WRITE)
def cancel_run(run_id):
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Not found"}), 404
    """Cancels an active execution run via ExecutionBackend."""
    from eval_runner.runtime_services import resolve_execution_backend

    data = request.json or {}
    reason = data.get("reason", "Cancelled via Console API")
    backend = resolve_execution_backend()
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
@require_permission(Permission.HITL_RESOLVE)
def resume_run(run_id):
    """Resumes a paused or checkpointed evaluation run via ExecutionBackend."""
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Not found"}), 404

    from flask import g

    from eval_runner.runtime_services import resolve_approval_store, resolve_execution_backend
    from eval_runner.session_components.approval_manager import SessionApprovalManager

    data = request.json or {}
    resumption_token = data.get("resumption_token") or data.get("approval_token")
    decision = (data.get("decision") or "APPROVED").upper()
    reason = data.get("reason")

    principal = getattr(g, "verified_principal", None)
    if principal is not None:
        reviewer = (
            principal.get("name")
            or principal.get("id")
            or principal.get("principal_id")
            or "authenticated_user"
        )
        roles = principal.get("roles") or []
        if isinstance(roles, str):
            roles = [roles]
        reviewer_roles = set(roles)
        if "role" in principal:
            reviewer_roles.add(str(principal["role"]))
    elif os.getenv("AGENTV_TEST_AUTH_BYPASS") == "1":
        reviewer = data.get("reviewer") or "test_reviewer"
        reviewer_role = data.get("reviewer_role")
        reviewer_roles = {reviewer_role} if reviewer_role else {"admin", "reviewer"}
    else:
        return jsonify(
            {"error": "Unauthorized: An authenticated principal is required to resolve approvals"}
        ), 401

    if decision not in {"APPROVED", "REJECTED"}:
        return jsonify({"error": "decision must be APPROVED or REJECTED"}), 400
    if not resumption_token:
        return jsonify({"error": "A durable approval token is required to resume a run"}), 400

    store = resolve_approval_store()
    req = store.get_request(resumption_token)
    if not req:
        return jsonify({"error": "Approval token was not found"}), 404
    if req.run_id != run_id:
        return jsonify({"error": "Approval token is not bound to this run"}), 409
    if req.status != "PENDING":
        return jsonify({"error": "Approval token has already been resolved"}), 409
    if req.required_role and req.required_role not in reviewer_roles:
        err_msg = (
            f"Reviewer role does not satisfy the approval requirement "
            f"(required: {req.required_role})"
        )
        return jsonify({"error": err_msg}), 403

    try:
        # Keep all durable approval resolutions on the runtime's generic
        # approval boundary.  This ensures the same interceptor checks apply
        # to Console, CLI, and in-session resumption paths.
        from agentv_runtime.scope import ScopeToken
        from eval_runner.runtime_services import resolve_plugin_registry

        run_context = active_runtime_context()
        run_store = _active_run_store()
        scope = active_runtime_scope() or (
            ScopeToken.from_tags(run_context) if run_context else None
        )
        SessionApprovalManager(
            run_id=run_id,
            approval_store=store,
            plugin_manager=resolve_plugin_registry(),
            scope=scope,
            run_store=run_store,
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

    backend = resolve_execution_backend()
    try:
        resumed = backend.resume(
            run_id,
            resumption_token=resumption_token,
            background=True,
            run_store=run_store,
            context=run_context,
        )
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        logger.debug("resume_run failed", extra={"operation": "resume_run"}, exc_info=True)
        msg = str(exc).lower()
        if "unavailable" in msg or "missing" in msg or "not found" in msg or "checkpoint" in msg:
            resumed = None
        else:
            raise
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


def _sanitize_certificate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Sanitize sensitive credentials (headers, tokens, keys) from returned certificate manifest."""
    from eval_runner.sanitizer import sanitize_credentials

    sanitized = json.loads(json.dumps(manifest))
    return sanitize_credentials(sanitized)


PUBLIC_CERTIFICATE_FIELDS = frozenset(
    {
        "run_id",
        "vc_version",
        "status",
        "outcome",
        "issued_at",
        "expires_at",
        "compliance_level",
        "execution_mode",
        "provisional",
        "evidence_root_hash",
        "scenario_hash",
        "manifest_hash",
        "verification_package",
        "signature",
        "signatures",
        "provenance_chain",
        "identity",
        "public_key",
        "digest",
        "algorithm",
    }
)


def project_public_certificate(manifest: dict[str, Any]) -> dict[str, Any]:
    """Extract public certificate projection without exposing private scenario data or evidence."""
    sanitized = _sanitize_certificate_manifest(manifest)
    public_proj = {k: v for k, v in sanitized.items() if k in PUBLIC_CERTIFICATE_FIELDS}
    if "run_id" not in public_proj and "run_id" in sanitized:
        public_proj["run_id"] = sanitized["run_id"]
    if "vc_version" not in public_proj and "vc_version" in sanitized:
        public_proj["vc_version"] = sanitized["vc_version"]
    return public_proj


@run_bp.route("/v1/certificates/<run_id>", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_verification_certificate(run_id):
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Not found"}), 404

    store = _active_run_store()
    context = active_runtime_context()
    run = store.get_run(run_id, context=context)
    if run is None:
        return jsonify({"error": "Certificate not found"}), 404
    if run.get("corrupted"):
        return jsonify({"error": "Corrupt manifest found"}), 500
    try:
        manifest = store.get_manifest(run_id, context=context)
    except ValueError as e:
        if "corrupt" in str(e).lower():
            return jsonify({"error": "Corrupt manifest found"}), 500
        raise
    if not manifest:
        return jsonify({"error": "Certificate not found"}), 404
    return jsonify(_sanitize_certificate_manifest(manifest))


@run_bp.route("/v1/certificates/<run_id>/public", methods=["GET"])
def get_public_certificate(run_id):
    """Public certificate projection returning cryptographic proof without private evidence."""
    store = _active_run_store()
    run = store.get_run(run_id)
    if run is None:
        return jsonify({"error": "Certificate not found"}), 404
    if run.get("corrupted"):
        return jsonify({"error": "Corrupt manifest found"}), 500
    try:
        manifest = store.get_manifest(run_id)
    except ValueError as e:
        if "corrupt" in str(e).lower():
            return jsonify({"error": "Corrupt manifest found"}), 500
        raise
    if not manifest:
        return jsonify({"error": "Certificate not found"}), 404
    return jsonify(project_public_certificate(manifest))


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
    except (ValueError, TypeError):
        logger.debug(
            "_extract_canonical_event_info failed",
            extra={"operation": "_extract_canonical_event_info"},
            exc_info=True,
        )
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


@run_bp.route("/v1/runs/<path:run_id>/stream", methods=["GET"])
@require_sse_permission(Permission.RUNS_READ)
def stream_run_logs(run_id):
    """SSE streaming endpoint for live run traces with Last-Event-ID replay support."""
    req_context = active_runtime_context()
    if req_context is not None and not _run_is_in_active_context(run_id, req_context):
        return jsonify({"error": "Not found"}), 404
    provider = _active_run_store()
    run_record = provider.get_run(run_id, context=req_context)
    last_id_str = (
        request.headers.get("Last-Event-ID")
        or request.args.get("last_event_id")
        or request.args.get("since")
    )
    try:
        last_event_id = int(last_id_str) if last_id_str is not None else 0
    except (ValueError, TypeError):
        last_event_id = 0

    def provider_events():
        next_offset = last_event_id
        for _ in range(300):  # Five-minute bounded connection; clients may reconnect.
            emitted = False
            for index, event in enumerate(
                provider.stream_events(run_id, from_seq=next_offset, context=req_context),
                start=next_offset + 1,
            ):
                # SSE replay cursors are transport positions, never forensic
                # ``_seq`` values.  A trace may legitimately have non-contiguous
                # evidence sequence numbers; using those as Last-Event-ID
                # silently skips replay frames and fabricates client-side gaps.
                event_id = index
                next_offset = event_id
                emitted = True
                yield f"id: {event_id}\ndata: {json.dumps(event)}\n\n"
                if event.get("event") in TERMINAL_TRACE_EVENTS:
                    return
            record = provider.get_run(run_id, context=req_context) or {}
            if str(record.get("status", "")).upper() == "PAUSED_FOR_APPROVAL":
                # HITL suspension is a durable, non-terminal lifecycle state.
                # It is nevertheless terminal for this *live execution stream*:
                # no worker remains to write events until a reviewer resumes it.
                # Emit an explicit control frame so EventSource does not treat
                # the normal close as a transient transport failure and retry.
                yield ('data: {"event":"paused_for_approval","status":"PAUSED_FOR_APPROVAL"}\n\n')
                return
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

    if run_record is not None:
        return Response(
            provider_events(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    def stream_not_found():
        import json as _json

        if run_record is None or is_run_alive(run_id):
            payload = _json.dumps(
                {
                    "event": "not_found",
                    "message": "Execution log file not found. Waiting for trace data.",
                }
            )
        else:
            # A registered run with no provider trace and no live writer
            # cannot make progress by reconnecting.
            # This is a persistence failure, not a transient SSE condition.
            payload = _json.dumps(
                {
                    "event": "trace_unavailable",
                    "status": "STALLED",
                    "message": "Run has no durable trace and no active execution writer.",
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

    store = _active_run_store()
    context = active_runtime_context()
    manifest = store.get_manifest(run_id, context=context)
    trace_bytes = store.get_trace_bytes(run_id, context=context)
    if not manifest or trace_bytes is None:
        return jsonify({"verification_status": "NOT_FOUND"}), 404
    result = TraceVerifier.verify_run(run_id, run_store=store, context=context)
    verified = result["is_valid"]
    verification_status = result["verification_status"]
    provenance = manifest.get("provenance_chain") or manifest.get("signatures") or []
    if not isinstance(provenance, list):
        provenance = []
    signer = provenance[-1] if provenance and isinstance(provenance[-1], dict) else {}
    has_certificate = bool(
        manifest.get("vc_version")
        or manifest.get("verification_package")
        or manifest.get("certificate")
        or provenance
    )
    return jsonify(
        {
            **result,
            "verification_status": verification_status,
            "verdict": verification_status,
            "provisional": verification_status == "VERIFIED_PROVISIONAL",
            # The console reads these only as the result of the provider-native
            # verification above, never as a certificate-presence inference.
            "is_valid": verified,
            "cryptographically_valid": verified,
            "has_certificate": has_certificate,
            "algorithm": signer.get("algorithm"),
            "signer_identity": signer.get("identity") or signer.get("key_id"),
            **(
                {"failure_reason": "Trace or certificate verification failed."}
                if not verified
                else {}
            ),
        }
    )
