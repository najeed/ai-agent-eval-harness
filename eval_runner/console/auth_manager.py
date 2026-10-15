import importlib
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path

from eval_runner.interfaces.auth import AuthorizationBackend, AuthPrincipal
from eval_runner.reference.auth import SimpleAPIKeyAuthBackend


class Permission:
    """
    Standard Granular Permission Nodes for the AES Evaluation Harness (Strict PBAC).
    Enterprise plugins can define custom strings (e.g., "billing:admin").
    """

    # 1. Read-Only Nodes
    SCENARIOS_READ = "scenarios:read"
    RUNS_READ = "runs:read"
    DOCS_READ = "docs:read"
    DEBUG_READ = "debugger:read"
    IDENTITY_READ = "identity:read"

    # 2. Operator Nodes (Execution)
    EVAL_TRIGGER = "eval:trigger"
    DEMO_EXECUTE = "demo:execute"
    INDEX_REFRESH = "index:refresh"
    DEBUG_EVENT = "debugger:event"
    CERTIFY_WRITE = "certify:write"
    HITL_RESOLVE = "hitl:resolve"
    RUNS_WRITE = "runs:write"
    EXTENSIONS_RUN = "extensions:run"

    # 3. Admin Nodes (Destructive / Config)
    SCENARIOS_WRITE = "scenarios:write"
    SCENARIOS_DELETE = "scenarios:delete"
    DEBUG_RESET = "debugger:reset"
    SYSTEM_CONFIG = "system:config"

    @classmethod
    def ADMIN(cls) -> list[str]:
        """Authoritative set of all granular permission nodes (AgentV v1.6.0 Standard)."""
        return [
            cls.SCENARIOS_READ,
            cls.RUNS_READ,
            cls.DOCS_READ,
            cls.DEBUG_READ,
            cls.IDENTITY_READ,
            cls.EVAL_TRIGGER,
            cls.DEMO_EXECUTE,
            cls.INDEX_REFRESH,
            cls.DEBUG_EVENT,
            cls.CERTIFY_WRITE,
            cls.HITL_RESOLVE,
            cls.RUNS_WRITE,
            cls.EXTENSIONS_RUN,
            cls.SCENARIOS_WRITE,
            cls.SCENARIOS_DELETE,
            cls.DEBUG_RESET,
            cls.SYSTEM_CONFIG,
        ]


CONTEXT_VERSION = "2"
CONTEXT_FIELDS = ("org_id", "tenant_id", "workspace_id", "active_environment")


def normalize_entitlements(user: dict) -> dict:
    """Return a fail-closed, provider-owned normalized principal.

    A principal without any context claims is a valid unscoped service
    principal.  Once a provider supplies entitlement claims, however, the v2
    claim is mandatory and every active scope must be an allowlisted tuple.
    """
    has_entitlements = any(k in user for k in ("context_version", "context", "authorized_contexts"))
    has_legacy_context = any(k in user for k in CONTEXT_FIELDS)
    if not has_entitlements and not has_legacy_context:
        return dict(user)

    version = user.get("context_version")
    context = user.get("context")
    entries = user.get("authorized_contexts")
    # Flat provider fields are accepted only as a compatibility input and are
    # normalized before storage; request values never enter this function.
    if context is None and has_legacy_context:
        context = {field: user.get(field) for field in CONTEXT_FIELDS}
    if entries is None and has_legacy_context:
        entries = [
            {
                "org_id": context.get("org_id"),
                "tenant_id": context.get("tenant_id"),
                "workspace_id": context.get("workspace_id"),
                "environments": [context.get("active_environment")],
            }
        ]
        version = version or CONTEXT_VERSION
    if (
        version != CONTEXT_VERSION
        or not isinstance(context, dict)
        or not isinstance(entries, list)
        or not entries
    ):
        raise ValueError("invalid configured principal entitlements")
    if set(context) != set(CONTEXT_FIELDS) or any(
        not isinstance(context[k], str) or not context[k] for k in CONTEXT_FIELDS
    ):
        raise ValueError("invalid active entitlement context")
    normalized_entries = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "org_id",
            "tenant_id",
            "workspace_id",
            "environments",
        }:
            raise ValueError("malformed authorized context")
        key = tuple(entry.get(k) for k in CONTEXT_FIELDS[:-1])
        environments = entry.get("environments")
        if (
            key in seen
            or any(not isinstance(v, str) or not v for v in key)
            or not isinstance(environments, list)
            or not environments
            or any(not isinstance(v, str) or not v for v in environments)
            or len(set(environments)) != len(environments)
        ):
            raise ValueError("duplicate or malformed authorized context")
        seen.add(key)
        normalized_entries.append(
            {**{k: entry[k] for k in CONTEXT_FIELDS[:-1]}, "environments": list(environments)}
        )
    active_key = tuple(context[k] for k in CONTEXT_FIELDS[:-1])
    match = next(
        (
            entry
            for entry in normalized_entries
            if tuple(entry[k] for k in CONTEXT_FIELDS[:-1]) == active_key
        ),
        None,
    )
    if match is None or context["active_environment"] not in match["environments"]:
        raise ValueError("active context is not authorized")
    result = dict(user)
    result.update(context)
    result.update(
        {
            "context_version": CONTEXT_VERSION,
            "context": dict(context),
            "authorized_contexts": normalized_entries,
        }
    )
    return result


