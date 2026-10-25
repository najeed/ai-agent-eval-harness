"""
agentv_runtime.scope
Scope-agnostic platform infrastructure for multi-tenant isolation.

Runtime treats tenant and workspace context as an opaque, canonical set of
string tags rather than prescribing a concrete organizational hierarchy.
Control Plane or embedding applications supply the concrete topology and
policy rules, while Runtime enforces data boundaries, storage partitioning,
and cryptographic attestation binding.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from agentv_runtime.canonical import canonical_json_encode


@dataclass(frozen=True)
class ScopeToken:
    """Opaque tenant boundary token owned by the runtime platform.

    Tags represent an arbitrary key-value scope (e.g. org/tenant/workspace/env,
    or project/account, or local workspace). The digest is a deterministic
    RFC 8785 canonical SHA3-256 hash ensuring identical identity across systems.
    """

    tags: dict[str, str]
    digest: str
    is_system: bool = False

    @classmethod
    def from_tags(
        cls, tags: Mapping[str, Any] | None = None, is_system: bool = False
    ) -> ScopeToken:
        """Create a ScopeToken with a deterministic canonical digest."""
        if not tags:
            return cls(tags={}, digest="", is_system=is_system)

        normalized: dict[str, str] = {
            str(k): str(v)
            for k, v in tags.items()
            if v is not None and isinstance(v, (str, int, float, bool))
        }

        if not normalized:
            return cls(tags={}, digest="", is_system=is_system)

        canonical_bytes = canonical_json_encode(normalized)
        digest = hashlib.sha3_256(canonical_bytes).hexdigest()
        return cls(tags=normalized, digest=digest, is_system=is_system)

    def matches(self, other: ScopeToken | None) -> bool:
        """Return True if scopes represent the same isolation partition."""
        if other is None:
            return False
        if self.is_system or other.is_system:
            return True
        return self.digest == other.digest


class ScopePolicy(Protocol):
    """Platform protocol for tenant resolution and boundary filtering."""

    def resolve_scope(self, principal: dict[str, Any]) -> ScopeToken | None:
        """Extract and validate the active scope from the principal."""
        ...  # pragma: no cover

    def allows_record(self, record: dict[str, Any], active_scope: ScopeToken | None) -> bool:
        """Predicate checking whether an active scope can read/mutate a record."""
        ...  # pragma: no cover

    def is_scope_mandatory(self) -> bool:
        """Whether unscoped requests are rejected (Enterprise) or defaulted (OSS)."""
        ...  # pragma: no cover

    def allows_permission(
        self,
        principal: dict[str, Any],
        permission_node: str,
        active_scope: ScopeToken | None = None,
    ) -> bool | None:
        """Optionally govern or override permission checks for the active scope."""
        ...  # pragma: no cover

    def validate_scope(self, scope: ScopeToken) -> None:
        """Validate scope token against policy rules."""
        ...  # pragma: no cover


class LocalOrSingleTenantScopePolicy:
    """Default scope policy for OSS Runtime, single-tenant, and local environments.

    In OSS mode, requests without enterprise context claims are treated as
    valid local/single-tenant runs. Unscoped service and admin principals
    are granted system scope so local development and CLI automation operate
    with zero friction.
    """

    def __init__(self, default_tags: Mapping[str, str] | None = None):
        self.default_tags = dict(default_tags) if default_tags else None

    def validate_scope(self, scope: ScopeToken) -> None:
        """Validate scope token against policy rules (no-op in OSS mode)."""
        pass

    def is_scope_mandatory(self) -> bool:
        return False

    def resolve_scope(self, principal: dict[str, Any]) -> ScopeToken | None:
        if not isinstance(principal, dict):
            return None

        # 1. Explicit context dict on principal takes precedence
        context = principal.get("context")
        if isinstance(context, dict) and context:
            return ScopeToken.from_tags(context, is_system=False)

        # 2. Unscoped backend service or root admin principals receive system scope
        permissions = principal.get("permissions") or []
        principal_type = principal.get("type")
        if "*" in permissions or principal_type in ("backend-auth", "api-key"):
            return ScopeToken.from_tags(None, is_system=True)

        # 3. Default local tags if configured
        if self.default_tags:
            return ScopeToken.from_tags(self.default_tags, is_system=False)

        # 4. Standard un-tenanted principal
        return ScopeToken.from_tags(None, is_system=False)

    def allows_record(self, record: dict[str, Any], active_scope: ScopeToken | None) -> bool:
        if active_scope is None or active_scope.is_system:
            return True

        if not active_scope.tags:
            return True

        if not isinstance(record, dict):
            return True

        if active_scope.digest and record.get("scope_digest") == active_scope.digest:
            return True

        source = record.get("context") if isinstance(record.get("context"), dict) else record
        metadata = record.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("runtime_context"), dict):
            source = metadata["runtime_context"]

        return all(source.get(k) == v for k, v in active_scope.tags.items())

    def allows_permission(
        self,
        principal: dict[str, Any],
        permission_node: str,
        active_scope: ScopeToken | None = None,
    ) -> bool | None:
        return None


class EnterpriseTaggedScopePolicy:
    """Configurable enterprise scope policy for Control Plane and multi-tenant fleets.

    Enforces that all requests carry mandatory scope tags (e.g. org/tenant/workspace/env).
    Unscoped requests are rejected at the authentication gate, and data access
    is strictly partitioned by matching scope tags.
    """

    def __init__(
        self,
        required_tags: tuple[str, ...] = (
            "org_id",
            "tenant_id",
            "workspace_id",
            "active_environment",
        ),
        allow_wildcard_system_principals: bool = True,
    ):
        self.required_tags = required_tags
        self.allow_wildcard_system_principals = allow_wildcard_system_principals

    def is_scope_mandatory(self) -> bool:
        return True

    def resolve_scope(self, principal: dict[str, Any]) -> ScopeToken | None:
        if not isinstance(principal, dict):
            return None

        # Wildcard / service backend keys may be authorized as cross-tenant system tokens
        if self.allow_wildcard_system_principals:
            permissions = principal.get("permissions") or []
            if "*" in permissions and not principal.get("context"):
                return ScopeToken.from_tags(None, is_system=True)

        context = principal.get("context")
        if not isinstance(context, dict):
            return None

        if not all(
            isinstance(context.get(tag), str) and context[tag] for tag in self.required_tags
        ):
            return None

        return ScopeToken.from_tags(context, is_system=False)

    def allows_record(self, record: dict[str, Any], active_scope: ScopeToken | None) -> bool:
        if active_scope is None:
            return False

        if active_scope.is_system:
            return True

        if not isinstance(record, dict):
            return False

        if active_scope.digest and record.get("scope_digest") == active_scope.digest:
            return True

        source = record.get("context") if isinstance(record.get("context"), dict) else record
        metadata = record.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("runtime_context"), dict):
            source = metadata["runtime_context"]

        return all(source.get(k) == v for k, v in active_scope.tags.items())

    def allows_permission(
        self,
        principal: dict[str, Any],
        permission_node: str,
        active_scope: ScopeToken | None = None,
    ) -> bool | None:
        if active_scope is None and not (
            self.allow_wildcard_system_principals and "*" in (principal.get("permissions") or [])
        ):
            return False
        return None


_active_scope_policy: ScopePolicy | None = None


def set_active_scope_policy(policy: ScopePolicy | None) -> None:
    """Set an explicit scope-policy override for embedding applications and tests."""
    global _active_scope_policy
    _active_scope_policy = policy


def get_active_scope_policy() -> ScopePolicy:
    """Resolve scope governance from the canonical authorization backend.

    Scope evaluation is part of authorization, not a parallel extension family.
    Authorization providers may expose either ``get_scope_policy()`` or a
    ``scope_policy`` attribute; local runtime uses the OSS policy fallback.
    """
    import os

    if _active_scope_policy is not None:
        return _active_scope_policy
    if os.environ.get("AGENTV_REQUIRE_ENTERPRISE_CONTEXT") == "1":
        return EnterpriseTaggedScopePolicy()

    from agentv_runtime.discovery import resolve_extension

    backend = resolve_extension("authorization_backends", default_factory=lambda: None)
    provider = getattr(backend, "get_scope_policy", None)
    policy = provider() if callable(provider) else getattr(backend, "scope_policy", None)
    return policy if policy is not None else LocalOrSingleTenantScopePolicy()
