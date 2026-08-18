"""
eval_runner.reference.signing
OSS Reference Implementations: LocalEd25519SigningBackend, NullSigningBackend, and PQCSigningBackend
"""

from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from eval_runner.interfaces.signing import SigningBackend


class LocalEd25519SigningBackend(SigningBackend):
    """
    Local filesystem Ed25519 cryptographic signing backend.
    Signs raw payloads using an Ed25519 PEM private key and verifies signatures
    against an Ed25519 PEM public key.
    """

    def sign_payload(
        self, payload: bytes, key_identifier: str | Path | bytes, **kwargs: Any
    ) -> str:
        """
        Signs raw payload using an Ed25519 private key located at key_identifier
        (file path or PEM bytes/str).
        Returns a hex-encoded signature string.
        """
        if isinstance(key_identifier, (str, Path)):
            p = Path(key_identifier)
            if p.exists() and p.is_file():
                with open(p, "rb") as f:
                    key_bytes = f.read()
            elif isinstance(key_identifier, str) and "-----BEGIN" in key_identifier:
                key_bytes = key_identifier.encode("utf-8")
            else:
                raise FileNotFoundError(f"Signing key not found at {key_identifier}")
        elif isinstance(key_identifier, bytes):
            key_bytes = key_identifier
        else:
            raise TypeError("Expected file path, PEM string, or bytes for key_identifier")

        private_key = serialization.load_pem_private_key(key_bytes, password=None)
        if not isinstance(private_key, ed25519.Ed25519PrivateKey):
            raise TypeError("Expected Ed25519PrivateKey in PEM file")

        sig_bytes = private_key.sign(payload)
        return sig_bytes.hex()

    def verify_signature(
        self,
        payload: bytes,
        signature: str,
        public_key_identifier: str | Path | bytes,
        **kwargs: Any,
    ) -> bool:
        """
        Verifies signature against public_key_identifier (file path or PEM bytes/str).
        """
        if isinstance(public_key_identifier, (str, Path)):
            try:
                p = Path(public_key_identifier)
                if p.exists() and p.is_file():
                    with open(p, "rb") as f:
                        pub_bytes = f.read()
                elif isinstance(public_key_identifier, str):
                    pub_bytes = public_key_identifier.encode("utf-8")
                else:
                    pub_bytes = bytes(public_key_identifier)
            except (OSError, ValueError):
                pub_bytes = (
                    public_key_identifier.encode("utf-8")
                    if isinstance(public_key_identifier, str)
                    else bytes(public_key_identifier)
                )
        elif isinstance(public_key_identifier, bytes):
            pub_bytes = public_key_identifier
        else:
            pub_bytes = bytes(public_key_identifier)

        try:
            public_key = serialization.load_pem_public_key(pub_bytes)
            if not isinstance(public_key, ed25519.Ed25519PublicKey):
                return False
            sig_bytes = bytes.fromhex(signature)
            public_key.verify(sig_bytes, payload)
            return True
        except (InvalidSignature, ValueError, TypeError, Exception):
            return False


class NullSigningBackend(SigningBackend):
    """
    Null signing backend for environments where cryptographic signing is disabled.
    Never signs and always returns false for verification.
    """

    def sign_payload(self, payload: bytes, key_identifier: str | Path, **kwargs: Any) -> str:
        return ""

    def verify_signature(
        self, payload: bytes, signature: str, public_key_identifier: str | Path, **kwargs: Any
    ) -> bool:
        return False


class PQCSigningBackend(SigningBackend):
    """
    Post-Quantum Cryptography (PQC) signing backend using ML-DSA-65 (FIPS 204)
    via IdentityService and Zero-Exposure Signing (ZES).
    """

    def sign_payload(
        self, payload: bytes, key_identifier: str | Path | None = None, **kwargs: Any
    ) -> str:
        from eval_runner import config, forensics
        from eval_runner.identity import IdentityService

        pqc_client = IdentityService.get_pqc_client()
        if not pqc_client:
            raise RuntimeError("PQC client is not available or PQC_ENABLED is False")

        shake_digest = forensics.compute_shake256_digest(payload)
        identity_id = str(key_identifier) if key_identifier else config.PQC_IDENTITY_ID
        return pqc_client.sign_digest(digest=shake_digest, identity_id=identity_id)

    def verify_signature(
        self,
        payload: bytes,
        signature: str,
        public_key_identifier: str | Path | None = None,
        **kwargs: Any,
    ) -> bool:
        from eval_runner import config, forensics
        from eval_runner.identity import IdentityService

        pqc_client = IdentityService.get_pqc_client()
        if not pqc_client:
            if config.PQC_STRICT_MODE:
                raise ValueError("PQC_STRICT_MODE Violation: PQC client not available")
            return False

        shake_digest = forensics.compute_shake256_digest(payload)
        identity_id = (
            str(public_key_identifier) if public_key_identifier else config.PQC_IDENTITY_ID
        )
        return bool(
            pqc_client.verify_digest(
                signature=signature, digest=shake_digest, identity_id=identity_id
            )
        )