class AuthManager(ABC):
    """Base interface for authentication and PBAC integration."""

    @abstractmethod
    def authenticate(self, credentials: str) -> dict | None:
        """Verify credentials and return a user profile (id, name, permissions)."""
        pass

    @abstractmethod
    def verify_token(self, token: str) -> dict | None:
        """Verify OAuth2/OIDC JWT Bearer token."""
        pass

    @abstractmethod
    def has_permission(self, user: dict, permission_node: str) -> bool:
        """Check if a user has the required granular permission node."""
        pass

    def get_service_credential(self) -> str | None:
        """Retrieve a service credential for background machine clients."""
        return None


class StaticKeyProvider(AuthManager):
    """Default OSS provider: Single Master/Root Key maps to explicit granular nodes."""

    def __init__(self, key: str, backend: AuthorizationBackend | None = None):
        self.key = key
        # Only the built-in fallback backend represents the legacy static
        # root key.  A supplied backend is the verified authority for its
        # principal claims, even when it happens to use the reference backend
        # implementation.
        self._uses_configured_backend = backend is not None
        self.backend = backend or SimpleAPIKeyAuthBackend(master_key=key)
        self._register_demo_principals()
        self._jwks_client = None
        self._jwks_url_cached = None

    def _register_demo_principals(self) -> None:
        """Load explicit local demo identities only when demo mode is enabled.

        This deliberately is not a production identity source: each credential
        is registered in the in-memory reference backend at startup and all
        tenant/workspace/environment claims originate from that verified
        principal, never a Console request.
        """
        from .. import config

        fixture_path = os.getenv("AGENTV_DEMO_IDENTITIES_FILE", "").strip()
        if not getattr(config, "ENABLE_DEMO", False) or not fixture_path:
            return
        if not isinstance(self.backend, SimpleAPIKeyAuthBackend):
            return

        try:
            payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
            principals = payload.get("principals", [])
            if not isinstance(principals, list):
                raise ValueError("'principals' must be a list")
            for item in principals:
                if not isinstance(item, dict):
                    raise ValueError("each principal must be an object")
                api_key = str(item["api_key"])
                principal_id = str(item["id"])
                permissions = item.get("permissions", [])
                roles = item.get("roles", [])
                if not isinstance(permissions, list) or not isinstance(roles, list):
                    raise ValueError("permissions and roles must be lists")
                metadata = {
                    claim: item[claim]
                    for claim in (
                        "name",
                        "email",
                        "role",
                        "roles",
                        "org_id",
                        "tenant_id",
                        "workspace_id",
                        "active_environment",
                        "context_version",
                        "context",
                        "authorized_contexts",
                    )
                    if item.get(claim) is not None
                }
                self.backend.register_key(
                    api_key,
                    principal_id=principal_id,
                    roles=[str(role) for role in roles],
                    permissions=[str(permission) for permission in permissions],
                    metadata=metadata,
                )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid demo identity fixture: {fixture_path}") from exc

    def authenticate(self, credentials: str) -> dict | None:
        if not credentials:
            return None

        # Check backend first
        principal = self.backend.validate_token(credentials)
        if principal:
            perms = list(principal.permissions)
            ptype = principal.metadata.get(
                "type", "static-root" if principal.principal_id == "root-admin" else "backend-auth"
            )
            # Preserve configured/OIDC backend permissions exactly.  The
            # finite Core expansion exists solely for the old unscoped static
            # root-key compatibility path; replacing '*' elsewhere would
            # erase extension-defined permission vocabularies.
            if (
                not self._uses_configured_backend
                and ptype == "static-root"
                and principal.principal_id == "root-admin"
                and "*" in perms
            ):
                perms = Permission.ADMIN()
            user = {
                "id": principal.principal_id,
                "name": principal.metadata.get("name", principal.principal_id),
                "permissions": perms,
                "type": ptype,
            }
            if principal.roles:
                user["roles"] = list(principal.roles)
            # Context is supplied by the authorization backend, never by a
            # Console request.  Preserve it when a backend supports it.
            for claim in (
                "email",
                "role",
                "roles",
                "org_id",
                "tenant_id",
                "workspace_id",
                "active_environment",
                "context_version",
                "context",
                "authorized_contexts",
            ):
                if claim in principal.metadata:
                    user[claim] = principal.metadata[claim]
            for claim in ("context_version", "context", "authorized_contexts"):
                value = getattr(principal, claim, None)
                if value is not None:
                    user[claim] = value
            return user

        if not self.key or credentials != self.key:
            return None

        # [Hardening] Explicit Granular Nodes
        return {
            "id": "root-admin",
            "name": "System Administrator",
            "permissions": Permission.ADMIN(),
            "type": "static-root",
        }

    def verify_token(self, token: str) -> dict | None:
        """
        Verify OAuth2/OIDC JWT Bearer token.
        If config.OIDC_JWKS_URL is set, verifies signature against the JWKS endpoint.
        Otherwise, falls back to checking if the token matches the static Master Key.
        """
        from .. import config

        if config.OIDC_JWKS_URL:
            try:
                import jwt

                if not self._jwks_client or self._jwks_url_cached != config.OIDC_JWKS_URL:
                    self._jwks_client = jwt.PyJWKClient(
                        config.OIDC_JWKS_URL,
                        cache_jwk_set=True,
                        cache_lifetime=config.OIDC_JWKS_CACHE_TTL,
                    )
                    self._jwks_url_cached = config.OIDC_JWKS_URL

                signing_key = self._jwks_client.get_signing_key_from_jwt(token)

                kwargs = {
                    "algorithms": ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                    "leeway": 10,  # [Hardening] Allow minor clock desynchronization skew
                }
                if config.OIDC_AUDIENCE:
                    kwargs["audience"] = config.OIDC_AUDIENCE
                if config.OIDC_ISSUER:
                    kwargs["issuer"] = config.OIDC_ISSUER

                payload = jwt.decode(token, signing_key.key, **kwargs)

                permissions = payload.get("permissions", [])
                if isinstance(permissions, str):
                    permissions = permissions.split()
                if not permissions:
                    roles = payload.get("roles", [])
                    if isinstance(roles, str):
                        roles = [roles]
                    if "admin" in roles or "system-admin" in roles:
                        permissions = Permission.ADMIN()
                    else:
                        scope = payload.get("scope", "")
                        if scope:
                            permissions = scope.split(" ")

                user = {
                    "id": payload.get("sub", "unknown-oidc-user"),
                    "email": payload.get("email", ""),
                    "name": payload.get("name", payload.get("preferred_username", "OIDC User")),
                    "permissions": permissions,
                    "type": "oidc-sso",
                }
                # These are normalized from the verified OIDC payload so
                # downstream extension handoffs can retain tenant context.
                if "roles" in payload:
                    user["roles"] = roles if "roles" in locals() else payload["roles"]
                for claim in ("org_id", "tenant_id", "workspace_id"):
                    if claim in payload:
                        user[claim] = payload[claim]
                environment = payload.get("active_environment", payload.get("environment"))
                if environment is not None:
                    user["active_environment"] = environment
                for claim in ("context_version", "context", "authorized_contexts"):
                    if claim in payload:
                        user[claim] = payload[claim]
                return user
            except Exception as e:
                if os.getenv("DEBUG", "false").lower() == "true":
                    print(f"   [Auth] JWT Verification failed: {e}")
                return None

        return self.authenticate(token)

    def has_permission(self, user: dict, permission_node: str) -> bool:
        """Strict PBAC implementation: Verifies granular permissions node."""
        user_perms = user.get("permissions", [])
        if "*" in user_perms or permission_node in user_perms:
            return True
        principal = AuthPrincipal(principal_id=user.get("id", "unknown"), permissions=user_perms)
        result = self.backend.check_permission(principal, permission_node, "")
        if not result and os.getenv("DEBUG", "false").lower() == "true":
            print(f"   [Auth] [DENIED] Node '{permission_node}' not in user perms: {user_perms}")
        return result

    def get_service_credential(self) -> str | None:
        """
        Resolves a machine credential for server-to-server operations.
        Prioritizes the configured backend before static key fallback.
        """
        if self._uses_configured_backend and hasattr(self.backend, "get_service_credential"):
            cred = self.backend.get_service_credential()
            if cred:
                return cred
        from .. import config

        return (
            self.key
            or os.getenv("SERVICE_API_KEY")
            or getattr(config, "SERVICE_API_KEY", None)
            or os.getenv("DASHBOARD_API_KEY")
            or getattr(config, "DASHBOARD_API_KEY", None)
            or None
        )


