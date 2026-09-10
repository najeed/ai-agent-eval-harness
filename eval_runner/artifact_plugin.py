"""
eval_runner/artifact_plugin.py

Core Compliance Layer: Artifact & Regulatory Guardrails.
Provides first-class support for Source of Truth bundling and integrity verification.
"""

import base64
import json
import logging
import os
import zipfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from agentv_runtime.canonical import canonical_json_encode

from . import config
from .plugins import BaseEvalPlugin
from .utils import crypto

logger = logging.getLogger(__name__)


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
        """Retrieves the authoritative private key for signing.

        Zero-Trust Hardening: Auto-generation of local unanchored signing keys
        is strictly forbidden to prevent self-attestation vulnerability.
        """
        # Priority 1: Environment variable
        env_key = os.getenv("AES_PRIVATE_KEY")
        if env_key:
            try:
                return serialization.load_pem_private_key(env_key.encode(), password=None)
            except Exception as e:
                print(f"      [ArtifactPlugin] Warning: Failed to load key from environment: {e}")
                err_msg = (
                    "CryptographicSigningError: Failed to load signing key "
                    f"from AES_PRIVATE_KEY: {e}"
                )
                raise RuntimeError(err_msg) from e

        # Priority 2: IdentityService authoritative identity
        try:
            from eval_runner.identity import IdentityService

            priv = IdentityService.get_private_key("system_id", auto_provision=False)
            if priv:
                return priv
        except (ImportError, AttributeError, ValueError, OSError) as exc:
            logger.debug("IdentityService private key resolution failed: %s", exc)

        # Priority 3: Persistent file
        key_dir = config.PROJECT_ROOT / ".aes" / "keys"
        key_path = key_dir / "system_id.pem"
        if key_path.exists():
            with open(key_path, "rb") as f:
                return serialization.load_pem_private_key(f.read(), password=None)

        # Priority 4: Prohibit auto-generation
        raise RuntimeError(
            "CryptographicSigningError: No signing key configured for artifact bundling. "
            "Self-generated unanchored signing keys are prohibited."
        )

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
            manifest["signer_identity"] = getattr(self, "signer_identity", "system_id")
            manifest["algorithm"] = "ed25519"

            # Sign exact canonical RFC 8785 bytes
            canonical_bytes = canonical_json_encode(manifest)
            priv_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            backend = LocalEd25519SigningBackend()
            sig_hex = backend.sign_payload(canonical_bytes, priv_pem)
            signature = bytes.fromhex(sig_hex)
            manifest["signature_ed25519"] = base64.b64encode(signature).decode()
            manifest["public_key"] = base64.b64encode(
                private_key.public_key().public_bytes(
                    encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
                )
            ).decode()

            manifest_path = base_path / "audit_manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
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

    def verify_integrity(
        self,
        manifest_path: str,
        trust_root: Any | None = None,
        key_registry: Mapping[str, Any] | None = None,
        public_key_pem: str | bytes | None = None,
        trusted_public_key: Any | None = None,
    ) -> dict[str, Any]:
        """
        Verifies all files listed in a manifest against their SHA3-256 hashes and
        verifies the detached signature against an externally anchored trust root.

        For ZIP bundles:
          - Directly inspects and hashes the files packed INSIDE the archive.
          - Rejects absolute paths, parent directory traversal (..), and unsafe paths.
        For standalone manifest files:
          - Hashes adjacent filesystem files after rejecting unsafe paths.

        Trust Anchor Invariant:
          - Publication verification requires an externally configured trust root/key registry.
          - Missing external trust anchor results in status="UNVERIFIED", is_valid=False.
          - Embedded public keys are informational only and must match the external anchor.
        """
        path = Path(manifest_path)
        if not path.exists():
            return {"status": "error", "message": "Manifest not found", "is_valid": False}

        is_zip = zipfile.is_zipfile(path)
        results: list[dict[str, str]] = []
        is_valid = True

        if is_zip:
            with zipfile.ZipFile(path, "r") as zf:
                if "audit_manifest.json" not in zf.namelist():
                    return {
                        "status": "error",
                        "message": "No audit_manifest.json in bundle",
                        "is_valid": False,
                    }
                manifest_raw = zf.read("audit_manifest.json").decode("utf-8")
                manifest = json.loads(manifest_raw)

                for entry in manifest.get("files", []):
                    entry_name = entry.get("name", "")
                    if (
                        not entry_name
                        or os.path.isabs(entry_name)
                        or ".." in Path(entry_name).parts
                        or entry_name.startswith("/")
                        or entry_name.startswith("\\")
                        or ":" in entry_name
                    ):
                        results.append({"file": entry_name, "status": "unsafe_path"})
                        is_valid = False
                        continue

                    if entry_name not in zf.namelist():
                        results.append({"file": entry_name, "status": "missing"})
                        is_valid = False
                        continue

                    entry_bytes = zf.read(entry_name)
                    actual_hash = crypto.content_hash(entry_bytes)
                    expected_hash = entry.get("file_hash")
                    if actual_hash == expected_hash:
                        results.append({"file": entry_name, "status": "valid"})
                    else:
                        results.append({"file": entry_name, "status": "mismatch"})
                        is_valid = False
        else:
            with open(path, encoding="utf-8") as f:
                manifest = json.load(f)

            for entry in manifest.get("files", []):
                entry_name = entry.get("name", "")
                if (
                    not entry_name
                    or os.path.isabs(entry_name)
                    or ".." in Path(entry_name).parts
                    or entry_name.startswith("/")
                    or entry_name.startswith("\\")
                    or ":" in entry_name
                ):
                    results.append({"file": entry_name, "status": "unsafe_path"})
                    is_valid = False
                    continue

                f_path = path.parent / entry_name
                if not f_path.exists():
                    results.append({"file": entry_name, "status": "missing"})
                    is_valid = False
                    continue

                actual_hash = self._calculate_hash(f_path)
                expected_hash = entry.get("file_hash")
                if actual_hash == expected_hash:
                    results.append({"file": entry_name, "status": "valid"})
                else:
                    results.append({"file": entry_name, "status": "mismatch"})
                    is_valid = False

        if not is_valid:
            return {
                "is_valid": False,
                "status": "INVALID",
                "details": results,
                "manifest": manifest,
            }

        has_sig = "signature_ed25519" in manifest
        if not has_sig:
            return {
                "is_valid": False,
                "status": "UNVERIFIED",
                "message": "Manifest has no cryptographic signature",
                "details": results,
                "manifest": manifest,
            }

        # Resolve authoritative external trust anchor
        anchored_key: ed25519.Ed25519PublicKey | None = None
        signer_id = manifest.get("signer_identity") or manifest.get("key_id") or "system_id"

        if trusted_public_key is not None:
            if isinstance(trusted_public_key, ed25519.Ed25519PublicKey):
                anchored_key = trusted_public_key
            elif isinstance(trusted_public_key, (str, bytes)):
                anchored_key = serialization.load_pem_public_key(
                    trusted_public_key
                    if isinstance(trusted_public_key, bytes)
                    else trusted_public_key.encode("utf-8")
                )
        elif public_key_pem is not None:
            pem_bytes = (
                public_key_pem
                if isinstance(public_key_pem, bytes)
                else public_key_pem.encode("utf-8")
            )
            anchored_key = serialization.load_pem_public_key(pem_bytes)
        elif key_registry is not None:
            key_val = (
                key_registry.get(signer_id)
                or (key_registry.get(manifest.get("key_id")) if manifest.get("key_id") else None)
                or key_registry.get("system_id")
            )
            if key_val is not None:
                if isinstance(key_val, ed25519.Ed25519PublicKey):
                    anchored_key = key_val
                elif isinstance(key_val, (str, bytes)):
                    anchored_key = serialization.load_pem_public_key(
                        key_val if isinstance(key_val, bytes) else key_val.encode("utf-8")
                    )
        elif trust_root is not None:
            if hasattr(trust_root, "get_public_key"):
                pk = trust_root.get_public_key(signer_id)
                if pk:
                    anchored_key = (
                        pk
                        if isinstance(pk, ed25519.Ed25519PublicKey)
                        else serialization.load_pem_public_key(
                            pk if isinstance(pk, bytes) else pk.encode("utf-8")
                        )
                    )
            elif isinstance(trust_root, (str, Path)):
                root_path = Path(trust_root)
                candidate = root_path / signer_id / "public_key.pem"
                if not candidate.is_file():
                    candidate = root_path / f"{signer_id}_public.pem"
                if candidate.is_file():
                    anchored_key = serialization.load_pem_public_key(candidate.read_bytes())
        else:
            try:
                from eval_runner.identity import IdentityService

                pk = IdentityService.get_public_key(signer_id, auto_provision=False)
                if pk:
                    anchored_key = pk
            except (ImportError, AttributeError, ValueError, OSError) as exc:
                logger.debug("IdentityService key resolution failed for %s: %s", signer_id, exc)
                anchored_key = None

            if not anchored_key:
                for candidate_path in [
                    config.TRUST_ROOT / f"{signer_id}_public.pem",
                    config.PROJECT_ROOT / ".aes" / "keys" / f"{signer_id}_public.pem",
                    config.PROJECT_ROOT / ".aes" / "keys" / signer_id / "public_key.pem",
                ]:
                    if candidate_path.is_file():
                        try:
                            anchored_key = serialization.load_pem_public_key(
                                candidate_path.read_bytes()
                            )
                            break
                        except (ValueError, TypeError, OSError) as exc:
                            logger.debug(
                                "Failed to load candidate trust root key %s: %s",
                                candidate_path,
                                exc,
                            )

        if not anchored_key:
            return {
                "is_valid": False,
                "status": "UNVERIFIED",
                "message": (
                    f"No external trust anchor found for signer '{signer_id}'. "
                    "Self-attestation is forbidden."
                ),
                "details": results,
                "manifest": manifest,
            }

        if "public_key" in manifest:
            try:
                embedded_raw = base64.b64decode(manifest["public_key"])
                anchored_raw = anchored_key.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
                if embedded_raw != anchored_raw:
                    msg = "Embedded public key does not match authoritative external trust anchor."
                    return {
                        "is_valid": False,
                        "status": "UNVERIFIED",
                        "message": msg,
                        "details": results,
                        "manifest": manifest,
                    }
            except Exception as e:
                return {
                    "is_valid": False,
                    "status": "UNVERIFIED",
                    "message": f"Malformed embedded public key: {e}",
                    "details": results,
                    "manifest": manifest,
                }

        # Verify signature using canonical RFC 8785 representation
        try:
            sig_bytes = base64.b64decode(manifest["signature_ed25519"])
            verify_manifest = {
                k: v for k, v in manifest.items() if k not in ["signature_ed25519", "public_key"]
            }
            canonical_bytes = canonical_json_encode(verify_manifest)
            anchored_key.verify(sig_bytes, canonical_bytes)
            return {
                "is_valid": True,
                "status": "VALID",
                "details": results,
                "manifest": manifest,
                "signer_identity": signer_id,
            }
        except Exception as e:
            return {
                "is_valid": False,
                "status": "INVALID_SIGNATURE",
                "message": f"Signature verification failure: {e}",
                "details": results,
                "manifest": manifest,
            }
