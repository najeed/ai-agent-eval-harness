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

    _pqc_client = None

    @staticmethod
    def get_signature_policy(identity_id: str, public_key=None, trust_root=None):
        """Load purpose/profile/rotation policy from the external trusted identity directory.

        Absent an explicit policy, the trusted public-key fingerprint is the key ID.
        Existing raw Ed25519 evidence remains enabled by this explicit default policy.
        KMS key ARN bindings require a separately provisioned signature_policy.json.
        """
        import json
        from datetime import datetime
        from pathlib import Path

        from agentv_runtime.signatures import (
            PROFILE,
            PROJECTIONS,
            SignatureContractError,
            SignaturePolicy,
            canonical_payload_from_json,
            fingerprint,
        )

        root = Path(trust_root or config.TRUST_ROOT).resolve()
        directory = (root / identity_id).resolve()
        if not directory.is_relative_to(root):
            raise SignatureContractError("Signature identity is outside the external trust root")
        if public_key is None:
            key_file = directory / "public_key.pem"
            public_key = (
                serialization.load_pem_public_key(key_file.read_bytes())
                if key_file.is_file()
                else IdentityService.get_public_key(identity_id, auto_provision=False)
            )
        path = directory / "signature_policy.json"
        if not path.exists():
            return SignaturePolicy(identity_id, "sha256:" + fingerprint(public_key), public_key)
        policy = json.loads(canonical_payload_from_json(path.read_bytes()))
        allowed = {
            "version",
            "key_id",
            "permitted_profiles",
            "permitted_purposes",
            "allow_legacy_raw",
            "revoked",
            "not_before",
            "not_after",
        }
        required = allowed - {"not_before", "not_after"}
        if (
            not isinstance(policy, dict)
            or set(policy) - allowed
            or required - set(policy)
            or type(policy["version"]) is not int
            or policy["version"] != 1
            or not isinstance(policy["key_id"], str)
            or type(policy["allow_legacy_raw"]) is not bool
            or type(policy["revoked"]) is not bool
        ):
            raise SignatureContractError("Malformed external signature policy")
        for name, supported in (
            ("permitted_profiles", {PROFILE, "ed25519-raw"}),
            ("permitted_purposes", set(PROJECTIONS)),
        ):
            values = policy[name]
            if (
                not isinstance(values, list)
                or any(not isinstance(value, str) or value not in supported for value in values)
                or len(set(values)) != len(values)
            ):
                raise SignatureContractError("Unknown or ambiguous external signature policy")
        intervals = {}
        for name in ("not_before", "not_after"):
            value = policy.get(name)
            if value is not None:
                value = datetime.fromisoformat(value)
                if value.tzinfo is None:
                    raise SignatureContractError("Signature policy times require a timezone")
            intervals[name] = value
        return SignaturePolicy(
            identity_id,
            policy["key_id"],
            public_key,
            permitted_profiles=tuple(policy["permitted_profiles"]),
            permitted_purposes=tuple(policy["permitted_purposes"]),
            allow_legacy_raw=policy["allow_legacy_raw"],
            revoked=policy["revoked"],
            **intervals,
        )

    @classmethod
    def get_pqc_client(cls):
        """
        Resolves the PQC client based on configuration.
        Implements lazy-loading and provider discovery.
        """
        if not config.PQC_ENABLED:
            return None

        if cls._pqc_client is not None:
            return cls._pqc_client

        if config.PQC_PROVIDER == "cyclecore":
            try:
                from cyclecore_pq.client import CycleCoreClient

                cls._pqc_client = CycleCoreClient(api_key=config.CYCLECORE_API_KEY)

                # Dynamically inject sign_digest and verify_digest to match ZES interface
                import base64

                def sign_digest(digest: bytes, identity_id: str = None) -> str:
                    result = cls._pqc_client.sign(digest)
                    return result.signature

                def verify_digest(
                    signature: str | bytes, digest: bytes, identity_id: str = None
                ) -> bool:
                    if isinstance(signature, str):
                        try:
                            # Try base64 decoding first
                            sig_bytes = base64.b64decode(signature)
                            if len(sig_bytes) < 100:
                                raise ValueError()
                        except Exception:
                            try:
                                sig_bytes = bytes.fromhex(signature)
                            except Exception:
                                sig_bytes = signature.encode()
                    else:
                        sig_bytes = signature

                    try:
                        result = cls._pqc_client.verify(digest, sig_bytes)
                        return result.valid
                    except Exception as e:
                        logger.error(f"   [Identity] PQC Verification exception: {e}")
                        return False

                cls._pqc_client.sign_digest = sign_digest
                cls._pqc_client.verify_digest = verify_digest

                logger.info(
                    "   [Identity] CycleCore PQC Client initialized with ZES interface extension."
                )
                return cls._pqc_client
            except ImportError:
                logger.error(
                    "   [Identity] FAIL: 'cyclecore-pq' package not found. "
                    "Please install it to use PQC features."
                )
            except Exception as e:
                logger.error(f"   [Identity] FAIL: Failed to initialize CycleCore Client: {e}")
        else:
            logger.warning(f"   [Identity] Unsupported PQC Provider: {config.PQC_PROVIDER}")

        return None

    @staticmethod
    def get_private_key(
        identity_id: str = "system_id", auto_provision: bool = True
    ) -> ed25519.Ed25519PrivateKey:
        """
        Resolves a private key by ID.
        Priority:
        1. Environment Variable (CORE_ARTIFACT_SIGNING_PEM_{ID})
        2. Configured TRUST_ROOT
        """
        env_var = f"CORE_ARTIFACT_SIGNING_PEM_{identity_id.upper()}"
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

        # Security Guardrail: Block auto-provisioning for certification identities in production
        certification_identities = {
            "system_id",
            "eval_kernel",
            "certification_authority",
            "evaluator",
            "attestation_signer",
            "eval_runner.runner.EvaluationKernel",
        }
        is_prod = config.is_production()
        if (
            (identity_id in certification_identities or identity_id.startswith("cert_")) or is_prod
        ) and not config.ALLOW_SYSTEM_IDENTITY_PROVISIONING:
            raise PermissionError(
                f"Security Policy Violation: Auto-provisioning for '{identity_id}' is disabled. "
                "Please provide a valid private key via environment or TRUST_ROOT."
            )

        # Auto-provision identity if missing for local developer experience
        if not auto_provision:
            return None
        return IdentityService._provision_local_identity(identity_id)

    @staticmethod
    def get_public_key(
        identity_id: str = "system_id", auto_provision: bool = False
    ) -> ed25519.Ed25519PublicKey:
        env_var = f"AES_PUBLIC_KEY_{identity_id.upper()}"
        env_key = os.getenv(env_var)
        if env_key:
            try:
                return serialization.load_pem_public_key(env_key.encode())
            except Exception as e:
                logger.warning(
                    f"Failed to load public key from environment variable {env_var}: {e}"
                )

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

        if key_path.exists():
            try:
                with open(key_path, "rb") as f:
                    return serialization.load_pem_public_key(f.read())
            except Exception as e:
                logger.error(f"Failed to load public key from {key_path}: {e}")
                raise

        # Fallback to derivation from private key if public is missing
        try:
            priv = IdentityService.get_private_key(identity_id, auto_provision=False)
            if priv:
                return priv.public_key()
        except Exception as e:
            logger.debug(f"Public key derivation fallback failed for {identity_id}: {e}")

        # Auto-provision identity only if explicitly requested
        if not auto_provision:
            return None
        priv = IdentityService.get_private_key(identity_id, auto_provision=True)
        return priv.public_key() if priv else None

    @staticmethod
    def _provision_local_identity(identity_id: str) -> ed25519.Ed25519PrivateKey:
        """
        Generates and saves a new identity if allowed by config.
        NOTE: Local unencrypted key storage is intended for development and local testing.
        Production enterprise deployments should use KMS/HSM or environment-supplied keys.
        """
        logger.warning(
            f"Generating local dev identity '{identity_id}' with unencrypted PEM storage. "
            "For enterprise audit-defensible attestation, configure a KMS/HSM signing backend."
        )
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


def get_default_signer():
    """
    Resolves the default SigningBackend based on environment configuration.
    """
    from eval_runner.runtime_services import NullSigningBackend, resolve_signing_backend

    key_path = os.getenv("FLIGHT_RECORDER_KEY_PATH")
    if key_path:
        return resolve_signing_backend()
    return NullSigningBackend()