_configured_authorization_backend: AuthorizationBackend | None = None
_AUTHORIZATION_BACKEND_FACTORY_ENV = "AGENTV_AUTHORIZATION_BACKEND_FACTORY"


def register_authorization_backend(backend: AuthorizationBackend | None) -> None:
    """Explicit bootstrap seam for a configured non-OIDC authorization backend."""
    global _configured_authorization_backend
    _configured_authorization_backend = backend


def has_configured_authorization_backend() -> bool:
    """Returns True if a non-default authorization backend has been registered or configured."""
    return _configured_authorization_backend is not None or bool(
        os.getenv(_AUTHORIZATION_BACKEND_FACTORY_ENV, "").strip()
    )


def _load_configured_authorization_backend(factory_spec: str) -> AuthorizationBackend:
    """Load a deployment-configured backend factory without accepting request input."""
    module_name, separator, factory_name = factory_spec.rpartition(":")
    if not separator or not module_name or not factory_name:
        raise RuntimeError(f"{_AUTHORIZATION_BACKEND_FACTORY_ENV} must be 'package.module:factory'")
    try:
        module = importlib.import_module(module_name)
        factory = getattr(module, factory_name)
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            f"Unable to load {_AUTHORIZATION_BACKEND_FACTORY_ENV}={factory_spec!r}"
        ) from exc
    if not callable(factory):
        raise RuntimeError(
            f"{_AUTHORIZATION_BACKEND_FACTORY_ENV} factory {factory_spec!r} is not callable"
        )
    try:
        backend = factory()
    except TypeError as exc:
        raise RuntimeError(
            f"{_AUTHORIZATION_BACKEND_FACTORY_ENV} factory must be callable with no arguments"
        ) from exc
    if not isinstance(backend, AuthorizationBackend):
        raise RuntimeError(
            f"{_AUTHORIZATION_BACKEND_FACTORY_ENV} factory must return an AuthorizationBackend"
        )
    return backend


