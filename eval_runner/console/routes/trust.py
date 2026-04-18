import json
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request

from eval_runner import config, identity
from eval_runner.verifier import TraceVerifier

from ..auth_manager import Permission, require_permission

logger = logging.getLogger(__name__)

trust_bp = Blueprint("trust", __name__, url_prefix="/api")


def execute_industrial_certification(
    run_id: str,
    identity_id: str = "system_id",
    status: str = "pass",
    score: float = 1.0,
    policy_ref: str | None = None,
    ttl: int | None = None,
) -> dict:
    """
    Authoritative Industrial Certification Service.
    Can be called via REST or directly by trusted plugins.
    """
    # 1. Authoritative Vault Resolution (Strict Affinity)
    vault_dir = (config.RUN_LOG_DIR / run_id).resolve()
    target_trace = (vault_dir / "run.jsonl").resolve()

    if not target_trace.exists():
        logger.error(
            f"   [Certification] 404 FAIL: Authoritative vault trace not found at {target_trace}"
        )
        raise FileNotFoundError(f"Run vault not found for {run_id}")

    # 2. Authoritative Signature Execution (Zero-Copy)
    manifest = TraceVerifier.sign_trace(
        str(target_trace),
        run_id=run_id,
        identity_id=identity_id,
        compliance_status=status,
        compliance_score=score,
        policy_ref=policy_ref,
        ttl_days=ttl or config.GOVERNANCE_TTL_DAYS,
    )

    # 3. Authoritative Manifest Save (Within the Vault)
    manifest_path = vault_dir / "run_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        import json

        json.dump(manifest, f, indent=2)

    return {
        "status": "certified",
        "run_id": run_id,
        "manifest": {
            "sha256": manifest.get("sha256"),
            "manifest_path": str(manifest_path),
            "certified_at": datetime.now().isoformat(),
        },
    }


@trust_bp.route("/v1/certify", methods=["POST"])
@require_permission(Permission.CERTIFY_WRITE)
def certify_run():
    """REST wrapper for the industrial certification service."""
    data = request.json or {}
    run_id = data.get("run_id")
    if not run_id:
        return jsonify({"error": "run_id is required"}), 400

    try:
        result = execute_industrial_certification(
            run_id=run_id,
            identity_id=data.get("identity", "system_id"),
            status=data.get("status", "pass"),
            score=float(data.get("score", 1.0)),
            policy_ref=data.get("policy_ref"),
            ttl=data.get("ttl"),
        )
        return jsonify(result)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(f"   [Certification] 500 ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 500


@trust_bp.route("/v1/verify/<run_id>", methods=["GET"])
def verify_run_public(run_id):
    """Public Verification API (Unprotected)."""
    run_dir = (config.RUN_LOG_DIR / run_id).resolve()
    trace_path = (run_dir / "run.jsonl").resolve()
    manifest_path = (run_dir / "run_manifest.json").resolve()

    if not manifest_path.exists() or not trace_path.exists():
        return jsonify({"error": "Verification Failed: Trace or Certificate not found."}), 404

    try:
        is_valid = TraceVerifier.verify_trace(str(trace_path), str(manifest_path))
        method = "SHA-256 integrity check"
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
            if manifest.get("provenance_chain"):
                method = "ED25519 cryptographic signature proof"

        # [Staff Hardening] Score-First Compliance Check (AgentV v1.5.0)
        compliance = manifest.get("compliance", {})
        status = compliance.get("status") or manifest.get("compliance_status")
        score = compliance.get("score")
        if score is None:
            score = manifest.get("compliance_score")

        # Unauthorized if status is fail or score < 1.0
        is_compliant = status in ["CERTIFIED", "pass", "certified"]
        if score is not None and float(score) < 1.0:
            is_compliant = False

        return jsonify(
            {
                "run_id": run_id,
                "verified": is_valid and is_compliant,
                "timestamp": datetime.now().astimezone().isoformat(),
                "method": method,
                "manifest": manifest,
            }
        )
    except Exception as e:
        return jsonify({"error": f"Verification failed: {str(e)}", "verified": False}), 500


@trust_bp.route("/v1/identity/<identity_id>/public_key", methods=["GET"])
def get_identity_public_key(identity_id):
    """Resolves the PEM public key for a given identity."""
    try:
        from cryptography.hazmat.primitives import serialization

        key = identity.IdentityService.get_public_key(identity_id, auto_provision=False)
        pem = key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        return jsonify({"identity_id": identity_id, "public_key": pem})
    except Exception as e:
        logger.error(f"Failed to resolve public key for {identity_id}: {e}")
        return jsonify(
            {"error": f"Identity {identity_id} not found or key resolution failed."}
        ), 404
