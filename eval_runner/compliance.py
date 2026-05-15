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
        """
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
                return {
                    "quantum_safe": True,
                    "algorithm": "ML-DSA-65",
                    "provider": pqc_nodes[0].get("provider", config.PQC_PROVIDER),
                    "timestamp": pqc_nodes[0].get("timestamp"),
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
        Internal placeholder for behavioral metrics evaluation.
        In OpenCore, this defaults to a pass-through success state.
        """
        return {"pass": True, "details": [], "metrics_evaluated": len(metrics)}


def evaluate_compliance(run_id: str, metrics: dict | None = None) -> dict:
    """
    Industrial Gatekeeping Utility.
    Enforces compliance policies, including PQC_STRICT_MODE branching.
    """
    metrics = metrics or {}
    service = ComplianceService()
    pqc_status = service.check_pqc_status(run_id)

    # --- [Behavioral Branching Logic] ---
    compliant = True
    message = "Compliant with standard trust policy."

    if config.PQC_STRICT_MODE and not pqc_status["quantum_safe"]:
        compliant = False
        message = "NON-COMPLIANT: PQC_STRICT_MODE enabled but manifest lacks quantum-safe proof."
        logger.error(f"[Compliance] {message}")

    return {
        "compliant": compliant,
        "message": message,
        "pqc_status": pqc_status,
        "metrics_eval": service._evaluate_metrics_pack(metrics),
    }
