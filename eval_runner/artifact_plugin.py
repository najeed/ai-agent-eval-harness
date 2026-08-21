"""
eval_runner/artifact_plugin.py

Core Compliance Layer: Artifact & Regulatory Guardrails.
Provides first-class support for Source of Truth bundling and integrity verification.
"""

import base64
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from . import config
from .plugins import BaseEvalPlugin
from .utils import crypto


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

    def _get_signing_key(self) -> ed25519.Ed25519PrivateKey:
        """Retrieves or generates the system private key for signing."""
        key_dir = config.PROJECT_ROOT / ".aes" / "keys"
        key_path = key_dir / "system_id.pem"

        # Priority 1: Environment variable
        env_key = os.getenv("AES_PRIVATE_KEY")
        if env_key:
            try:
                return serialization.load_pem_private_key(env_key.encode(), password=None)
            except Exception as e:
                # Forensic Audit: Key format errors must be signaled
                print(f"      [ArtifactPlugin] Warning: Failed to load key from environment: {e}")

        # Priority 2: Persistent file
        if key_path.exists():
            with open(key_path, "rb") as f:
                return serialization.load_pem_private_key(f.read(), password=None)

        # Priority 3: Auto-generate
        print("      [ArtifactPlugin] Generating new Ed25519 system identity...")
        private_key = ed25519.Ed25519PrivateKey.generate()
        key_dir.mkdir(parents=True, exist_ok=True)
        with open(key_path, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
        return private_key

    def _calculate_hash(self, file_path: Path) -> str:
        return crypto.file_hash(file_path)

    def bundle_artifacts(
        self,
        target_dir: str,
        files_to_include: list[str],
        output_filename: str = "publication_artifact_bundle.zip",
        generate_manifest: bool = True,
    ) -> dict[str, Any]:
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
            f"      [ArtifactPlugin] Bundling {len(files_to_include)} files in {base_path.name}..."
        )

        with zipfile.ZipFile(zip_path, "w") as zipf:
            for filename in files_to_include:
                f_path = base_path / filename
                if f_path.exists():
                    zipf.write(f_path, arcname=filename)
                    if generate_manifest:
                        manifest["files"].append(
                            {"name": filename, "file_hash": self._calculate_hash(f_path)}
                        )
                else:
                    print(f"⚠️ [ArtifactPlugin] Skipping missing file: {filename}")

        if generate_manifest:
            # Add signature to manifest
            from eval_runner.reference.signing import LocalEd25519SigningBackend

            private_key = self._get_signing_key()
            manifest_json = json.dumps(manifest, sort_keys=True)
            priv_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            backend = LocalEd25519SigningBackend()
            sig_hex = backend.sign_payload(manifest_json.encode(), priv_pem)
            signature = bytes.fromhex(sig_hex)
            manifest["signature_ed25519"] = base64.b64encode(signature).decode()
            manifest["public_key"] = base64.b64encode(
                private_key.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
                )
            ).decode()

            manifest_path = base_path / "audit_manifest.json"
            with open(manifest_path, "w") as f:
                json.dump(manifest, f, indent=2)

            # Append the signed manifest to the compiled ZIP bundle archive
            with zipfile.ZipFile(zip_path, "a") as zipf:
                zipf.write(manifest_path, arcname="audit_manifest.json")

            print(f"      [ArtifactPlugin] Signed manifest created and embedded: {manifest_path}")

        bundle_hash = self._calculate_hash(zip_path)
        print(f"      [ArtifactPlugin] Bundle created: {zip_path} (Hash: {bundle_hash[:16]}...)")
        return {
            "bundle_path": str(zip_path),
            "bundle_hash": bundle_hash,
            "manifest_path": (
                str(base_path / "audit_manifest.json") if generate_manifest else None
            ),
            "status": "success",
        }

    def verify_integrity(self, manifest_path: str) -> dict[str, Any]:
        """
        Verifies all files listed in a manifest against their SHA3-256 hashes.
        """
        path = Path(manifest_path)
        if not path.exists():
            return {"status": "error", "message": "Manifest not found"}

        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as zf:
                if "audit_manifest.json" not in zf.namelist():
                    return {"status": "error", "message": "No audit_manifest.json in bundle"}
                with zf.open("audit_manifest.json") as f:
                    manifest = json.loads(f.read().decode("utf-8"))
        else:
            with open(path, encoding="utf-8") as f:
                manifest = json.load(f)

        results = []
        is_valid = True

        for entry in manifest.get("files", []):
            f_path = path.parent / entry["name"]
            if not f_path.exists():
                results.append({"file": entry["name"], "status": "missing"})
                is_valid = False
                continue

            actual_hash = self._calculate_hash(f_path)
            expected_hash = entry.get("file_hash")
            if actual_hash == expected_hash:
                results.append({"file": entry["name"], "status": "valid"})
            else:
                results.append({"file": entry["name"], "status": "mismatch"})
                is_valid = False

        # Verify Signature if present
        if is_valid and "signature_ed25519" in manifest and "public_key" in manifest:
            try:
                # [Industrial Hardening] Verify the Ed25519 signature
                pub_key_bytes = base64.b64decode(manifest["public_key"])
                sig_bytes = base64.b64decode(manifest["signature_ed25519"])

                # Reconstruct signing data (manifest without signature/public_key)
                verify_manifest = {
                    k: v
                    for k, v in manifest.items()
                    if k not in ["signature_ed25519", "public_key"]
                }
                manifest_json = json.dumps(verify_manifest, sort_keys=True)

                from cryptography.hazmat.primitives.asymmetric import ed25519

                public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_key_bytes)
                public_key.verify(sig_bytes, manifest_json.encode())

                print("      [ArtifactPlugin] Signature verification successful.")
            except Exception as e:
                print(f"      [ArtifactPlugin] Signature verification failure: {e}")
                is_valid = False

        return {"is_valid": is_valid, "details": results}
