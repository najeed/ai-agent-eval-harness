"""
eval_runner/signing_readiness.py
Authoritative runtime Signer Readiness and Cryptographic Health Resolver.

Single source of truth for /api/status, /api/scenarios/readiness, doctor audits,
and pre-certification verification gates.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SigningReadinessResult:
    """Represents the authoritative health and verifiability state of the signer."""

    is_ready: bool
    is_verifiable: bool
    signer_type: str  # "SIGNED", "NULL", "FAILED"
    key_identifier: str | None
    error_message: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_ready": self.is_ready,
            "is_verifiable": self.is_verifiable,
            "signer_type": self.signer_type,
            "key_identifier": self.key_identifier,
            "error_message": self.error_message,
        }


def check_signing_readiness() -> SigningReadinessResult:
    """
    Authoritatively checks whether the active runtime environment possesses a
    healthy, loadable, and cryptographically sound persistent signing key.

    Priority order:
    1. FLIGHT_RECORDER_KEY_PATH (file path)
    2. CORE_ARTIFACT_SIGNING_PEM / CORE_ARTIFACT_SIGNING_PEM_SYSTEM_ID (inline PEM)
    3. IdentityService persistent key store (TRUST_ROOT)
    """
    key_path_env = os.getenv("FLIGHT_RECORDER_KEY_PATH")
    inline_pem = os.getenv("CORE_ARTIFACT_SIGNING_PEM") or os.getenv(
        "CORE_ARTIFACT_SIGNING_PEM_SYSTEM_ID"
    )

    priv_key: ed25519.Ed25519PrivateKey | None = None
    key_source: str = ""

    # 1. File path configuration
    if key_path_env:
        p = Path(key_path_env)
        if not p.exists():
            msg = f"Configured FLIGHT_RECORDER_KEY_PATH file not found: {key_path_env}"
            logger.warning(msg)
            return SigningReadinessResult(
                is_ready=False,
                is_verifiable=False,
                signer_type="FAILED",
                key_identifier=str(key_path_env)[:16],
                error_message=msg,
            )
        try:
            priv_key = serialization.load_pem_private_key(p.read_bytes(), password=None)
            key_source = f"file:{p.name}"
        except Exception as e:
            msg = f"Failed to parse private key from FLIGHT_RECORDER_KEY_PATH ({key_path_env}): {e}"
            logger.warning(msg)
            return SigningReadinessResult(
                is_ready=False,
                is_verifiable=False,
                signer_type="FAILED",
                key_identifier=str(key_path_env)[:16],
                error_message=msg,
            )

    # 2. Inline PEM configuration
    if priv_key is None and inline_pem:
        try:
            priv_key = serialization.load_pem_private_key(inline_pem.encode("utf-8"), password=None)
            key_source = "inline:CORE_ARTIFACT_SIGNING_PEM"
        except Exception as e:
            msg = f"Failed to parse private key from CORE_ARTIFACT_SIGNING_PEM: {e}"
            logger.warning(msg)
            return SigningReadinessResult(
                is_ready=False,
                is_verifiable=False,
                signer_type="FAILED",
                key_identifier="inline_pem",
                error_message=msg,
            )

    # 3. IdentityService persistent storage fallback
    if priv_key is None:
        try:
            from eval_runner.identity import IdentityService

            priv_key = IdentityService.get_private_key("system_id", auto_provision=False)
            if priv_key is not None:
                key_source = "identity_service:system_id"
        except Exception as e:
            logger.debug("IdentityService private key lookup returned: %s", e)

    # If no key found at all, return NULL (ephemeral/unanchored) signer state
    if priv_key is None:
        return SigningReadinessResult(
            is_ready=True,
            is_verifiable=False,
            signer_type="NULL",
            key_identifier=None,
            error_message=(
                "No persistent signing key configured (FLIGHT_RECORDER_KEY_PATH / "
                "CORE_ARTIFACT_SIGNING_PEM). Generated certificates will be PROVISIONAL."
            ),
        )

    # 4. Perform active cryptographic health probe (sign & verify round-trip)
    try:
        probe_payload = b"__agentv_authoritative_signer_readiness_probe__"
        sig = priv_key.sign(probe_payload)
        pub_key = priv_key.public_key()
        pub_key.verify(sig, probe_payload)
        key_raw = pub_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        snippet = key_raw.hex()[:12]
        return SigningReadinessResult(
            is_ready=True,
            is_verifiable=True,
            signer_type="SIGNED",
            key_identifier=f"{key_source} ({snippet}...)",
            error_message=None,
        )
    except Exception as e:
        msg = f"Cryptographic health probe failed on active key: {e}"
        logger.error(msg)
        return SigningReadinessResult(
            is_ready=False,
            is_verifiable=False,
            signer_type="FAILED",
            key_identifier=key_source,
            error_message=msg,
        )