def get_auth_provider() -> AuthManager:
    """Factory method to retrieve the active Auth Provider."""
    from .. import config

    # Ensure environment is loaded for the API key
    # Industrial Hardening: Prefer dedicated SERVICE_API_KEY for programmatic access
    backend = _configured_authorization_backend
    if backend is None:
        factory_spec = os.getenv(_AUTHORIZATION_BACKEND_FACTORY_ENV, "").strip()
        if factory_spec:
            backend = _load_configured_authorization_backend(factory_spec)
    return StaticKeyProvider(config.SERVICE_API_KEY, backend=backend)


def extract_credentials_from_context(headers: dict, args: dict) -> tuple[str | None, str | None]:
    """
    Extracts Bearer token and/or API Key from headers and query parameters.
    Returns (bearer_token, api_key).
    """

    # Case-insensitive header helper
    def get_header(name: str) -> str | None:
        name_lower = name.lower()
        for k, v in headers.items():
            if k.lower() == name_lower:
                return v
        return None

    auth_header = get_header("Authorization")
    bearer_token = None
    if auth_header and auth_header.startswith("Bearer "):
        bearer_token = auth_header[7:].strip()

    api_key = get_header("X-AES-API-KEY") or get_header("X-API-Key") or args.get("apiKey")
    if api_key:
        api_key = api_key.strip()

    return bearer_token, api_key


