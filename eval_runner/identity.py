"""
identity.py

Centralized Identity Service for AgentV.
Abstracts key discovery and cryptographic provenance across different backends.
Supports Local PEM files by default, extensible to Vault or AWS KMS.
"""

import logging
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from . import config

logger = logging.getLogger(__name__)


class IdentityService:
    """
    Authoritative service for resolving public and private keys.
    Eliminates filesystem 'crawling' in high-level components.
    """

    @staticmethod
    def get_private_key(
        identity_id: str = "system_id", auto_provision: bool = True
    ) -> ed25519.Ed25519PrivateKey:
        """
        Resolves a private key by ID.
        Priority:
        1. Environment Variable (AES_PRIVATE_KEY_{ID})
        2. Configured TRUST_ROOT
        """
        env_var = f"AES_PRIVATE_KEY_{identity_id.upper()}"
        env_key = os.getenv(env_var)

        if env_key:
            try:
                return serialization.load_pem_private_key(env_key.encode(), password=None)
            except Exception as e:
                logger.warning(f"Failed to load key from environment variable {env_var}: {e}")

        # Security Check: Prevent path traversal in identity_id
        target_path = (config.TRUST_ROOT / identity_id).resolve()
        base_path = config.TRUST_ROOT.resolve()

        # Strict Trust Jail: Identity MUST be within TRUST_ROOT, no exceptions (e.g. Temp Zone)
        try:
            if not target_path.is_relative_to(base_path):
                raise PermissionError(
                    f"Security violation: Identity ID '{identity_id}' is outside trust root."
                )
        except (ValueError, AttributeError) as e:
            # Happens if paths are on different drives or incompatible types
            raise PermissionError(
                f"Security violation: Identity ID '{identity_id}' is outside trust root."
            ) from e

        # Local File Fallback (TRUST_ROOT/{identity_id}/private_key.pem)
        id_dir = config.TRUST_ROOT / identity_id
        key_path = id_dir / "private_key.pem"
        if key_path.exists():
            try:
                with open(key_path, "rb") as f:
                    return serialization.load_pem_private_key(f.read(), password=None)
            except Exception as e:
                logger.error(f"Failed to load private key from {key_path}: {e}")
                raise

        # Security Guardrail: Block auto-provisioning for system_id in production
        if identity_id == "system_id" and not config.ALLOW_SYSTEM_IDENTITY_PROVISIONING:
            raise PermissionError(
                "Security Policy Violation: Auto-provisioning for 'system_id' is disabled. "
                "Please provide a valid private key via environment or TRUST_ROOT."
            )

        # Auto-provision identity if missing for local developer experience
        if not auto_provision:
            return None
        return IdentityService._provision_local_identity(identity_id)

    @staticmethod
    def get_public_key(
        identity_id: str = "system_id", auto_provision: bool = True
    ) -> ed25519.Ed25519PublicKey:
        target_path = (config.TRUST_ROOT / identity_id).resolve()
        base_path = config.TRUST_ROOT.resolve()
        try:
            if not target_path.is_relative_to(base_path):
                raise PermissionError(
                    f"Security violation: Identity ID '{identity_id}' is outside trust root."
                )
        except (ValueError, AttributeError) as e:
            raise PermissionError(
                f"Security violation: Identity ID '{identity_id}' is outside trust root."
            ) from e

        key_path = config.TRUST_ROOT / identity_id / "public_key.pem"

        # Fallback to derivation from private key if public is missing
        if not key_path.exists():
            try:
                priv = IdentityService.get_private_key(identity_id, auto_provision=False)
                if priv:
                    return priv.public_key()
            except Exception as e:
                logger.debug(f"Public key derivation fallback failed for {identity_id}: {e}")

        if key_path.exists():
            try:
                with open(key_path, "rb") as f:
                    return serialization.load_pem_public_key(f.read())
            except Exception as e:
                logger.error(f"Failed to load public key from {key_path}: {e}")
                raise

        # Auto-provision identity if missing for local developer experience
        if not auto_provision:
            return None
        return IdentityService.get_private_key(identity_id).public_key()

    @staticmethod
    def _provision_local_identity(identity_id: str) -> ed25519.Ed25519PrivateKey:
        """Generates and saves a new identity if allowed by config."""
        logger.info(f"Generating new local identity: {identity_id}")
        private_key = ed25519.Ed25519PrivateKey.generate()

        id_dir = config.TRUST_ROOT / identity_id
        id_dir.mkdir(parents=True, exist_ok=True)
        priv_path = id_dir / "private_key.pem"
        pub_path = id_dir / "public_key.pem"

        with open(priv_path, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        with open(pub_path, "wb") as f:
            f.write(
                private_key.public_key().public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )

        return private_key
