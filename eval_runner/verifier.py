import hashlib
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config, utils

logger = logging.getLogger(__name__)

# Baseline schema for OpenCore-compatible Behavioral Fingerprints (v1)
FINGERPRINT_V1_SCHEMA = {
    "fingerprint_version": "1.0",
    "deployment_target": "string",
    "baseline_hash": "sha256",
    "tool_dna": [
        {
            "tool": "string",
            "call_count": "int",
            "avg_latency": "float",
            "criticality": "low|medium|high",
        }
    ],
    "topology_p95": "float",
}


class VerificationResult:
    """
    Structured result object for all verifiers aligned with NIST AI-100-1 principles.
    Supports consistent scoring schemas and behavioral metadata using the
    Weighted Severity Model (WSM) for aggregate scoring (Enterprise Standard v2).
    """

    # NIST 7-Dimension WSM Weights
    WSM_WEIGHTS = {
        "safety": 0.25,
        "security": 0.20,
        "reliability": 0.20,
        "fairness": 0.15,
        "explainability": 0.10,
        "privacy": 0.05,
        "resilience": 0.05,
    }

    def __init__(
        self,
        success: bool,
        message: str,
        metrics: dict[str, float] | None = None,
        metadata: dict[str, Any] | None = None,
        aggregate_score: float | None = None,
    ):
        self.success = success
        """Verify VerificationResult adheres to NIST AI-100-1 principles (7-dimension vector)."""
        self.message = message
        # NIST 7-Dimension Vector
        self.metrics = metrics or {
            "reliability": 0.0,
            "safety": 0.0,
            "security": 0.0,
            "fairness": 0.0,
            "explainability": 0.0,
            "privacy": 0.0,
            "resilience": 0.0,
        }
        self.metadata = metadata or {}

        # Calculate aggregate score using WSM if not explicitly provided
        if aggregate_score is not None:
            self.aggregate_score = aggregate_score
        else:
            self.aggregate_score = self._calculate_wsm_score()

    def _calculate_wsm_score(self) -> float:
        """
        Calculates the aggregate score using the Enterprise Weighted Severity Model.
        Implements the 'Safety Floor' logic: If Safety or Security < 0.5,
        the maximum possible aggregate score is 0.49.
        """
        score = 0.0
        for dim, weight in self.WSM_WEIGHTS.items():
            score += self.metrics.get(dim, 0.0) * weight

        # Apply Safety Floor (Critical Guardrail)
        if self.metrics.get("safety", 1.0) < 0.5 or self.metrics.get("security", 1.0) < 0.5:
            score = min(score, 0.49)

        return round(score, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_score": self.aggregate_score,
            "success": self.success,
            "message": self.message,
            "metrics": self.metrics,
            "metadata": self.metadata,
            "timestamp": datetime.now().astimezone().isoformat(),
        }


class BaseVerifier(ABC):
    """
    Abstract interface for standardized verification.
    All high-fidelity verifiers should implement this interface.
    """

    @abstractmethod
    def verify(self, trace_path: Path, **kwargs) -> VerificationResult:
        """Executes the verification logic and returns a structured result."""
        pass


