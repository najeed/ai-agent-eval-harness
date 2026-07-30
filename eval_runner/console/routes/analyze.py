"""
routes/analyze.py

Analyze group API endpoints:
  - Leaderboard (data + HTML export)
  - Failure Corpus search
  - Triage (per-run root cause analysis)
  - Compliance (PQC status, fleet summary)
  - Forensic diff
"""

import json
import logging

from flask import Blueprint, jsonify, request, send_file

from eval_runner import config
from eval_runner.compliance import ComplianceService
from eval_runner.forensics import list_diff
from eval_runner.leaderboard_generator import LeaderboardGenerator
from eval_runner.trace_utils import load_events, reconstruct_results_from_events

from ..auth_manager import Permission, require_permission

logger = logging.getLogger(__name__)

analyze_bp = Blueprint("analyze", __name__)

_compliance_svc = ComplianceService()


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
    runs_dir = str(config.RUN_LOG_DIR)
    try:
        rows = LeaderboardGenerator.generate_data(runs_dir)
        return jsonify({"leaderboard": rows, "total": len(rows)})
    except Exception as e:
        logger.error(f"[Leaderboard] Failed to generate leaderboard: {e}")
        return jsonify({"error": str(e)}), 500


@analyze_bp.route("/leaderboard/export-html", methods=["POST"])
@require_permission(Permission.RUNS_READ)
def export_leaderboard_html():
    """
    Generates a self-contained HTML leaderboard artifact via html_builder.py
    and returns it as a downloadable file.
    """
    try:
        from eval_runner.publication_suite.html_builder import HtmlBuilder

        runs_dir = str(config.RUN_LOG_DIR)
        output_path = config.PROJECT_ROOT / "reports" / "leaderboard.html"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        builder = HtmlBuilder(runs_dir=runs_dir, output_path=str(output_path))
        builder.build()

        return send_file(
            str(output_path),
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
    Searches the master run.jsonl log for events matching a query.
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

    master_log = config.RUN_LOG_DIR / "run.jsonl"
    if not master_log.exists():
        return jsonify({"matches": [], "total": 0, "mode": "text", "query": q})

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
        with open(master_log, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
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
                except json.JSONDecodeError:
                    continue
    except Exception as e:
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
    between raw run.jsonl events and the TriageEngine's expected input shape.

    Returns a list of per-task triage reports with category, confidence,
    explanation, suggestion, and root-cause turn index.
    """
    trace_path = config.RUN_LOG_DIR / run_id / "run.jsonl"
    if not trace_path.exists():
        return jsonify({"error": f"Run '{run_id}' not found"}), 404

    try:
        events = load_events(trace_path)
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
    run_dir = config.RUN_LOG_DIR / run_id
    if not run_dir.exists():
        return jsonify({"error": f"Run '{run_id}' not found"}), 404

    try:
        status = _compliance_svc.check_pqc_status(run_id)
        return jsonify({"run_id": run_id, **status})
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
    runs_dir = config.RUN_LOG_DIR

    total_certified = 0
    quantum_safe = 0
    classical_only = 0
    details = []

    for manifest_path in runs_dir.glob("*/run_manifest.json"):
        run_id = manifest_path.parent.name
        if date_range and not run_id.startswith(date_range):
            continue

        try:
            status = _compliance_svc.check_pqc_status(run_id)
            total_certified += 1
            if status.get("quantum_safe"):
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
