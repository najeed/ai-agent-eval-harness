"""
eval_runner.reference.auth
OSS Reference Implementation: SimpleAPIKeyAuthBackend
"""

import logging
import os
import secrets
from typing import Any

from eval_runner.interfaces.auth import AuthorizationBackend, AuthPrincipal

logger = logging.getLogger(__name__)


class SimpleAPIKeyAuthBackend(AuthorizationBackend):
    """
    Simple API Key based reference authorization backend.
    Validates tokens against static keys or environment variables
    (EVAL_MASTER_KEY, CONSOLE_MASTER_KEY).
    If no keys or environment master key are configured, generates
    a secure random bootstrap token at startup.
    """

    def __init__(
        self,
        static_keys: dict[str, dict[str, Any]] | None = None,
        master_key: str | None = None,
    ):
        env_master = os.getenv("EVAL_MASTER_KEY", os.getenv("CONSOLE_MASTER_KEY"))
        if master_key is not None:
            self.master_key: str | None = master_key if master_key else None
        elif env_master:
            self.master_key = env_master
        elif not static_keys:
            # Generate a secure dynamic bootstrap secret rather than shipping a static default
            self.master_key = secrets.token_urlsafe(32)
            logger.info("Generated dynamic bootstrap master API key: %s", self.master_key)
        else:
            self.master_key = None

        self._keys: dict[str, dict[str, Any]] = dict(static_keys or {})

        # Ensure master key is registered
        if self.master_key and self.master_key not in self._keys:
            self._keys[self.master_key] = {
                "principal_id": "root-admin",
                "roles": ["admin"],
                "permissions": ["*"],
                "metadata": {"name": "System Administrator"},
            }

    def register_key(
        self,
        key: str,
        principal_id: str,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        """Registers an API key with specific roles and permissions."""
        self._keys[key] = {
            "principal_id": principal_id,
            "roles": roles or ["user"],
            "permissions": permissions or [],
            "metadata": metadata or {},
        }

    def revoke_key(self, key: str) -> bool:
        """Revokes a registered API key."""
        if key in self._keys:
            del self._keys[key]
            if self.master_key == key:
                self.master_key = None
            return True
        return False

    def list_keys(self) -> list[str]:
        """Lists all active registered API keys."""
        return list(self._keys.keys())

    def validate_token(self, token: str) -> AuthPrincipal | None:
        """Validates incoming token against registered keys or master key."""
        if not token:
            return None

        # Direct match in registered keys
        if token in self._keys:
            info = self._keys[token]
            return AuthPrincipal(
                principal_id=info.get("principal_id", "unknown"),
                roles=info.get("roles", []),
                permissions=info.get("permissions", []),
                metadata=info.get("metadata", {}),
            )

        # Fallback to master key match
        if self.master_key and token == self.master_key:
            return AuthPrincipal(
                principal_id="root-admin",
                roles=["admin"],
                permissions=["*"],
                metadata={"name": "System Administrator"},
            )

        return None

    def check_permission(self, principal: AuthPrincipal, resource: str, action: str = "") -> bool:
        """
        Checks if the principal is authorized.
        Evaluates permissions for wildcard '*', exact permission match, or 'resource:action'.
        """
        if not principal:
            return False

        target_permission = f"{resource}:{action}" if action else resource

        for perm in principal.permissions:
            if perm == "*":
                return True
            if perm == target_permission or perm == resource:
                return True
            if perm.endswith(":*") and target_permission.startswith(perm[:-1]):
                return True

        return False
