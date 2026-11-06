"""
eval_runner.reference.auth
OSS Reference Implementation: SimpleAPIKeyAuthBackend
"""

import logging
import os
from typing import Any

from eval_runner.interfaces.auth import AuthorizationBackend, AuthPrincipal

logger = logging.getLogger(__name__)


class SimpleAPIKeyAuthBackend(AuthorizationBackend):
    """
    Simple API Key based reference authorization backend.
    Validates tokens against static keys or environment variables
    (EVAL_MASTER_KEY, CONSOLE_MASTER_KEY).
    If no keys are configured, authentication is unavailable.
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
        else:
            self.master_key = None

        self._keys: dict[str, dict[str, Any]] = dict(static_keys or {})

        # Ensure master key is registered
        if self.master_key and self.master_key not in self._keys:
            self._keys[self.master_key] = {
                "principal_id": "root-admin",
                "roles": ["admin"],
                "permissions": ["*"],
                "metadata": {"name": "System Administrator", "type": "static-root"},
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

    def list_keys(self, mask: bool = True) -> list[str]:
        """
        Lists all active registered API keys.
        By default (mask=True), returns masked key previews to prevent secret disclosure.
        """
        if mask:
            return [f"{k[:4]}...{k[-4:]}" if len(k) >= 8 else "***" for k in self._keys]
        return list(self._keys.keys())

    def list_principals(self) -> list[dict[str, Any]]:
        """Lists metadata of all registered principals without exposing raw secrets."""
        principals = []
        for k, v in self._keys.items():
            preview = f"{k[:4]}...{k[-4:]}" if len(k) >= 8 else "***"
            principals.append(
                {
                    "principal_id": v.get("principal_id", "unknown"),
                    "roles": v.get("roles", []),
                    "permissions": v.get("permissions", []),
                    "metadata": v.get("metadata", {}),
                    "key_preview": preview,
                }
            )
        return principals

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
                context_version=info.get(
                    "context_version", info.get("metadata", {}).get("context_version")
                ),
                context=info.get("context", info.get("metadata", {}).get("context")),
                authorized_contexts=info.get(
                    "authorized_contexts", info.get("metadata", {}).get("authorized_contexts")
                ),
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

    def get_service_credential(self) -> str | None:
        """Returns the master key or registered service credential."""
        if self.master_key:
            return self.master_key
        if self._keys:
            return next(iter(self._keys.keys()))
        return None


class OIDCAuthorizationBackend(AuthorizationBackend):
    """OIDC authority with explicit trust configuration and literal permissions.

    Roles are descriptive claims. Only explicit permissions (or OAuth scopes)
    authorize actions; wildcard entitlements are never accepted from JWTs.
    """

    def __init__(self, jwks_url, issuer, audience, cache_ttl=3600):
        self.jwks_url = jwks_url
        self.issuer = issuer
        self.audience = audience
        self.cache_ttl = cache_ttl
        self._jwks_client = None

    def validate_token(self, token: str) -> AuthPrincipal | None:
        if not all(
            isinstance(v, str) and v.strip()
            for v in (token, self.jwks_url, self.issuer, self.audience)
        ):
            return None
        try:
            import jwt

            from eval_runner.console.auth_manager import normalize_entitlements

            if self._jwks_client is None:
                self._jwks_client = jwt.PyJWKClient(
                    self.jwks_url,
                    cache_jwk_set=True,
                    cache_lifetime=self.cache_ttl,
                )
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                leeway=10,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["sub", "iss", "aud", "exp"]},
            )
            subject = payload.get("sub")
            roles = payload.get("roles", [])
            permissions = payload.get("permissions", payload.get("scope", "").split())
            if (
                not isinstance(subject, str)
                or not subject
                or not isinstance(roles, list)
                or not isinstance(permissions, list)
                or any(not isinstance(r, str) or not r for r in roles)
                or any(not isinstance(p, str) or not p or "*" in p for p in permissions)
            ):
                return None
            metadata = dict(payload)
            metadata["type"] = "oidc-sso"
            if "environment" in payload and "active_environment" not in payload:
                metadata["active_environment"] = payload["environment"]
            metadata = normalize_entitlements(metadata)
            return AuthPrincipal(subject, roles=roles, permissions=permissions, metadata=metadata)
        except Exception:
            logging.getLogger(__name__).debug(
                "Failure in OIDCAuthorizationBackend.validate_token", exc_info=True
            )
            return None

    def check_permission(self, principal: AuthPrincipal, resource: str, action: str = "") -> bool:
        target = f"{resource}:{action}" if action else resource
        return target in principal.permissions and "*" not in target
