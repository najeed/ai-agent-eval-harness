"""
eval_runner.interfaces.auth
Public Extension Family: AuthorizationBackend Contract
"""

from abc import ABC, abstractmethod
from typing import Any


class AuthPrincipal:
    """Represents an authenticated principal (user, service account, api token)."""

    def __init__(
        self,
        principal_id: str,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.principal_id = principal_id
        self.roles = roles or []
        self.permissions = permissions or []
        self.metadata = metadata or {}


class AuthorizationBackend(ABC):
    """
    Abstraction for access control, token validation, and permission checks.
    OSS Reference: SimpleAPIKeyAuthBackend
    Control Plane / Enterprise: OIDC_SCIM_AuthBackend
    """

    @abstractmethod
    def validate_token(self, token: str) -> AuthPrincipal | None:
        """Validates an incoming bearer/API token and returns the principal if valid."""
        raise NotImplementedError

    @abstractmethod
    def check_permission(self, principal: AuthPrincipal, resource: str, action: str = "") -> bool:
        """Checks if the principal is authorized to perform action on resource."""
        raise NotImplementedError
