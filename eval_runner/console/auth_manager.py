import os
from abc import ABC, abstractmethod


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
            cls.SCENARIOS_WRITE,
            cls.SCENARIOS_DELETE,
            cls.DEBUG_RESET,
            cls.SYSTEM_CONFIG,
        ]


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


class StaticKeyProvider(AuthManager):
    """Default OSS provider: Single Master/Root Key maps to explicit granular nodes."""

    def __init__(self, key: str):
        self.key = key
        self._jwks_client = None
        self._jwks_url_cached = None

    def authenticate(self, credentials: str) -> dict | None:
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
                if not permissions:
                    roles = payload.get("roles", [])
                    if "admin" in roles or "system-admin" in roles:
                        permissions = Permission.ADMIN()
                    else:
                        scope = payload.get("scope", "")
                        if scope:
                            permissions = scope.split(" ")

                return {
                    "id": payload.get("sub", "unknown-oidc-user"),
                    "email": payload.get("email", ""),
                    "name": payload.get("name", payload.get("preferred_username", "OIDC User")),
                    "permissions": permissions,
                    "type": "oidc-sso",
                }
            except Exception as e:
                if os.getenv("DEBUG", "false").lower() == "true":
                    print(f"   [Auth] JWT Verification failed: {e}")
                return None

        return self.authenticate(token)

    def has_permission(self, user: dict, permission_node: str) -> bool:
        """Strict PBAC implementation: Verifies granular permissions node."""
        user_perms = user.get("permissions", [])
        # Equality check (No wildcards or role logic)
        result = permission_node in user_perms
        if not result and os.getenv("DEBUG", "false").lower() == "true":
            print(f"   [Auth] [DENIED] Node '{permission_node}' not in user perms: {user_perms}")
        return result


def get_auth_provider() -> AuthManager:
    """Factory method to retrieve the active Auth Provider."""
    from .. import config

    # Ensure environment is loaded for the API key
    # Industrial Hardening: Prefer dedicated SERVICE_API_KEY for programmatic access
    return StaticKeyProvider(config.SERVICE_API_KEY)


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
            from flask import current_app, jsonify, request, session

            from .. import config

            # [INDUSTRIAL DIAGNOSTIC]: Log all permission checks for forensic auditing
            print(
                f"   [Auth] Checking permission '{permission_node}' for path: {request.path}",
                flush=True,
            )
            provider = get_auth_provider()
            user = session.get("user")

            # --- INDUSTRIAL DEMO HARNESS (Local Trust v1.6.0) ---
            # [HARDENING] Skip Local Trust if we are running in a TEST environment (AgentV v1.6.0)
            is_testing = current_app.config.get("TESTING", False)

            if (
                not user
                and not is_testing
                and config.ENABLE_DEMO
                and (request.remote_addr == "127.0.0.1" or request.remote_addr == "::1")
            ):
                # Staff Engineer Decision: Inherit system identity for
                # local demonstrative execution.
                user = {
                    "id": "industrial-integrator@harness.io",
                    "email": "industrial-integrator@harness.io",
                    "name": "Local Integrator",
                    "permissions": Permission.ADMIN(),
                    "type": "local-trust",
                }
                session["user"] = user
                print(f"   [Auth] Local Trust inherited for: {request.remote_addr}", flush=True)

            # 1. Check Session (Browser UI)
            if user:
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
                    if provider.has_permission(user, permission_node):
                        return f(*args, **kwargs)
                    return jsonify(
                        {"error": f"Forbidden: Permission '{permission_node}' required"}
                    ), 403

            elif api_key:
                user = provider.authenticate(api_key)
                if user:
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
            elif bearer_token and not user:
                print(
                    f"   [Auth] 401 Unauthorized - Invalid Bearer Token for {request.path}",
                    flush=True,
                )

            return jsonify({"error": "Unauthorized: Invalid or missing API Key"}), 401

        return decorated_function

    return decorator
