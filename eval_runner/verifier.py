import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from . import config

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
    def sign_trace(trace_path: str, metadata: Optional[Dict[str, Any]] = None) -> Path:
        """
        Signs a trace file by generating a manifest.json with its SHA-256 signature.
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

        # Save manifest in the same directory as the trace
        manifest_path = p.parent / f"{p.stem}_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        
        return manifest_path

    @staticmethod
    def verify_trace(trace_path: str, manifest_path: str) -> bool:
        """
        Verifies a trace file against its manifest signature.
        """
        tp = Path(trace_path)
        mp = Path(manifest_path)

        if not tp.exists() or not mp.exists():
            return False

        try:
            with open(mp, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            expected_sig = manifest.get("sha256")
            actual_sig = TraceVerifier.compute_signature(tp)
            
            return expected_sig == actual_sig
        except Exception:
            return False
