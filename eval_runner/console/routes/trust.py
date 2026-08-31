import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from eval_runner import config, identity
from eval_runner.reference.signing import LocalEd25519SigningBackend
from eval_runner.services.certification import (
    CertificationService,
    execute_industrial_certification,
)
from eval_runner.utils import crypto
from eval_runner.utils.safe_path import is_path_safe
from eval_runner.verifier import TraceVerifier, locate_certificate_file

from ..auth_manager import Permission, require_permission
from .runs import resolve_trace_path

logger = logging.getLogger(__name__)

trust_bp = Blueprint("trust", __name__, url_prefix="/api")


def _read_run_truth_level(run_id: str) -> tuple[str | None, bool]:
    """Compatibility wrapper delegating to CertificationService."""
    return CertificationService.read_run_truth_level(run_id)


def _extract_computed_run_outcome(vault_dir: Path, target_trace: Path) -> tuple[str, float]:
    """Compatibility wrapper delegating to CertificationService."""
    return CertificationService.extract_computed_run_outcome(vault_dir, target_trace)


@trust_bp.route("/v1/certify", methods=["POST"])
@require_permission(Permission.CERTIFY_WRITE)
def certify_run():
    """REST wrapper for the industrial certification service."""
    data = request.json or {}
    run_id = data.get("run_id")
    if (
        not run_id
        or not isinstance(run_id, str)
        or ".." in run_id
        or "/" in run_id
        or "\\" in run_id
    ):
        return jsonify({"error": "Valid run_id is required"}), 400

    try:
        result = execute_industrial_certification(
            run_id=run_id,
            identity_id=data.get("identity", "system_id"),
            status=data.get("status"),
            score=float(data["score"]) if data.get("score") is not None else None,
            policy_ref=data.get("policy_ref"),
            ttl=data.get("ttl"),
        )
        return jsonify(result)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"   [Certification] 500 ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 500


