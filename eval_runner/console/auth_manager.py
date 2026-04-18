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
        """Authoritative set of all granular permission nodes (AgentV v1.5.0 Standard)."""
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
    def has_permission(self, user: dict, permission_node: str) -> bool:
        """Check if a user has the required granular permission node."""
        pass


class StaticKeyProvider(AuthManager):
    """Default OSS provider: Single Master/Root Key maps to explicit granular nodes."""

    def __init__(self, key: str):
        self.key = key

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


def require_permission(permission_node: str):
    """
    Unified decorator for Session-based (Browser) and Header-based (CLI) Auth.
    Supports granular permission nodes via Strict PBAC logic.
    """
    from functools import wraps

    from flask import jsonify, request, session

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # [INDUSTRIAL DIAGNOSTIC]: Log all permission checks for forensic auditing
            print(
                f"   [Auth] Checking permission '{permission_node}' for path: {request.path}",
                flush=True,
            )
            provider = get_auth_provider()
            user = session.get("user")

            # --- INDUSTRIAL DEMO HARNESS (Local Trust v1.4.1) ---
            from flask import current_app

            from .. import config

            # [HARDENING] Skip Local Trust if we are running in a TEST environment (AgentV v1.5.0)
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
            api_key = (
                request.headers.get("X-AES-API-KEY")
                or request.headers.get("X-API-Key")
                or request.args.get("apiKey")
            )

            if api_key:
                # [Hardening] Trim whitespace to prevent 401s from invisible formatting
                # in .env/headers
                api_key = api_key.strip()
                user = provider.authenticate(api_key)
                if user:
                    if provider.has_permission(user, permission_node):
                        return f(*args, **kwargs)
                    return jsonify(
                        {"error": f"Forbidden: Permission '{permission_node}' required"}
                    ), 403

            if not api_key and not user:
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

            return jsonify({"error": "Unauthorized: Invalid or missing API Key"}), 401

        return decorated_function

    return decorator
