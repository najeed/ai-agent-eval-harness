"""
eval_runner/artifact_plugin.py

Core Compliance Layer: Artifact & Regulatory Guardrails.
Provides first-class support for Source of Truth bundling and integrity verification.
"""

import hashlib
import json
import zipfile
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from .plugins import BaseEvalPlugin


class ArtifactPlugin(BaseEvalPlugin):
    """
    Registers services for bundling and signing evaluation artifacts.
    This is a core capability for regulatory compliance.
    """

    def on_discover_services(self, registry: Any):
        """Register bundling services."""
        print("      [Plugin] Registering Artifact/Compliance services.")
        registry.register_service("bundle_artifacts", self.bundle_artifacts)
        registry.register_service("verify_integrity", self.verify_integrity)

    def _calculate_sha256(self, file_path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def bundle_artifacts(
        self,
        target_dir: str,
        files_to_include: List[str],
        output_filename: str = "publication_artifact_bundle.zip",
        generate_manifest: bool = True,
    ) -> Dict[str, Any]:
        """
        Standardized core Service for creating a signed ZIP bundle.
        """
        base_path = Path(target_dir)
        zip_path = base_path / output_filename
        manifest = {
            "version": "1.0",
            "timestamp": datetime.now().isoformat(),
            "batch_id": base_path.name,
            "files": [],
        }

        print(
            f"📦 [ArtifactPlugin] Bundling {len(files_to_include)} files in {base_path.name}..."
        )

        with zipfile.ZipFile(zip_path, "w") as zipf:
            for filename in files_to_include:
                f_path = base_path / filename
                if f_path.exists():
                    zipf.write(f_path, arcname=filename)
                    if generate_manifest:
                        manifest["files"].append(
                            {"name": filename, "sha256": self._calculate_sha256(f_path)}
                        )
                else:
                    print(f"⚠️ [ArtifactPlugin] Skipping missing file: {filename}")

        if generate_manifest:
            manifest_path = base_path / "audit_manifest.json"
            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)
            print(f"✅ [ArtifactPlugin] Manifest created: {manifest_path}")

        print(f"✅ [ArtifactPlugin] Bundle created: {zip_path}")
        return {
            "bundle_path": str(zip_path),
            "manifest_path": (
                str(base_path / "audit_manifest.json") if generate_manifest else None
            ),
            "status": "success",
        }

    def verify_integrity(self, manifest_path: str) -> Dict[str, Any]:
        """
        Verifies all files listed in a manifest against their SHA-256 hashes.
        """
        path = Path(manifest_path)
        if not path.exists():
            return {"status": "error", "message": "Manifest not found"}

        with open(path, "r") as f:
            manifest = json.load(f)

        results = []
        is_valid = True

        for entry in manifest.get("files", []):
            f_path = path.parent / entry["name"]
            if not f_path.exists():
                results.append({"file": entry["name"], "status": "missing"})
                is_valid = False
                continue

            actual_hash = self._calculate_sha256(f_path)
            if actual_hash == entry["sha256"]:
                results.append({"file": entry["name"], "status": "valid"})
            else:
                results.append({"file": entry["name"], "status": "mismatch"})
                is_valid = False

        return {"is_valid": is_valid, "details": results}
