import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from eval_runner import config, identity
from eval_runner.console.extension_publisher import (
    _private_key_pem_bytes,
    _public_key_pem_bytes,
)
from eval_runner.services.certification import execute_industrial_certification
from eval_runner.utils import crypto
from eval_runner.verifier import TraceVerifier

from ..auth_manager import Permission, active_runtime_context, require_permission
from ..providers import get_run_store

logger = logging.getLogger(__name__)

trust_bp = Blueprint("trust", __name__, url_prefix="/api")


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

    # Derive signer identity server-side from configured certification authority (P0-5 / Defect 6)
    server_identity = getattr(config, "AES_CERTIFICATION_IDENTITY", "system_id")

    try:
        from eval_runner.runtime_services import resolve_signing_backend

        signing_backend = resolve_signing_backend()
        run_store = get_run_store()
        context = active_runtime_context()
        # Classify provider ownership before invoking certification.  A
        # signing backend may also raise FileNotFoundError (for example when
        # an identity key is absent); treating every such exception as a
        # missing run incorrectly turns a cryptographic configuration failure
        # into a 404.
        if run_store.get_run(run_id, context=context) is None:
            return jsonify({"error": f"Run vault not found for {run_id}"}), 404
        result = execute_industrial_certification(
            run_id=run_id,
            identity_id=server_identity,
            status=data.get("status"),
            signing_backend=signing_backend,
            score=float(data["score"]) if data.get("score") is not None else None,
            policy_ref=data.get("policy_ref"),
            ttl=data.get("ttl"),
            scenario_data=data.get("scenario_data"),
            run_store=run_store,
            context=context,
        )
        return jsonify(result)
    except FileNotFoundError as e:
        logger.error("Certification signing material unavailable for run %s: %s", run_id, e)
        return jsonify({"error": f"Internal certification failure: {e}"}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Certification error for run {run_id}: {e}")
        return jsonify({"error": f"Internal certification failure: {e}"}), 500


@trust_bp.route("/v1/verify/<path:run_id>", methods=["GET"])
@trust_bp.route("/verify/<path:run_id>", methods=["GET"])
def public_verify_run(run_id):
    """
    Public Authoritative Verification Endpoint.
    Validates trace integrity, cryptographic signature chain, EvaluatorFinalizationRecord,
    execution truth (non-provisional), and policy compliance.
    """
    if (
        not run_id
        or not isinstance(run_id, str)
        or ".." in run_id
        or "/" in run_id
        or "\\" in run_id
    ):
        return jsonify({"error": "Invalid or unsafe run_id"}), 400

    try:
        run_store = get_run_store()
        context = active_runtime_context()
        trace_bytes = run_store.get_trace_bytes(run_id, context=context)
        manifest = run_store.get_manifest(run_id, context=context)
        if trace_bytes is None or manifest is None:
            run_rec = run_store.get_run(run_id, context=context)
            if run_rec and run_rec.get("corrupted"):
                return jsonify({"error": "Corrupt manifest", "verified": False}), 500
            return jsonify({"error": "Verification Failed: Trace or Certificate not found."}), 404

        from eval_runner.run_lifecycle import RunLifecycleState, get_run_lifecycle_state

        lifecycle_state = get_run_lifecycle_state(
            run_id,
            run_store=run_store,
            context=context,
        )
        if lifecycle_state != RunLifecycleState.SEALED:
            return (
                jsonify(
                    {
                        "error": (
                            f"Verification Failed: Run '{run_id}' is not sealed "
                            f"(state: {lifecycle_state.value})."
                        ),
                        "verified": False,
                        "lifecycle_state": lifecycle_state.value,
                    }
                ),
                400,
            )

        canonical_m = manifest.get("execution_manifest") or manifest
        scen_data = manifest.get("scenario_data") or manifest.get("scenario")

        # 1. Authoritative verification check via provider-owned artifacts.
        is_valid = TraceVerifier.verify_trace(
            trace_bytes,
            manifest,
            run_store=run_store,
            context=context,
            scenario_data=scen_data,
        )

        # 2. Independent Package Artifacts Verification if package is present
        if is_valid and manifest.get("verification_package"):
            from eval_runner.verifier import VerificationAuthority

            raw_bytes = trace_bytes
            events_data: list[dict[str, Any]] = []
            try:
                for line in raw_bytes.decode("utf-8").splitlines():
                    trimmed = line.strip()
                    if trimmed:
                        events_data.append(json.loads(trimmed))
            except Exception as ev_err:
                logger.debug("Failed parsing trace events in public_verify_run: %s", ev_err)

            canonical_m = manifest.get("execution_manifest") or manifest
            scen_data = manifest.get("scenario_data") or manifest.get("scenario")

            pkg_res = VerificationAuthority.verify_package_artifacts(
                package=manifest["verification_package"],
                raw_trace_bytes=raw_bytes,
                raw_trace_events=events_data,
                canonical_manifest=canonical_m,
                scenario_data=scen_data,
            )
            if not pkg_res.get("verified"):
                logger.warning(
                    "Public verify package artifact verification failed: %s",
                    pkg_res.get("failures"),
                )
                is_valid = False

        method = "SHA3-256 integrity check"
        if manifest.get("provenance_chain"):
            method = "ED25519 cryptographic signature proof"

        # 3. Disentangle raw integrity from authoritative certification
        compliance = manifest.get("compliance", {})
        status = compliance.get("status") or manifest.get("compliance_status") or "UNKNOWN"
        score = compliance.get("score")
        if score is None:
            score = manifest.get("compliance_score")

        is_compliant = str(status).lower() in ["certified", "pass", "passed"]

        # Mode-Aware Truth Level Enforcement (P0-07)
        clean_mode = str(manifest.get("execution_mode", "")).strip().lower()
        is_authoritative = bool(not manifest.get("provisional", False) and clean_mode == "live")
        verified = bool(
            is_valid
            and is_compliant
            and is_authoritative
            and lifecycle_state == RunLifecycleState.SEALED
        )

        if verified:
            terminal_verdict = "CERTIFIED_PASS"
        elif not is_authoritative:
            terminal_verdict = "PROVISIONAL"
        elif is_valid and not is_compliant and lifecycle_state == RunLifecycleState.SEALED:
            terminal_verdict = "ATTESTED_FAIL"
        else:
            terminal_verdict = "UNVERIFIED"

        return jsonify(
            {
                "run_id": run_id,
                "verified": verified,
                "terminal_verdict": terminal_verdict,
                "file_integrity_valid": is_valid,
                "cryptographically_valid": is_valid,
                "certificate_valid": is_valid,
                "evaluation_passed": is_compliant,
                "evaluation_verdict": status,
                "compliance_score": score,
                "policy_compliant": is_compliant,
                "certificate_authoritative": is_authoritative,
                "execution_mode": clean_mode or "unknown",
                "lifecycle_state": lifecycle_state.value,
                "timestamp": datetime.now().astimezone().isoformat(),
                "method": method,
                "certificate_hash": (
                    manifest.get("certificate_hash") or manifest.get("package_hash")
                ),
                "package_hash": manifest.get("package_hash"),
                "trace_hash": manifest.get("trace_hash"),
            }
        )
    except Exception as e:
        logger.exception("Verification error for run %s: %s", run_id, e)
        return jsonify({"error": f"Verification failed: {str(e)}", "verified": False}), 500


verify_run_public = public_verify_run


@trust_bp.route("/v1/verify/<path:run_id>/manifest", methods=["GET"])
@require_permission(Permission.RUNS_READ)
def get_verified_run_manifest(run_id):
    """Authenticated endpoint for audit-level manifest inspection."""
    if (
        not run_id
        or not isinstance(run_id, str)
        or ".." in run_id
        or "/" in run_id
        or "\\" in run_id
    ):
        return jsonify({"error": "Invalid or unsafe run_id"}), 400

    try:
        run = get_run_store().get_run(run_id, context=active_runtime_context())
        if run and run.get("corrupted"):
            return jsonify({"error": "Failed to load manifest: corrupt file"}), 500
        manifest = get_run_store().get_manifest(run_id, context=active_runtime_context())
        if manifest is None:
            return jsonify({"error": "Manifest not found for run."}), 404
        return jsonify(manifest), 200
    except Exception as e:
        return jsonify({"error": f"Failed to load manifest: {e}"}), 500


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
        from eval_runner.runtime_services import resolve_signing_backend

        signer = resolve_signing_backend()
        signature_hex = signer.sign_payload(canonical, pem)
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


@trust_bp.route("/v1/extensions/publish", methods=["POST"])
@require_permission(Permission.CERTIFY_WRITE)
def publish_extension_bundle():
    """Publish a signed ESM extension from the Runtime's configured source/store."""
    from eval_runner.console.extension_publisher import publish_extension

    data = request.json or {}
    entry_value = data.get("entry")
    if not isinstance(entry_value, str):
        return jsonify({"error": "entry must be a configured local ESM path"}), 400
    source_root = Path(os.getenv("AGENTV_EXTENSION_SOURCE_ROOT", config.PROJECT_ROOT)).resolve()
    entry = Path(entry_value).resolve()
    if source_root not in entry.parents:
        return jsonify({"error": "entry is outside the configured extension source root"}), 400
    try:
        descriptor = publish_extension(
            entry=entry,
            extension_id=str(data.get("extension_id") or ""),
            publisher=str(data.get("publisher") or ""),
            version=str(data.get("version") or ""),
            private_key_pem=_private_key_pem_bytes,
            manifest_declaration=data.get("manifest"),
            activate=bool(data.get("activate", False)),
        )
    except (OSError, ValueError) as exc:
        logger.warning("[Extensions] publish rejected: %s", exc)
        return jsonify({"error": str(exc)}), 400
    return jsonify(descriptor), 201


@trust_bp.route("/v1/extensions/unpublish", methods=["POST"])
@require_permission(Permission.CERTIFY_WRITE)
def unpublish_extension_bundle():
    """Authenticated, idempotent withdrawal of a Runtime-owned release."""
    from eval_runner.console.extension_publisher import unpublish_extension

    data = request.json or {}
    extension_id = data.get("extension_id")
    version = data.get("extension_version")
    if not isinstance(extension_id, str) or not isinstance(version, str):
        return jsonify({"error": "extension_id and extension_version are required"}), 400
    try:
        return jsonify(unpublish_extension(extension_id=extension_id, version=version))
    except (OSError, ValueError) as exc:
        logger.warning("[Extensions] unpublish rejected: %s", exc)
        return jsonify({"error": str(exc)}), 400


@trust_bp.route("/v1/extensions/verify", methods=["POST"])
@require_permission(Permission.CERTIFY_WRITE)
def verify_extension_bundle():
    from eval_runner.console.extension_publisher import verify_extension

    data = request.json or {}
    if not isinstance(data.get("extension_id"), str) or not isinstance(
        data.get("extension_version"), str
    ):
        return jsonify({"error": "extension_id and extension_version are required"}), 400
    result = verify_extension(
        extension_id=data["extension_id"],
        version=data["extension_version"],
        public_key_pem=_public_key_pem_bytes,
    )
    return jsonify(result), (200 if result["valid"] else 409)


@trust_bp.route("/v1/extensions/repair", methods=["POST"])
@require_permission(Permission.CERTIFY_WRITE)
def repair_extension_bundle():
    from eval_runner.console.extension_publisher import repair_extension

    data = request.json or {}
    required = ("entry", "extension_id", "publisher", "extension_version")
    if not all(isinstance(data.get(name), str) for name in required):
        return jsonify(
            {"error": "entry, extension_id, publisher, and extension_version are required"}
        ), 400
    source_root = Path(os.getenv("AGENTV_EXTENSION_SOURCE_ROOT", config.PROJECT_ROOT)).resolve()
    entry = Path(data["entry"]).resolve()
    if source_root not in entry.parents:
        return jsonify({"error": "entry is outside the configured extension source root"}), 400
    try:
        return jsonify(
            repair_extension(
                entry=entry,
                extension_id=data["extension_id"],
                publisher=data["publisher"],
                version=data["extension_version"],
                public_key_pem=_public_key_pem_bytes,
            )
        )
    except (OSError, ValueError) as exc:
        logger.warning("[Extensions] repair rejected: %s", exc)
        return jsonify({"error": str(exc)}), 400


@trust_bp.route("/v1/extensions/activate", methods=["POST"])
@require_permission(Permission.CERTIFY_WRITE)
def activate_extension_bundle():
    from eval_runner.console.extension_publisher import activate_extension

    data = request.json or {}
    extension_id = data.get("extension_id")
    version = data.get("extension_version") or data.get("version")
    publisher = data.get("publisher")
    if not isinstance(extension_id, str) or not isinstance(version, str):
        return jsonify({"error": "extension_id and extension_version are required"}), 400
    try:
        res = activate_extension(
            extension_id=extension_id,
            version=version,
            publisher=publisher,
            public_key_pem=_public_key_pem_bytes,
        )
        return jsonify(res), 200
    except (OSError, ValueError) as exc:
        logger.warning("[Extensions] activate rejected: %s", exc)
        return jsonify({"error": str(exc)}), 400


@trust_bp.route("/v1/extensions/rollback", methods=["POST"])
@require_permission(Permission.CERTIFY_WRITE)
def rollback_extension_bundle():
    from eval_runner.console.extension_publisher import rollback_extension

    data = request.json or {}
    extension_id = data.get("extension_id")
    version = data.get("extension_version") or data.get("version")
    publisher = data.get("publisher")
    if not isinstance(extension_id, str) or not isinstance(version, str):
        return jsonify({"error": "extension_id and extension_version are required"}), 400
    try:
        res = rollback_extension(
            extension_id=extension_id,
            version=version,
            publisher=publisher,
            public_key_pem=_public_key_pem_bytes,
        )
        return jsonify(res), 200
    except (OSError, ValueError) as exc:
        logger.warning("[Extensions] rollback rejected: %s", exc)
        return jsonify({"error": str(exc)}), 400


@trust_bp.route("/v1/extensions/active", methods=["GET"])
def get_active_extensions_endpoint():
    from eval_runner.console.extension_publisher import get_active_release, list_active_releases

    extension_id = request.args.get("extension_id")
    publisher = request.args.get("publisher")
    if extension_id:
        active = get_active_release(extension_id=extension_id, publisher=publisher)
        if not active:
            return jsonify({"status": "not_found", "extension_id": extension_id}), 404
        return jsonify(active), 200
    return jsonify(list_active_releases()), 200


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

    # Verification key MUST resolve exclusively from the verified publisher identity.
    # Never accept an independent signer identity.
    caller_identity = data.get("identity_id")
    if caller_identity and caller_identity != publisher:
        return jsonify(
            {
                "valid": False,
                "tier": tier,
                "reason": "signer-identity-mismatch",
                "publisher": publisher,
                "identity_id": caller_identity,
            }
        ), 400

    identity_id = publisher

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

    from eval_runner.runtime_services import resolve_signing_backend

    signer = resolve_signing_backend()
    valid = signer.verify_signature(_canonical_manifest_bytes(manifest), signature_hex, pub_pem)

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