def require_permission(permission_node: str):
    """
    Unified decorator for Session-based (Browser) and Header-based (CLI) Auth.
    Supports granular permission nodes via Strict PBAC logic.
    """
    from functools import wraps

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            import os

            from flask import jsonify, request, session

            # [TEST HARNESS SEAM] Explicit opt-in bypass for deterministic test
            # suites. Never set in production: authorization remains deny-by-
            # default (no implicit localhost/demo trust).
            if os.getenv("AGENTV_TEST_AUTH_BYPASS") == "1":
                return f(*args, **kwargs)

            # [INDUSTRIAL DIAGNOSTIC]: Log all permission checks for forensic auditing
            print(
                f"   [Auth] Checking permission '{permission_node}' for path: {request.path}",
                flush=True,
            )
            provider = get_auth_provider()
            user = session.get("user")

            def bind_verified_scope(principal: dict) -> bool:
                """Bind only provider/session context for downstream data routes."""
                from flask import g

                try:
                    normalized = normalize_entitlements(principal)
                except ValueError:
                    return False
                g.verified_principal = normalized
                g.runtime_context = normalized.get("context")
                return True

            # NOTE: No implicit localhost trust, even in demo mode.
            # All API access — including local developer setups — requires a valid
            # session or bearer token. Set DASHBOARD_API_KEY for local development.
            # This block intentionally left without a localhost shortcut.

            # 1. Check Session (Browser UI)
            if user:
                if not bind_verified_scope(user):
                    return jsonify({"error": "Invalid configured principal entitlements"}), 403
                if provider.has_permission(user, permission_node):
                    return f(*args, **kwargs)
                return jsonify(
                    {"error": f"Forbidden: Permission '{permission_node}' required"}
                ), 403

            # 2. Check Header or Query (CLI / Debug Support)
            bearer_token, api_key = extract_credentials_from_context(
                dict(request.headers), dict(request.args)
            )

            if bearer_token:
                user = provider.verify_token(bearer_token)
                if user:
                    if not bind_verified_scope(user):
                        return jsonify({"error": "Invalid configured principal entitlements"}), 403
                    if provider.has_permission(user, permission_node):
                        return f(*args, **kwargs)
                    return jsonify(
                        {"error": f"Forbidden: Permission '{permission_node}' required"}
                    ), 403

            elif api_key:
                user = provider.authenticate(api_key)
                if user:
                    if not bind_verified_scope(user):
                        return jsonify({"error": "Invalid configured principal entitlements"}), 403
                    if provider.has_permission(user, permission_node):
                        return f(*args, **kwargs)
                    return jsonify(
                        {"error": f"Forbidden: Permission '{permission_node}' required"}
                    ), 403

            if not bearer_token and not api_key and not user:
                print(
                    f"   [Auth] 401 Unauthorized - No session and no key "
                    f"(Node: {permission_node}, Path: {request.path})",
                    flush=True,
                )
            elif api_key and not user:
                # Safe Diagnostic: log the length and a hint of the key (first 4 chars)
                key_hint = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
                print(
                    f"   [Auth] 401 Unauthorized - Invalid key: {key_hint} "
                    f"(Len: {len(api_key)}) for {request.path}",
                    flush=True,
                )
            else:
                print(
                    f"   [Auth] 401 Unauthorized - Invalid Bearer Token for {request.path}",
                    flush=True,
                )

            return jsonify({"error": "Unauthorized: Invalid or missing API Key"}), 401

        return decorated_function

    return decorator


def active_runtime_context() -> dict[str, str] | None:
    """Return the request-bound verified context, never request presentation data."""
    from flask import g

    context = getattr(g, "runtime_context", None)
    return dict(context) if isinstance(context, dict) else None


def context_allows_record(record: dict, context: dict[str, str] | None) -> bool:
    """Non-enumerating scope test for a stored Runtime object.

    Records without scope are available only to unscoped legacy service
    principals. A scoped principal never receives a record whose declared
    tuple differs or is absent.
    """
    if context is None:
        return True
    source = record.get("context") if isinstance(record.get("context"), dict) else record
    metadata = record.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("runtime_context"), dict):
        source = metadata["runtime_context"]
    return all(source.get(field) == context[field] for field in CONTEXT_FIELDS)


def require_sse_permission(permission_node: str):
    """Authorize an SSE route without accepting credentials or tenant scope in its URL.

    Same-origin ``EventSource`` reconnects authenticate through the HttpOnly
    Console session cookie.  Non-browser clients may use normal headers, but
    URL credentials and presentation tenant context are categorically refused.
    ``Last-Event-ID`` remains the replay authority.
    """

    from functools import wraps

    from flask import jsonify, request

    forbidden_query_keys = {
        "token",
        "access_token",
        "authorization",
        "apiKey",
        "api_key",
        "tenant_id",
        "org_id",
        "workspace_id",
        "active_environment",
        "environment",
    }

    def decorator(f):
        @wraps(f)
        @require_permission(permission_node)
        def decorated_function(*args, **kwargs):
            if forbidden_query_keys.intersection(request.args.keys()):
                return jsonify(
                    {"error": "SSE credentials and tenant context must not be sent in the URL"}
                ), 400
            return f(*args, **kwargs)

        return decorated_function

    return decorator
