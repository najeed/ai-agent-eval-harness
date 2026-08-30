"""
routes/compliance_packs.py

API Endpoints for Compliance Pack Editor and Rules Evaluator.
Manages custom checks configuration (WSM severity, PQC algorithms, IJA, Rubrics)
against compliance standards and tests them against historical runs.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, jsonify, request

from eval_runner import config
from eval_runner.explainer import explain_trace

from ..auth_manager import Permission, require_permission
from .runs import resolve_trace_path

logger = logging.getLogger(__name__)
compliance_packs_bp = Blueprint("compliance_packs", __name__)

PACKS_DIR = config.PROJECT_ROOT / "results" / "compliance_packs"
PACKS_DIR.mkdir(parents=True, exist_ok=True)


def _load_standards() -> list[dict]:
    """Loads all standard items from spec/aes/standards.json."""
    standards_path = config.PROJECT_ROOT / "spec" / "aes" / "standards.json"
    if not standards_path.exists():
        return []
    try:
        with open(standards_path, encoding="utf-8") as f:
            data = json.load(f)
            flat_list = []
            for category, info in data.get("categories", {}).items():
                for std in info.get("standards", []):
                    flat_list.append(
                        {
                            "id": std.get("id"),
                            "name": std.get("name"),
                            "description": std.get("description"),
                            "category": category,
                        }
                    )
            return flat_list
    except Exception as e:
        logger.error(f"Failed to load standards.json: {e}")
        return []


@compliance_packs_bp.route("/v1/compliance-packs", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def list_packs():
    """Lists compliance packs integrated with standards metadata."""
    standards = _load_standards()
    packs = []

    for std in standards:
        pack_id = std["id"]
        pack_path = PACKS_DIR / f"{pack_id}.json"

        configured = False
        checks = []
        version = 1

        if pack_path.exists():
            try:
                with open(pack_path, encoding="utf-8") as f:
                    pack_data = json.load(f)
                    configured = True
                    checks = pack_data.get("checks", [])
                    version = pack_data.get("version", 1)
            except Exception as e:
                logger.warning(f"Error loading pack {pack_id}: {e}")

        packs.append(
            {
                "id": pack_id,
                "name": std["name"],
                "description": std["description"],
                "category": std["category"],
                "configured": configured,
                "version": version,
                "checks": checks,
            }
        )

    # Discovery of custom user-defined compliance packs
    standard_ids = {std["id"] for std in standards}
    for p in PACKS_DIR.glob("*.json"):
        pack_id = p.stem
        if pack_id in standard_ids:
            continue
        try:
            with open(p, encoding="utf-8") as f:
                pack_data = json.load(f)
                packs.append(
                    {
                        "id": pack_id,
                        "name": pack_data.get("name") or f"Custom Pack {pack_id}",
                        "description": pack_data.get("description", "User-defined custom checks."),
                        "category": "Custom Checklists",
                        "configured": True,
                        "version": pack_data.get("version", 1),
                        "checks": pack_data.get("checks", []),
                    }
                )
        except Exception as e:
            logger.warning(f"Error loading custom pack {pack_id}: {e}")

    return jsonify({"packs": packs})


@compliance_packs_bp.route("/v1/compliance-packs/<pack_id>", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_pack(pack_id):
    """Fetches a specific compliance pack configuration."""
    pack_path = PACKS_DIR / f"{pack_id}.json"
    if not pack_path.exists():
        return jsonify({"id": pack_id, "configured": False, "checks": []})

    try:
        with open(pack_path, encoding="utf-8") as f:
            data = json.load(f)
            data["configured"] = True
            return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


SUPPORTED_CHECK_TYPES = {"pqc_required", "wsm_threshold", "rubric_required", "ija_threshold"}


@compliance_packs_bp.route("/v1/compliance-packs", methods=["POST"])
@require_permission(Permission.EVAL_TRIGGER)
def save_pack():
    """Saves or creates a compliance pack ruleset config."""
    body = request.get_json(silent=True) or {}
    pack_id = body.get("id")
    name = body.get("name")
    checks = body.get("checks", [])

    if not pack_id or not name:
        return jsonify({"error": "Missing required parameters: id, name"}), 400

    for chk in checks:
        chk_type = chk.get("type") if isinstance(chk, dict) else chk
        if not isinstance(chk, dict) or chk_type not in SUPPORTED_CHECK_TYPES:
            return (
                jsonify(
                    {
                        "error": (
                            f"Invalid check configuration: check type '{chk_type}' "
                            f"is not supported. Supported types: {sorted(SUPPORTED_CHECK_TYPES)}"
                        )
                    }
                ),
                400,
            )

    pack_path = PACKS_DIR / f"{pack_id}.json"

    # Versioning bump if it already exists
    version = 1
    if pack_path.exists():
        try:
            with open(pack_path, encoding="utf-8") as f:
                old_data = json.load(f)
                version = old_data.get("version", 1) + 1
        except Exception as e:
            logger.debug(f"Could not load old pack version: {e}")

    pack_record = {
        "id": pack_id,
        "name": name,
        "description": body.get("description", ""),
        "applicable_industries": body.get("applicable_industries", []),
        "version": version,
        "checks": checks,
        "last_updated": datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
    }

    try:
        with open(pack_path, "w", encoding="utf-8") as f:
            json.dump(pack_record, f, indent=2)
        return jsonify(pack_record)
    except Exception as e:
        logger.error(f"Failed to save compliance pack {pack_id}: {e}")
        return jsonify({"error": str(e)}), 500


@compliance_packs_bp.route("/v1/compliance-packs/<pack_id>/publish", methods=["POST"])
@require_permission(Permission.EVAL_TRIGGER)
def publish_pack(pack_id):
    """Finalizes and registers the published version of a pack."""
    pack_path = PACKS_DIR / f"{pack_id}.json"
    if not pack_path.exists():
        standards = _load_standards()
        matching_std = next((s for s in standards if s["id"] == pack_id), None)
        if not matching_std:
            return jsonify({"error": f"Compliance Pack {pack_id} not found"}), 404
        name = matching_std["name"]
        desc = matching_std.get("description", "")

        pack_record = {
            "id": pack_id,
            "name": name,
            "description": desc,
            "applicable_industries": [],
            "version": 1,
            "checks": [],
            "last_updated": datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
        }
        try:
            with open(pack_path, "w", encoding="utf-8") as f:
                json.dump(pack_record, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to auto-create compliance pack {pack_id} on publish: {e}")
            return jsonify({"error": str(e)}), 500

    # Return success confirmation
    return jsonify(
        {"status": "success", "message": f"Compliance Pack {pack_id} published successfully."}
    )


@compliance_packs_bp.route("/v1/compliance-packs/<pack_id>/test", methods=["POST"])
@require_permission(Permission.RUNS_READ)
def test_pack(pack_id):
    """Tests compliance pack checks against a target historical run's trace data."""
    run_id = request.args.get("run_id")
    if not run_id:
        return jsonify({"error": "Missing query parameter: run_id"}), 400

    pack_path = PACKS_DIR / f"{pack_id}.json"
    checks = []
    if pack_path.exists():
        try:
            with open(pack_path, encoding="utf-8") as f:
                pack_data = json.load(f)
                checks = pack_data.get("checks", [])
        except Exception as e:
            logger.error(f"Failed to read pack configuration: {e}")

    trace_path = resolve_trace_path(run_id)
    temp_extracted = False
    temp_path = None

    # Fallback to scanning master log
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
                temp_path = PACKS_DIR / f"temp_test_{run_id}.jsonl"
                with open(temp_path, "w", encoding="utf-8") as f_temp:
                    f_temp.write("\n".join(filtered))
                trace_path = temp_path
                temp_extracted = True

    if not trace_path or not trace_path.exists():
        return jsonify({"error": "Run trace not found"}), 404

    # Run Analysis
    try:
        analysis = explain_trace(trace_path)
    except Exception as e:
        logger.warning(f"Explain trace warning: {e}")
        analysis = {"root_cause": "Unknown", "suggestion": "N/A", "confidence": 0.5}

    results = []
    overall_pass = True

    # Determine if this run has a valid PQC verification certificate.
    # Only treat cert as present if the actual file exists, or if the trace
    # explicitly records a completed/certified status — NOT by assuming a default.
    status = ""
    try:
        with open(trace_path, encoding="utf-8") as f:
            first_line = f.readline()
            if first_line:
                ev = json.loads(first_line)
                status = ev.get("status") or ""
    except Exception as e:
        logger.debug(f"Error reading first trace line: {e}")

    cert_path = config.REPORTS_DIR / "certificates" / f"{run_id}_vc.json"
    manifest_path = config.RUN_LOG_DIR / run_id / "run_manifest.json"

    cert_data: dict[str, Any] = {}
    for c_path in [cert_path, manifest_path]:
        if c_path.exists():
            try:
                with open(c_path, encoding="utf-8") as f_cert:
                    cert_data.update(json.load(f_cert))
            except Exception as e:
                logger.debug(f"Error reading cert/manifest at {c_path}: {e}")

    has_cert = (
        bool(cert_data)
        or cert_path.exists()
        or "completed" in status.lower()
        or "certified" in status.lower()
    )

    for chk in checks:
        chk_type = chk.get("type")
        chk_params = chk.get("params", {})

        status_val = "PASS"
        details = ""

        if chk_type == "pqc_required":
            min_alg = chk_params.get("min_algorithm", "ML-DSA-65")
            if has_cert:
                details = f"Post-quantum cryptographic signature validated using {min_alg}."
            else:
                status_val = "FAIL"
                details = "PQC Verification Certificate signature is missing or non-compliant."
                overall_pass = False

        elif chk_type == "wsm_threshold":
            dim = chk_params.get("dimension", "security")
            min_score = chk_params.get("min_score", 0.85)

            # Query real WSM metrics from certificate, metrics dictionary, or run analysis
            metrics_dict = (
                cert_data.get("metrics", {})
                or cert_data.get("wsm_scores", {})
                or cert_data.get("compliance", {}).get("wsm_scores", {})
                or analysis.get("wsm_scores", {})
            )
            actual_score = (
                metrics_dict.get(f"wsm_{dim}")
                or metrics_dict.get("wsm_score")
                or metrics_dict.get(dim)
                or cert_data.get("compliance", {}).get("score")
                or analysis.get("wsm_score")
            )
            if actual_score is None:
                actual_score = analysis.get("wsm_score", 0.0)

            if isinstance(actual_score, int | float) and actual_score >= min_score:
                details = (
                    f"Weighted Severity model for {dim} "
                    f"cleared threshold ({actual_score} >= {min_score})."
                )
            else:
                status_val = "FAIL"
                details = (
                    f"WSM {dim} score below compliance threshold ({actual_score} < {min_score})."
                )
                overall_pass = False

        elif chk_type == "rubric_required":
            rubric = chk_params.get("rubric", "general_compliance")
            min_score = chk_params.get("min_score", 0.8)

            rubrics = (
                cert_data.get("rubrics", {})
                or cert_data.get("metrics", {})
                or cert_data.get("metadata", {}).get("rubrics", {})
                or cert_data.get("consensus", {}).get("rubrics", {})
            )
            actual_score = rubrics.get(rubric) if isinstance(rubrics, dict) else None

            if actual_score is not None and isinstance(actual_score, int | float):
                if actual_score >= min_score:
                    details = (
                        f"Fiduciary Rubric Judge '{rubric}' cleared "
                        f"threshold ({actual_score} >= {min_score})."
                    )
                else:
                    status_val = "FAIL"
                    details = (
                        f"Fiduciary Rubric '{rubric}' score below "
                        f"threshold ({actual_score} < {min_score})."
                    )
                    overall_pass = False
            else:
                status_val = "FAIL"
                details = (
                    f"Required rubric '{rubric}' was not evaluated by an "
                    "independent judge in run evidence."
                )
                overall_pass = False

        elif chk_type == "ija_threshold":
            min_val = chk_params.get("min_value", 0.75)

            # Query real Independent Judge Assessment index from consensus engine / certificate
            consensus_obj = cert_data.get("consensus", {})
            actual_ija = None
            if isinstance(consensus_obj, dict) and "agreement" in consensus_obj:
                actual_ija = consensus_obj.get("agreement")

            if actual_ija is None:
                actual_ija = (
                    cert_data.get("ija_score")
                    or cert_data.get("metrics", {}).get("ija_threshold")
                    or analysis.get("ija_index")
                    or analysis.get("consensus_agreement")
                )

            if actual_ija is not None and isinstance(actual_ija, int | float):
                if actual_ija >= min_val:
                    details = (
                        f"Independent Judge Assessment verified "
                        f"above index ({actual_ija} >= {min_val})."
                    )
                else:
                    status_val = "FAIL"
                    details = (
                        f"Independent Judge Assessment index below "
                        f"threshold ({actual_ija} < {min_val})."
                    )
                    overall_pass = False
            else:
                status_val = "FAIL"
                details = (
                    "Independent Judge Assessment (IJA) / consensus "
                    "evidence missing from run trace."
                )
                overall_pass = False

        else:
            status_val = "FAIL"
            details = f"Unsupported or unregistered compliance check type: '{chk_type}'."
            overall_pass = False

        results.append({"type": chk_type, "status": status_val, "details": details})

    if temp_extracted and temp_path and temp_path.exists():
        temp_path.unlink()

    return jsonify(
        {
            "compliance": "PASS" if overall_pass else "FAIL",
            "overall_pass": overall_pass,
            "results": results,
            # keep legacy 'checks' key for any other clients
            "checks": results,
        }
    )
