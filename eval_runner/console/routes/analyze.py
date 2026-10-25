"""
routes/analyze.py

Analyze group API endpoints:
  - Leaderboard (data + HTML export)
  - Failure Corpus search
  - Triage (per-run root cause analysis)
  - Compliance (PQC status, fleet summary)
  - Forensic diff
"""

import html
import logging
from io import BytesIO

from flask import Blueprint, jsonify, request, send_file

from eval_runner.forensics import list_diff
from eval_runner.trace_utils import reconstruct_results_from_events

from ..auth_manager import Permission, active_runtime_context, require_permission
from ..providers import get_run_store
from .runs import _run_is_in_active_context

logger = logging.getLogger(__name__)

analyze_bp = Blueprint("analyze", __name__)


def _run_store():
    return get_run_store()


def _provider_leaderboard_rows() -> list[dict]:
    """Aggregate leaderboard rows from provider records and events only."""
    store = _run_store()
    context = active_runtime_context()
    rows: list[dict] = []
    for run in store.list_runs(limit=10_000, context=context):
        run_id = str(run.get("run_id") or "")
        if not run_id or not _run_is_in_active_context(run_id, context):
            continue
        manifest = store.get_manifest(run_id, context=context) or {}
        events = store.get_events(run_id, offset=0, limit=10_000_000, context=context)
        execution_manifest = manifest.get("execution_manifest") or {}
        agent_config = execution_manifest.get("agent_config") or {}
        agent = (
            run.get("agent")
            or run.get("agent_id")
            or manifest.get("agent_name")
            or agent_config.get("agent_name")
            or agent_config.get("agent_id")
            or "unknown"
        )
        finalization = next(
            (
                (event.get("data") or {}).get("finalization", {})
                for event in reversed(events)
                if event.get("event") in {"run_end", "end"} and isinstance(event.get("data"), dict)
            ),
            {},
        )
        score = run.get("score")
        if score is None:
            score = manifest.get("score", finalization.get("score"))
        if score is None:
            continue
        try:
            pass_rate = float(score)
        except (TypeError, ValueError):
            continue
        if pass_rate <= 1:
            pass_rate *= 100
        outcome = str(run.get("result_status") or finalization.get("outcome") or "").upper()
        successful = 0 if outcome in {"FAIL", "FAILED", "ATTESTED_FAIL"} else 1
        certified = bool(manifest.get("signature") or manifest.get("provenance_chain"))
        rows.append(
            {
                "run_id": run_id,
                "agent": str(agent),
                "agent_display": f"🏅 {agent}" if certified else str(agent),
                "pass_rate": round(pass_rate, 1),
                "successful_tasks": successful,
                "total_tasks": 1,
                "tasks": f"{successful}/1",
                "certified": certified,
                "metrics": {},
                "trace_file": "provider://trace",
            }
        )
    return sorted(rows, key=lambda row: row["pass_rate"], reverse=True)


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


