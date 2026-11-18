"""Use the configured signer for the existing raw Ed25519 observation receipts."""

import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def sign_observation(payload, backend, identity):
    """Sign through the selected backend, without key generation or provider fallback."""
    if not backend.can_sign():
        raise RuntimeError("Configured observation signer is unavailable")
    key_reference = identity
    if getattr(backend, "requires_private_key_material", False):
        path = os.getenv("FLIGHT_RECORDER_KEY_PATH") if identity == "system_id" else None
        pem = (
            os.getenv("CORE_ARTIFACT_SIGNING_PEM") if identity == "system_id" else None
        ) or os.getenv(f"CORE_ARTIFACT_SIGNING_PEM_{identity.upper()}")
        if path:
            private_key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        elif pem:
            private_key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
        else:
            from eval_runner.identity import IdentityService

            private_key = IdentityService.get_private_key(identity, auto_provision=False)
        if not isinstance(private_key, ed25519.Ed25519PrivateKey):
            raise ValueError("Configured observation identity requires an existing Ed25519 key")
        public_key = private_key.public_key()
        from eval_runner.state_authority import receipt_public_key

        anchor = receipt_public_key(identity)
        if anchor is not None and anchor.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ) != public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw):
            raise ValueError(
                "Configured observation signing key does not match its public trust anchor"
            )
        key_reference = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    else:
        from eval_runner.state_authority import receipt_public_key

        public_key = receipt_public_key(identity)
        if public_key is None:
            raise ValueError("Configured observation signer requires a trusted public key")
    signature = backend.sign_payload(payload, key_reference)
    if not isinstance(signature, str):
        raise ValueError("Observation signer must support the existing raw Ed25519 receipt format")
    signature_bytes = bytes.fromhex(signature)
    if len(signature_bytes) != 64:
        raise ValueError("Observation signer returned an invalid Ed25519 signature")
    public_key.verify(signature_bytes, payload)
    return signature_bytes.hex(), public_key
