import json
import hashlib
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from . import config

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
            "criticality": "low|medium|high"
        }
    ],
    "topology_p95": "float"
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
        "resilience": 0.05
    }

    def __init__(
        self, 
        success: bool, 
        message: str, 
        metrics: Optional[Dict[str, float]] = None, 
        metadata: Optional[Dict[str, Any]] = None,
        aggregate_score: Optional[float] = None
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
            "resilience": 0.0
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "aggregate_score": self.aggregate_score,
            "success": self.success,
            "message": self.message,
            "metrics": self.metrics,
            "metadata": self.metadata,
            "timestamp": datetime.now().astimezone().isoformat()
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

class KeyLoader(ABC):
    """Abstract base class for loading cryptographic keys (HMS-Readiness)."""
    @abstractmethod
    def load_private_key(self, path: str):
        pass

    @abstractmethod
    def load_public_key(self, path: str):
        pass

class LocalFileKeyLoader(KeyLoader):
    """Default implementation for loading keys from local PEM files."""
    def load_private_key(self, path: str):
        from cryptography.hazmat.primitives import serialization
        with open(path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    def load_public_key(self, path: str):
        from cryptography.hazmat.primitives import serialization
        with open(path, "rb") as f:
            return serialization.load_pem_public_key(f.read())

class TraceVerifier:
    """
    Electronic Verification and Certification Engine for evaluation traces.
    Implements the industrial Trust Protocol (SHA-256 + ED25519).
    """
    _key_loader: KeyLoader = LocalFileKeyLoader()

    @classmethod
    def set_key_loader(cls, loader: KeyLoader):
        """Allows overriding the default key loader (e.g., for KMS/HSM)."""
        cls._key_loader = loader

    @staticmethod
    def compute_signature(trace_path: Path) -> str:
        """Computes the SHA-256 hash of a trace file."""
        sha256 = hashlib.sha256()
        with open(trace_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()

    @classmethod
    def sign_trace(cls, trace_path: str, metadata: Optional[Dict[str, Any]] = None, private_key_path: Optional[str] = None, fingerprint_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Signs a trace file and issues a standardized Verification Certificate (VC).
        Returns the Manifest DICT (Authoritative Proof).
        """
        p = Path(trace_path)
        if not p.exists():
            raise FileNotFoundError(f"Trace file not found: {trace_path}")

        # 1. Compute Integrity Hash (SHA-256)
        sha256_hash = cls.compute_signature(p)
        run_id = p.stem

        # 2. Build the Manifest (Standardized v1.2.3)
        manifest = {
            "harness_version": "1.2.3",
            "version": "1.2.3",  # Aliased for modern consumers
            "timestamp": datetime.now().astimezone().isoformat(),
            "run_id": run_id,
            "trace_file": p.name,
            "sha256": sha256_hash,
            "metadata": metadata or {},
            "fingerprint_id": fingerprint_id or "default_v1",
            "signing_algorithm": "ED25519"
        }

        if fingerprint_id:
            manifest["behavioral_fingerprint_id"] = fingerprint_id

        # 3. Add Asymmetric Authority (ED25519) if key available
        if private_key_path:
            try:
                # We sign the entire manifest structure (sorted)
                manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")
                signature_hex = cls.sign_asymmetric(manifest_bytes, private_key_path)
                manifest["signature_ed25519"] = signature_hex
            except Exception as e:
                logger.warning(f"Could not cryptographically sign trace: {e}")

        # 4. Save Sidecar Manifest (Standard Reproducibility)
        sidecar_path = p.parent / f"{p.stem}_manifest.json"
        try:
            with open(sidecar_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save sidecar manifest: {e}")

        # 5. Authoritative certificate backup (for Public API)
        try:
            cert_dir = config.REPORTS_DIR / "certificates"
            cert_dir.mkdir(parents=True, exist_ok=True)
            cert_path = cert_dir / f"{run_id}_vc.json"
            with open(cert_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=4)
        except Exception:
             # Silently skip if authoritative storage is unavailable (common in lean tests)
             pass

        return manifest

    @classmethod
    def get_certificate(cls, trace_path: str, private_key_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Signs a trace and returns the certificate DICT directly (API Helper).
        """
        return cls.sign_trace(trace_path, private_key_path=private_key_path)

    @classmethod
    def verify_trace(cls, trace_path: str, manifest_path: str, public_key_path: Optional[str] = None) -> bool:
        """
        Verifies a trace file against its manifest (VC). Supports both SHA-256 and ED25519.
        """
        tp = Path(trace_path)
        mp = Path(manifest_path)

        if not tp.exists() or not mp.exists():
            return False

        try:
            with open(mp, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            # Extract basic integrity details
            expected_hash = manifest.get("sha256")
            actual_hash = cls.compute_signature(tp)
            
            # 1. Base Integrity Check
            if expected_hash != actual_hash:
                return False
            
            # 2. Cryptographic Proof (R1.2)
            sig_hex = manifest.get("signature_ed25519")
            if sig_hex and public_key_path:
                manifest_to_verify = manifest.copy()
                manifest_to_verify.pop("signature_ed25519", None)
                
                manifest_bytes = json.dumps(manifest_to_verify, sort_keys=True).encode("utf-8")
                if not cls.verify_asymmetric(manifest_bytes, sig_hex, public_key_path):
                    return False
            elif sig_hex and not public_key_path:
                # If signed but no key provided, integrity only is valid but signature remains unverified
                return True
                
            return True
        except Exception:
            return False

    # --- ASYMMETRIC Trust Protocol (ED25519) ---

    @staticmethod
    def generate_key_pair(output_dir: str = ".aes/keys"):
        """Generates a new ED25519 key pair for signing."""
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives import serialization

        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        out_path = Path(output_dir)
        if out_path.is_absolute():
            d = out_path
        else:
            d = (config.PROJECT_ROOT / output_dir).resolve()
            
        d.mkdir(parents=True, exist_ok=True)

        # Save Private Key (Keep Secret!)
        priv_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        with open(d / "private_key.pem", "wb") as f:
            f.write(priv_bytes)

        # Save Public Key (For Verification)
        pub_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        with open(d / "public_key.pem", "wb") as f:
            f.write(pub_bytes)
        
        return d

    @classmethod
    def sign_asymmetric(cls, data_bytes: bytes, private_key_path: str) -> str:
        """Signs bytes using an ED25519 private key via the pluggable _key_loader."""
        private_key = cls._key_loader.load_private_key(private_key_path)
        signature = private_key.sign(data_bytes)
        return signature.hex()

    @classmethod
    def verify_asymmetric(cls, data_bytes: bytes, hex_signature: str, public_key_path: str) -> bool:
        """Verifies a hex signature against data using an ED25519 public key."""
        try:
            public_key = cls._key_loader.load_public_key(public_key_path)
            public_key.verify(bytes.fromhex(hex_signature), data_bytes)
            return True
        except Exception:
            return False
