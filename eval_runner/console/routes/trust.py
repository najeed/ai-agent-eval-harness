import json
import logging
from datetime import datetime

from flask import Blueprint, jsonify

from eval_runner import config, identity
from eval_runner.verifier import TraceVerifier

logger = logging.getLogger(__name__)

trust_bp = Blueprint("trust", __name__, url_prefix="/api")


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

        return jsonify(
            {
                "run_id": run_id,
                "verified": is_valid,
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