@analyze_bp.route("/leaderboard", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_leaderboard():
    """
    Returns structured leaderboard rows aggregated across all evaluation runs.
    Each row includes agent name, pass rate, task counts, certified flag,
    and per-metric averages for the 4 metric family drill-down.
    """
    try:
        rows = _provider_leaderboard_rows()
        return jsonify({"leaderboard": rows, "total": len(rows)})
    except Exception as e:
        logger.error(f"[Leaderboard] Failed to generate leaderboard: {e}")
        return jsonify({"error": str(e)}), 500


@analyze_bp.route("/leaderboard/export-html", methods=["POST"])
@require_permission(Permission.RUNS_READ)
def export_leaderboard_html():
    """
    Generates a self-contained HTML leaderboard from provider-owned rows.
    """
    try:
        rows = _provider_leaderboard_rows()
        body = "".join(
            "<tr>"
            f"<td>{html.escape(row['agent'])}</td>"
            f"<td>{row['pass_rate']:.1f}%</td>"
            f"<td>{html.escape(row['tasks'])}</td>"
            f"<td>{'yes' if row['certified'] else 'no'}</td>"
            "</tr>"
            for row in rows
        )
        document = (
            "<!doctype html><html><head><meta charset='utf-8'><title>AgentV Leaderboard</title>"
            "</head><body><h1>AgentV Leaderboard</h1>"
            "<table><thead><tr><th>Agent</th><th>Pass rate</th><th>Tasks</th>"
            "<th>Certified</th></tr></thead><tbody>"
            f"{body}</tbody></table></body></html>"
        )

        return send_file(
            BytesIO(document.encode("utf-8")),
            mimetype="text/html",
            as_attachment=True,
            download_name="agentv_leaderboard.html",
        )
    except Exception as e:
        logger.error(f"[Leaderboard] HTML export failed: {e}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Failure Corpus Search
# ---------------------------------------------------------------------------


@analyze_bp.route("/failures/search", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def search_failures():
    """
    Searches provider-owned run events for entries matching a query.
    Supports regex (auto-detected by presence of metacharacters) and
    multi-term AND text search, mirroring failure_corpus.search() behavior.

    Query params:
      q       — search query string (required)
      page    — 1-indexed page number (default: 1)
      limit   — results per page (default: 50)
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    page = max(1, int(request.args.get("page", 1)))
    limit = min(200, max(1, int(request.args.get("limit", 50))))

    import re

    # Mirror the auto-detection logic from failure_corpus.py exactly
    regex_pattern = None
    mode = "text"
    try:
        if any(c in q for c in ".+*?^$()[]{}|\\"):
            regex_pattern = re.compile(q, re.IGNORECASE)
            mode = "regex"
    except re.error:
        regex_pattern = None
        mode = "text"

    matches = []
    try:
        for run in _run_store().list_runs(limit=10_000, context=active_runtime_context()):
            run_id = str(run.get("run_id") or "")
            for data in _run_store().get_events(
                run_id, offset=0, limit=10_000_000, context=active_runtime_context()
            ):
                search_space = (
                    f"{data.get('event', '')} {data.get('status', '')} "
                    f"{data.get('triage_tag', '')} {data.get('metric', '')} "
                    f"{str(data.get('content', ''))}"
                )
                found = False
                if regex_pattern:
                    found = bool(regex_pattern.search(search_space))
                else:
                    terms = q.lower().split()
                    found = all(t in search_space.lower() for t in terms)

                if found:
                    matches.append(
                        {
                            "timestamp": data.get("timestamp"),
                            "run_id": data.get("run_id"),
                            "event": data.get("event"),
                            "status": data.get("status"),
                            "triage_tag": data.get("triage_tag"),
                            "metric": data.get("metric"),
                            "content": str(data.get("content", ""))[:500],
                            "task_id": data.get("task_id"),
                        }
                    )
    except Exception as e:
        logger.error(f"[Failure Search] Failed: {e}")
        return jsonify({"error": str(e)}), 500

    total = len(matches)
    start = (page - 1) * limit
    page_matches = matches[start : start + limit]

    return jsonify(
        {
            "matches": page_matches,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit if total > 0 else 0,
            "mode": mode,
            "query": q,
        }
    )


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------


@analyze_bp.route("/triage/<run_id>", methods=["POST"])
@require_permission(Permission.RUNS_READ)
def run_triage(run_id: str):
    """
    Runs the Triage Engine against a completed run's event trace.
    Uses trace_utils.reconstruct_results_from_events() as the canonical bridge
    between provider events and the TriageEngine's expected input shape.

    Returns a list of per-task triage reports with category, confidence,
    explanation, suggestion, and root-cause turn index.
    """
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Run not found"}), 404
    events = _run_store().get_events(
        run_id, offset=0, limit=10_000_000, context=active_runtime_context()
    )
    if not events:
        return jsonify({"error": f"Run '{run_id}' not found"}), 404

    try:
        # reconstruct_results_from_events internally calls TriageEngine.apply_triage()
        results = reconstruct_results_from_events(events)

        from eval_runner.triage import TriageEngine

        enriched = []
        for r in results:
            root_cause = TriageEngine.identify_root_cause(r)
            enriched.append(
                {
                    "task_id": r.get("task_id"),
                    "triage_tag": r.get("triage_tag", "UNKNOWN"),
                    "category": root_cause.get("category", "UNKNOWN"),
                    "confidence": root_cause.get("confidence", 0.0),
                    "explanation": root_cause.get("reason", ""),
                    "suggestion": root_cause.get("suggestion", ""),
                    "turn_index": root_cause.get("index", -1),
                    "metrics": r.get("metrics", []),
                }
            )

        return jsonify({"run_id": run_id, "results": enriched, "total": len(enriched)})
    except Exception as e:
        logger.error(f"[Triage] Failed for run {run_id}: {e}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Compliance (PQC)
# ---------------------------------------------------------------------------


@analyze_bp.route("/compliance/<run_id>", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_compliance(run_id: str):
    """Returns PQC compliance status for a single run's manifest."""
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Run not found"}), 404
    try:
        manifest = _run_store().get_manifest(run_id, context=active_runtime_context())
        if not manifest:
            return jsonify({"error": f"Run '{run_id}' not found"}), 404

        algorithm = str(manifest.get("algorithm") or manifest.get("crypto_suite") or "")
        return jsonify(
            {
                "run_id": run_id,
                "quantum_safe": "ml-dsa" in algorithm.lower() or "pqc" in algorithm.lower(),
            }
        )
    except Exception as e:
        logger.error(f"[Compliance] Failed for run {run_id}: {e}")
        return jsonify({"error": str(e)}), 500


@analyze_bp.route("/compliance/summary", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_compliance_summary():
    """
    Aggregates PQC compliance status across all certified runs in a date range.
    Returns: total certified, quantum_safe count, classical_only count, percentage.

    Query params:
      range — optional ISO date filter prefix, e.g. '2026-07' matches July 2026
    """
    date_range = request.args.get("range", "").strip()
    total_certified = 0
    quantum_safe = 0
    classical_only = 0
    details = []

    for run in _run_store().list_runs(limit=10_000, context=active_runtime_context()):
        run_id = str(run.get("run_id") or "")
        if not _run_is_in_active_context(run_id):
            continue
        if date_range and not run_id.startswith(date_range):
            continue

        try:
            manifest = _run_store().get_manifest(run_id, context=active_runtime_context()) or {}
            algorithm = str(manifest.get("algorithm") or manifest.get("crypto_suite") or "")
            status = {"quantum_safe": "ml-dsa" in algorithm.lower() or "pqc" in algorithm.lower()}
            total_certified += 1
            if status["quantum_safe"]:
                quantum_safe += 1
            else:
                classical_only += 1
            details.append({"run_id": run_id, **status})
        except Exception as e:
            logger.warning(f"[Compliance Summary] Skipping {run_id}: {e}")
            continue

    pct_safe = round((quantum_safe / total_certified * 100), 1) if total_certified > 0 else 0.0

    return jsonify(
        {
            "total_certified": total_certified,
            "quantum_safe": quantum_safe,
            "classical_only": classical_only,
            "percent_quantum_safe": pct_safe,
            "details": details,
        }
    )


# ---------------------------------------------------------------------------
# Forensic Diff
# ---------------------------------------------------------------------------


@analyze_bp.route("/forensics/diff", methods=["POST"])
@require_permission(Permission.RUNS_READ)
def forensic_diff():
    """
    Computes a structural diff between two environment state snapshots.
    Accepts two JSON arrays (lists of dicts) and returns a list_diff result
    identifying added/modified/deleted records, with the auto-detected primary key.

    Request body: { "old": [...], "new": [...] }
    """
    body = request.get_json(silent=True)
    if not body or "old" not in body or "new" not in body:
        return jsonify({"error": "Request body must include 'old' and 'new' arrays"}), 400

    old_state = body["old"]
    new_state = body["new"]

    if not isinstance(old_state, list) or not isinstance(new_state, list):
        return jsonify({"error": "'old' and 'new' must be JSON arrays"}), 400

    try:
        # Detect the primary key before running the diff so we can expose it
        pk_candidates = ["id", "audit_id", "application_id", "applicant_id", "email"]
        detected_pk = None
        if old_state and all(isinstance(x, dict) for x in old_state):
            detected_pk = next(
                (
                    k
                    for k in pk_candidates
                    if all(k in x for x in old_state) and all(k in x for x in new_state)
                ),
                None,
            )

        result = list_diff(old_state, new_state)

        return jsonify(
            {
                "diff": result,
                "detected_primary_key": detected_pk,
                "identical": result is None,
            }
        )
    except Exception as e:
        logger.error(f"[Forensics] Diff failed: {e}")
        return jsonify({"error": str(e)}), 500