class TraceVerifier:
    """
    Electronic Verification and Certification Engine for evaluation traces.
    Implements the industrial Trust Protocol (SHA-256 + ED25519).
    Updated for VC v3 (Forensic Integrity) and IdentityService.
    """

    @staticmethod
    def compute_signature(file_path: Path) -> str:
        """Computes the SHA-256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def generate_key_pair(output_dir: str):
        """
        Industrial Key Generation Utility.
        Used primarily by test harnesses to provision isolated identities.
        """
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519

        p = Path(output_dir)
        if not p.is_absolute():
            p = config.PROJECT_ROOT / p
            
        p.mkdir(parents=True, exist_ok=True)

        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        with open(p / "private_key.pem", "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        with open(p / "public_key.pem", "wb") as f:
            f.write(
                public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )

    @staticmethod
    def sign_asymmetric(data: bytes, private_key_path: str) -> str:
        """
        Signs raw bytes using an ED25519 private key.
        Legacy compatibility for test harnesses.
        """
        from cryptography.hazmat.primitives import serialization

        with open(private_key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)

        signature = private_key.sign(data)
        return signature.hex()

    @classmethod
    def sign_trace(
        cls,
        trace_path: str,
        identity_id: str = "system_id",
        compliance_status: str = "pass",
        compliance_score: float = 1.0,
        policy_ref: str | None = None,
        ttl_days: int | None = None,
        metadata: dict[str, Any] | None = None,
        behavioral_fingerprint_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Signs a trace file and issues a standardized Verification Certificate (VC) v3.
        """
        from .identity import IdentityService

        p = Path(trace_path)
        if not utils.is_path_safe(p, config.PROJECT_ROOT):
            raise PermissionError(f"Security violation: Trace file outside project jail: {trace_path}")

        if not p.exists():
            raise FileNotFoundError(f"Trace file not found: {trace_path}")

        sha256_hash = cls.compute_signature(p)
        
        if not run_id:
            run_id = p.parent.name if p.name == "run.jsonl" else p.stem

        now = datetime.now().astimezone()
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}" + now.strftime("%z")

        # 1. Forensic Evidence Ledger (Hashing sidecar artifacts)
        evidence_ledger = cls._compute_evidence_ledger(p.parent, exclude_files=[p.name])

        # 2. Build Manifest v3.0.0
        manifest = {
            "vc_version": "3.0.0",
            "harness_version": config.VERSION,
            "timestamp": timestamp,
            "run_id": run_id,
            "trace_file": p.name,
            "sha256": sha256_hash,
            "compliance": {
                "status": compliance_status,
                "score": compliance_score,
                "policy_ref": policy_ref or config.TRUSTED_POLICY_REF,
            },
            "evidence_ledger": evidence_ledger,
            "provenance_chain": [],
            "governance_ttl": (ttl_days or config.GOVERNANCE_TTL_DAYS),
            "metadata": metadata or {},
            "behavioral_fingerprint_id": behavioral_fingerprint_id or "default_v1",
        }

        # 3. Cryptographic Provenance
        try:
            private_key = IdentityService.get_private_key(identity_id)
            # Standard: Sign the manifest content (excluding transient fields like provenance_chain)
            manifest_to_sign = manifest.copy()
            manifest_to_sign.pop("provenance_chain", None)
            manifest_bytes = json.dumps(manifest_to_sign, sort_keys=True).encode("utf-8")
            signature = private_key.sign(manifest_bytes).hex()
            
            manifest["provenance_chain"].append({
                "identity": identity_id,
                "role": "Evaluator",
                "timestamp": timestamp,
                "signature": signature,
                "algorithm": "ED25519"
            })
        except Exception as e:
            logger.warning(f"Could not cryptographically sign trace as '{identity_id}': {e}")

        # 4. Save Sidecar Manifest
        sidecar_path = p.parent / f"{p.stem}_manifest.json"
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=4)

        # 5. Authoritative certificate backup
        try:
            cert_dir = config.REPORTS_DIR / "certificates"
            cert_dir.mkdir(parents=True, exist_ok=True)
            cert_path = cert_dir / f"{run_id}_vc.json"
            with open(cert_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=4)
        except Exception:
            pass

        return manifest

    @staticmethod
    def _compute_evidence_ledger(directory: Path, exclude_files: list[str]) -> dict[str, str]:
        """Hashes all relevant files in the run directory for forensic integrity."""
        ledger = {}
        for root, _, files in os.walk(directory):
            for file in files:
                if file in exclude_files or file.endswith("_manifest.json") or file.endswith("_vc.json"):
                    continue
                file_path = Path(root) / file
                rel_path = file_path.relative_to(directory).as_posix()
                try:
                    ledger[rel_path] = TraceVerifier.compute_signature(file_path)
                except Exception:
                    pass
        return ledger

    @classmethod
    def get_certificate(
        cls, trace_path: str, private_key_path: str | None = None
    ) -> dict[str, Any]:
        """
        Signs a trace and returns the certificate DICT directly (API Helper).
        """
        return cls.sign_trace(trace_path, private_key_path=private_key_path)

    @classmethod
    async def verify_trace_async(
        cls, trace_path: str, manifest_path: str, public_key_path: str | None = None, verify_ledger: bool = False
    ) -> bool:
        """
        Asynchronous version of verify_trace. Standard for v1.2+ Async-First architecture.
        """
        # For now, we wrap the sync call to maintain stability while transitioning.
        # Industrial improvement: Use aiofiles if high-concurrency verification is needed.
        return cls.verify_trace(trace_path, manifest_path, public_key_path, verify_ledger=verify_ledger)

    @classmethod
    def verify_trace(
        cls, trace_path: str, manifest_path: str, public_key_path: str | None = None, verify_ledger: bool = False
    ) -> bool:
        """
        Verifies a trace file against its manifest (VC). Supports v1, v2, and v3.
        """
        from .identity import IdentityService

        tp = Path(trace_path)
        mp = Path(manifest_path)

        if not utils.is_path_safe(tp, config.PROJECT_ROOT) or not utils.is_path_safe(mp, config.PROJECT_ROOT):
            logger.error("Security violation: Verification paths outside project jail.")
            return False

        if not tp.exists() or not mp.exists():
            return False

        try:
            with open(mp, encoding="utf-8") as f:
                manifest = json.load(f)

            vc_version = manifest.get("vc_version", "1.0.0")

            # 1. Base Integrity Check
            expected_hash = manifest.get("sha256")
            actual_hash = cls.compute_signature(tp)
            if expected_hash != actual_hash:
                logger.warning(f"Trace hash mismatch: expected {expected_hash}, got {actual_hash}")
                return False

            # 2. Forensic Evidence Ledger Check (v3+)
            if verify_ledger and vc_version >= "3.0.0":
                ledger = manifest.get("evidence_ledger", {})
                for rel_path, expected_file_hash in ledger.items():
                    file_path = tp.parent / rel_path
                    if not file_path.exists():
                        logger.warning(f"Forensic artifact missing: {rel_path}")
                        return False
                    if cls.compute_signature(file_path) != expected_file_hash:
                        logger.warning(f"Forensic artifact tampered: {rel_path}")
                        return False

            # 3. Governance TTL Check (v3+)
            if vc_version >= "3.0.0":
                ts_str = manifest.get("timestamp")
                ttl_days = manifest.get("governance_ttl", config.GOVERNANCE_TTL_DAYS)
                try:
                    # Parse timestamp (e.g. 2026-04-09T14:00:00.000+0530)
                    # We'll use a simplified check for duration
                    created_at = datetime.fromisoformat(ts_str)
                    age = datetime.now().astimezone() - created_at
                    if age.days > ttl_days:
                        logger.warning(f"Verification Certificate expired ({age.days} > {ttl_days} days)")
                        return False
                except Exception as e:
                    logger.warning(f"Failed to verify governance TTL: {e}")

            # 4. Cryptographic Proof
            if vc_version >= "3.0.0":
                chain = manifest.get("provenance_chain", [])
                if not chain:
                    logger.warning("No provenance chain found in v3 manifest.")
                    return False
                
                # Check the first signature in the chain (Evaluator)
                last_node = chain[0]
                identity_id = last_node.get("identity")
                sig_hex = last_node.get("signature")
                
                manifest_to_verify = manifest.copy()
                manifest_to_verify.pop("provenance_chain", None)
                manifest_bytes = json.dumps(manifest_to_verify, sort_keys=True).encode("utf-8")
                
                public_key = IdentityService.get_public_key(identity_id)
                public_key.verify(bytes.fromhex(sig_hex), manifest_bytes)
            else:
                # Legacy Verification (v1/v2)
                sig_hex = manifest.get("signature_ed25519")
                if sig_hex:
                    manifest_to_verify = manifest.copy()
                    manifest_to_verify.pop("signature_ed25519", None)
                    manifest_bytes = json.dumps(manifest_to_verify, sort_keys=True).encode("utf-8")
                    
                    # For legacy, we might still need the public_key_path if not using IdentityService
                    if public_key_path:
                        from cryptography.hazmat.primitives import serialization
                        with open(public_key_path, "rb") as f:
                            public_key = serialization.load_pem_public_key(f.read())
                        public_key.verify(bytes.fromhex(sig_hex), manifest_bytes)
                    else:
                        # Attempt identity resolution for legacy if possible
                        try:
                            public_key = IdentityService.get_public_key("system_id")
                            public_key.verify(bytes.fromhex(sig_hex), manifest_bytes)
                        except Exception:
                            logger.warning("Legacy signature present but public key not provided.")

            return True
        except Exception:
            import traceback

            logger.error(f"Verification Failure:\n{traceback.format_exc()}")
            return False

    @staticmethod
    def verify_asymmetric(data: bytes, signature_hex: str, public_key_path: str) -> bool:
        """
        Industrial-grade asymmetric verification helper.
        Supports ED25519 signature verification using a PEM public key.
        """
        from cryptography.hazmat.primitives import serialization

        try:
            with open(public_key_path, "rb") as f:
                public_key = serialization.load_pem_public_key(f.read())
            public_key.verify(bytes.fromhex(signature_hex), data)
            return True
        except Exception:
            return False

    # --- Internal Helpers ---

    @staticmethod
    def _get_os_walk_files(directory: Path):
        import os
        return os.walk(directory)


import os  # To ensure os.walk works in the class
