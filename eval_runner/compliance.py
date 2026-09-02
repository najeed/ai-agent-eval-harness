import json
import logging

from . import config

logger = logging.getLogger(__name__)


class ComplianceService:
    """
    Industrial Compliance Orchestrator for the Trust Protocol.
    Provides high-fidelity status checks for Post-Quantum Cryptography (PQC)
    and forensic evidence manifests.
    """

    def check_pqc_status(self, run_id: str) -> dict:
        """
        Evaluates the PQC status of a run based on its Verification Certificate (VC).
        Returns a structured status dictionary aligned with NIST AI-100-1 audit standards.
        Cryptographically verifies the ML-DSA-65 signature against the canonical manifest payload.
        """
        from . import forensics
        from .identity import IdentityService

        run_dir = config.RUN_LOG_DIR / run_id
        manifest_path = run_dir / "run_manifest.json"

        if not manifest_path.exists():
            logger.warning(f"Compliance check failed: Manifest missing for {run_id}")
            return {"quantum_safe": False, "reason": "Manifest missing"}

        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)

            chain = manifest.get("provenance_chain", [])
            # Search for ML-DSA-65 (Post-Quantum) signature node
            pqc_nodes = [node for node in chain if node.get("algorithm") == "ML-DSA-65"]

            if pqc_nodes:
                pqc_node = pqc_nodes[0]
                sig_hex = pqc_node.get("signature", "")
                identity_id = pqc_node.get("identity", config.PQC_IDENTITY_ID)

                # Reconstruct canonical signed payload
                manifest_to_verify = {
                    k: v
                    for k, v in manifest.items()
                    if k not in ("provenance_chain", "certification", "signing_context")
                }
                manifest_bytes = json.dumps(manifest_to_verify, sort_keys=True).encode("utf-8")
                shake_digest = forensics.compute_shake256_digest(manifest_bytes)

                pqc_client = IdentityService.get_pqc_client()
                if not pqc_client:
                    logger.warning(
                        f"PQC client not available for {identity_id}; "
                        "cannot cryptographically verify ML-DSA-65 signature."
                    )
                    return {
                        "quantum_safe": False,
                        "status": "unverifiable",
                        "algorithm": "ML-DSA-65",
                        "reason": (
                            f"PQC client not available to verify ML-DSA-65 signature "
                            f"for {identity_id}"
                        ),
                    }

                is_valid = pqc_client.verify_digest(
                    signature=sig_hex,
                    digest=shake_digest,
                    identity_id=identity_id,
                )
                if not is_valid:
                    return {
                        "quantum_safe": False,
                        "algorithm": "ML-DSA-65",
                        "reason": f"PQC signature verification failed for {identity_id}",
                    }

                return {
                    "quantum_safe": True,
                    "algorithm": "ML-DSA-65",
                    "provider": pqc_node.get("provider", config.PQC_PROVIDER),
                    "timestamp": pqc_node.get("timestamp"),
                }

            # Fallback analysis: determine the strongest classical algorithm present
            fallback = chain[0].get("algorithm") if chain else "None"
            return {
                "quantum_safe": False,
                "algorithm": fallback,
                "reason": "Classical-only signature chain detected",
            }
        except Exception as e:
            logger.error(f"Failed to parse manifest for compliance check: {e}")
            return {"quantum_safe": False, "reason": str(e)}

    def _evaluate_metrics_pack(self, metrics: dict) -> dict:
        """
        Behavioral metrics evaluation — FAIL-CLOSED in OSS.

        The previous implementation unconditionally returned ``pass: True`` regardless of input,
        which made an unscored audit gate read as compliant. Unscored metrics can
        never imply compliance: with no evaluator wired, the honest verdict
        is NOT_EVALUATED and the caller's ``compliant`` computation treats it
        as non-asserting (never silently passing).
        """
        if not metrics:
            return {
                "status": "NOT_EVALUATED",
                "pass": False,
                "details": [],
                "metrics_evaluated": 0,
                "reason": (
                    "No behavioral metric evaluator is wired into the OSS "
                    "runtime; metrics packs are not evaluated here."
                ),
            }
        return {
            "status": "NOT_EVALUATED",
            "pass": False,
            "details": [],
            "metrics_evaluated": len(metrics),
            "reason": (
                "Behavioral metric evaluation is not implemented in the OSS "
                "runtime; supplied metrics are recorded but NOT scored. "
                "Compliance claims must not rely on this field."
            ),
        }


def evaluate_compliance(run_id: str, metrics: dict | None = None) -> dict:
    """
    Industrial Gatekeeping Utility.
    Enforces compliance policies with strict Tri-State Audit Invariants:
    'COMPLIANT' | 'NON_COMPLIANT' | 'NOT_EVALUATED'.
    """
    metrics = metrics or {}
    service = ComplianceService()
    pqc_status = service.check_pqc_status(run_id)
    metrics_eval = service._evaluate_metrics_pack(metrics)

    # --- [Tri-State Audit Invariant] ---
    # Cryptographic proof (PQC) alone can NEVER imply behavioral compliance.
    # When behavioral metrics are un-evaluated, the status is strictly NOT_EVALUATED.
    if config.PQC_STRICT_MODE and not pqc_status.get("quantum_safe"):
        status = "NON_COMPLIANT"
        compliant = False
        message = "NON-COMPLIANT: PQC_STRICT_MODE enabled but manifest lacks quantum-safe proof."
        logger.error(f"[Compliance] {message}")
    elif metrics_eval.get("status") == "NOT_EVALUATED":
        status = "NOT_EVALUATED"
        compliant = False
        message = (
            "NOT_EVALUATED: Behavioral metrics are not evaluated in the standalone OSS runtime; "
            "cryptographic PQC proof alone cannot imply behavioral compliance."
        )
    elif metrics_eval.get("pass") and pqc_status.get("quantum_safe"):
        status = "COMPLIANT"
        compliant = True
        message = "COMPLIANT: Both quantum-safe cryptographic proof and behavioral metrics passed."
    else:
        status = "NON_COMPLIANT"
        compliant = False
        message = "NON-COMPLIANT: One or more compliance requirements failed."

    return {
        "status": status,
        "compliant": compliant,
        "message": message,
        "pqc_status": pqc_status,
        "metrics_eval": metrics_eval,
        # Explicit marker for downstream consumers/auditors.
        "behavioral_metrics": "not_evaluated_in_oss",
    }
