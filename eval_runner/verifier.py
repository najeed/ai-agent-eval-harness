import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from . import config

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

class TraceVerifier:
    """Handles SHA-256 signing and verification of run traces for public reproducibility."""

    @staticmethod
    def compute_signature(trace_path: Path) -> str:
        """Computes the SHA-256 hash of a trace file."""
        sha256 = hashlib.sha256()
        with open(trace_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def sign_trace(trace_path: str, metadata: Optional[Dict[str, Any]] = None, private_key_path: Optional[str] = None) -> Path:
        """
        Signs a trace file. If private_key_path is provided, generates an ED25519 signature.
        Otherwise, generates a standard SHA-256 manifest.
        """
        p = Path(trace_path)
        if not p.exists():
            raise FileNotFoundError(f"Trace file not found: {trace_path}")

        signature = TraceVerifier.compute_signature(p)
        
        manifest = {
            "harness_version": "1.2.0-opencore",
            "timestamp": datetime.now().isoformat(),
            "trace_file": p.name,
            "sha256": signature,
            "metadata": metadata or {}
        }

        # R1.2 Remediation: Add Asymmetric Signature if key is provided
        if private_key_path:
            # We sign the SHA-256 hash of the trace for efficiency
            manifest["signature_ed25519"] = TraceVerifier.sign_asymmetric(signature.encode(), private_key_path)
            manifest["signing_algorithm"] = "ED25519"

        # Save manifest in the same directory as the trace
        manifest_path = p.parent / f"{p.stem}_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        
        return manifest_path

    @staticmethod
    def verify_trace(trace_path: str, manifest_path: str, public_key_path: Optional[str] = None) -> bool:
        """
        Verifies a trace file against its manifest. Supports both SHA-256 and ED25519.
        """
        tp = Path(trace_path)
        mp = Path(manifest_path)

        if not tp.exists() or not mp.exists():
            return False

        try:
            with open(mp, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            expected_hash = manifest.get("sha256")
            actual_hash = TraceVerifier.compute_signature(tp)
            
            # 1. Base Integrity Check
            if expected_hash != actual_hash:
                return False
            
            # 2. Cryptographic Proof (R1.2)
            sig_hex = manifest.get("signature_ed25519")
            if sig_hex and public_key_path:
                return TraceVerifier.verify_asymmetric(actual_hash.encode(), sig_hex, public_key_path)
            elif sig_hex and not public_key_path:
                # If signed but no key provided, we mark as "Integrity Only" but technically valid
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

        d = Path(output_dir)
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

    @staticmethod
    def sign_asymmetric(data_bytes: bytes, private_key_path: str) -> str:
        """Signs bytes using an ED25519 private key and returns hex signature."""
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives import serialization

        with open(private_key_path, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        
        signature = private_key.sign(data_bytes)
        return signature.hex()

    @staticmethod
    def verify_asymmetric(data_bytes: bytes, hex_signature: str, public_key_path: str) -> bool:
        """Verifies a hex signature against data using an ED25519 public key."""
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives import serialization

        with open(public_key_path, "rb") as f:
            public_key = serialization.load_pem_public_key(f.read())
        
        try:
            public_key.verify(bytes.fromhex(hex_signature), data_bytes)
            return True
        except Exception:
            return False