@trust_bp.route("/v1/verify/<path:run_id>", methods=["GET"])
def verify_run_public(run_id):
    """Public Verification API (Unprotected)."""
    if (
        not run_id
        or not isinstance(run_id, str)
        or ".." in run_id
        or "/" in run_id
        or "\\" in run_id
    ):
        return jsonify({"error": "Invalid or unsafe run_id"}), 400

    trace_path = resolve_trace_path(run_id)
    if (
        not trace_path
        or not is_path_safe(trace_path, config.RUN_LOG_DIR)
        or not trace_path.exists()
    ):
        return jsonify({"error": "Verification Failed: Trace or Certificate not found."}), 404

    manifest_path = locate_certificate_file(run_id)
    if not manifest_path or not manifest_path.exists():
        return jsonify({"error": "Verification Failed: Trace or Certificate not found."}), 404

    try:
        is_valid = TraceVerifier.verify_trace(str(trace_path), str(manifest_path))
        method = "SHA3-256 integrity check"
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
            if manifest.get("provenance_chain"):
                method = "ED25519 cryptographic signature proof"

        # Disentangle cryptographic validity from threshold compliance
        compliance = manifest.get("compliance", {})
        status = compliance.get("status") or manifest.get("compliance_status") or "UNKNOWN"
        score = compliance.get("score")
        if score is None:
            score = manifest.get("compliance_score")

        is_compliant = str(status).lower() in ["certified", "pass", "passed"]
        verified = bool(is_valid and is_compliant)

        return jsonify(
            {
                "run_id": run_id,
                "verified": verified,
                "cryptographically_valid": is_valid,
                "certificate_valid": is_valid,
                "evaluation_passed": is_compliant,
                "evaluation_verdict": status,
                "compliance_score": score,
                "policy_compliant": is_compliant,
                "certificate_authoritative": not manifest.get("provisional", False),
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
        if key is None:
            return jsonify({"error": f"Identity {identity_id} not found."}), 404
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


# ---------------------------------------------------------------------------
# [D1] Extension publisher signing & verification (tier enforcement backend)
#
# Signing keys live under the configured TRUST_ROOT (dev trust root:
# TRUST_ROOT/<identity_id>/private_key.pem, auto-provisioned for developer
# identities). Signatures cover RuntimeExtension.canonical_bytes() — the
# deterministic manifest serialization that EXCLUDES the signature field —
# so verification is exact across runtimes.
# ---------------------------------------------------------------------------

DEFAULT_DEV_PUBLISHER_IDENTITY = "dev_publisher"


def _private_key_pem_bytes(identity_id: str) -> bytes:
    from cryptography.hazmat.primitives import serialization

    key = identity.IdentityService.get_private_key(identity_id, auto_provision=True)
    if key is None:
        raise ValueError(f"No signing identity available for '{identity_id}'")
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _public_key_pem_bytes(identity_id: str) -> bytes | None:
    from cryptography.hazmat.primitives import serialization

    key = identity.IdentityService.get_public_key(identity_id, auto_provision=False)
    if key is None:
        return None
    return key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _canonical_manifest_bytes(manifest: dict) -> bytes:
    """
    [D1] Canonical signing payload over the RAW transmitted manifest dict
    (every field bound, unknown fields included), excluding 'signature'.
    Strictly stronger than the dataclass round-trip: from_dict() silently
    ignores undeclared keys, which would otherwise escape the signature.
    """
    payload = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parse_manifest_or_error(manifest: Any, *, require_signature: bool = True):
    """Returns (RuntimeExtension, None) or (None, (response, status))."""
    from agentv_runtime.extension_contract import ExtensionContractError, RuntimeExtension

    if not isinstance(manifest, dict):
        return None, (jsonify({"error": "manifest must be a JSON object"}), 400)
    try:
        ext = RuntimeExtension.from_dict(manifest)
    except ExtensionContractError as e:
        return None, (jsonify({"error": f"Invalid manifest: {e}"}), 400)
    violations = ext.validate(require_signature=require_signature)
    if violations:
        return None, (
            jsonify(
                {
                    "error": "Manifest violates the extension contract",
                    "violations": violations,
                }
            ),
            400,
        )
    return ext, None


@trust_bp.route("/v1/extensions/sign", methods=["POST"])
@require_permission(Permission.CERTIFY_WRITE)
def sign_extension_manifest():
    """
    Dev trust-root signing: signs a contract-valid manifest with the named
    (auto-provisioned) publisher identity under TRUST_ROOT and returns the
    signature to embed in `manifest.signature`.
    """
    data = request.json or {}
    manifest = data.get("manifest")
    identity_id = str(data.get("identity_id") or DEFAULT_DEV_PUBLISHER_IDENTITY)

    # Signing precedes the signature existing: structural validation only.
    ext, err = _parse_manifest_or_error(manifest, require_signature=False)
    if err is not None:
        return err

    try:
        pem = _private_key_pem_bytes(identity_id)
        canonical = _canonical_manifest_bytes(manifest)
        signature_hex = LocalEd25519SigningBackend().sign_payload(canonical, pem)
    except Exception as e:
        logger.error(f"[Extensions] Signing failed for '{identity_id}': {e}")
        return jsonify({"error": f"Signing failed: {e}"}), 500

    return jsonify(
        {
            "status": "success",
            "identity_id": identity_id,
            "algorithm": "ed25519",
            "signature": signature_hex,
            "canonical_sha3_256": crypto.checksum(canonical),
        }
    )


@trust_bp.route("/v1/extensions/verify-publisher", methods=["POST"])
@require_permission(Permission.RUNS_READ)
def verify_extension_publisher():
    """
    Verifies a manifest's Ed25519 signature against the publisher's
    trust-root public key. Fail-closed: any missing or unresolvable element
    yields valid=False with an explicit reason and an 'unsigned-local' /
    'invalid-signature' tier.
    """
    data = request.json or {}
    manifest = data.get("manifest")

    if not isinstance(manifest, dict):
        return jsonify({"error": "manifest must be a JSON object"}), 400

    tier = "unsigned-local"
    signature_hex = str(manifest.get("signature") or "")
    publisher = str(manifest.get("publisher") or "")

    # Structural validation FIRST: a contract-violating manifest is rejected
    # regardless of what its signature field contains.
    ext, err = _parse_manifest_or_error(manifest, require_signature=False)
    if err is not None:
        resp, code = err
        body = resp.get_json()
        return jsonify(
            {
                "valid": False,
                "tier": tier,
                "reason": "contract-violation",
                "violations": body.get("violations") or [body.get("error")],
                "publisher": publisher,
            }
        ), code

    if not signature_hex:
        return jsonify(
            {
                "valid": False,
                "tier": tier,
                "reason": "missing-signature",
                "publisher": publisher,
            }
        )
    if not publisher:
        return jsonify(
            {
                "valid": False,
                "tier": tier,
                "reason": "missing-publisher",
                "publisher": publisher,
            }
        )

    identity_id = str(data.get("identity_id") or publisher)

    pub_pem = _public_key_pem_bytes(identity_id)
    if pub_pem is None:
        return jsonify(
            {
                "valid": False,
                "tier": tier,
                "reason": "unknown-publisher",
                "publisher": publisher,
                "identity_id": identity_id,
            }
        )

    valid = LocalEd25519SigningBackend().verify_signature(
        _canonical_manifest_bytes(manifest), signature_hex, pub_pem
    )

    # [Trust hardening] The BACKEND owns tier classification. A signed
    # manifest cannot self-promote to 'official': only publishers listed in
    # AGENTV_OFFICIAL_PUBLISHERS (comma-separated identities) receive it.
    official_publishers = {
        p.strip().lower()
        for p in os.getenv("AGENTV_OFFICIAL_PUBLISHERS", "").split(",")
        if p.strip()
    }
    if not valid:
        authoritative_tier = "invalid-signature"
        reason = "signature-mismatch"
    elif publisher.lower() in official_publishers:
        authoritative_tier = "official"
        reason = "signature-verified"
    else:
        authoritative_tier = "community"
        reason = "signature-verified"

    return jsonify(
        {
            "valid": valid,
            # Authoritative classification — the frontend MUST consume this
            # value and ignore any tier the manifest declares about itself.
            "tier": authoritative_tier,
            "reason": reason,
            "publisher": publisher,
            "identity_id": identity_id,
            "algorithm": "ed25519",
        }
    )
