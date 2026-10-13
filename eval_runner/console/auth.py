import datetime
import functools
import logging
import os
import re
import secrets
import threading
import time
from datetime import UTC
from typing import Any

import jwt
from flask import Blueprint, jsonify, request, session

from eval_runner import config

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

HANDOFF_PRINCIPAL_CLAIMS = (
    "context_version",
    "context",
    "authorized_contexts",
    "email",
    "roles",
    "permissions",
    "org_id",
    "tenant_id",
    "workspace_id",
    "active_environment",
)
CONTEXT_CLAIMS = ("org_id", "tenant_id", "workspace_id", "active_environment")
_REVOKED_HANDOFF_JTIS: set[str] = set()

# Sliding-window rate limiting for /api/auth/login (S1 DevSecOps Hardening)
_FAILED_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_ATTEMPT_LOCK = threading.Lock()
LOGIN_RATE_LIMIT_MAX = 10
LOGIN_RATE_LIMIT_WINDOW = 60.0  # 10 failed attempts per 60 seconds

# Dynamic Secret Resolution: Use configured secret, service key hash, or ephemeral secret
_EPHEMERAL_SECRET = secrets.token_hex(32)


def get_jwt_secret() -> str:
    """Returns the authoritative secret for console handoff and internal token signing."""
    configured = getattr(config, "JWT_SECRET", None) or os.environ.get("JWT_SECRET")
    if configured:
        return configured
    if getattr(config, "DASHBOARD_API_KEY", None):
        return config.DASHBOARD_API_KEY
    if getattr(config, "SERVICE_API_KEY", None):
        return config.SERVICE_API_KEY

    # A per-process ephemeral secret silently breaks JWT validation and
    # Flask sessions across worker processes/replicas. Fail loud in production;
    # warn clearly everywhere else.
    if config.is_production():
        raise RuntimeError(
            "AGENTV_ENV=production requires a stable signing secret: set "
            "JWT_SECRET or DASHBOARD_API_KEY. A per-process ephemeral secret "
            "breaks multi-worker deployments (tokens issued by one worker fail "
            "validation on another)."
        )
    logger.warning(
        "JWT secret falling back to a per-process EPHEMERAL value. Sessions "
        "and handoff tokens will NOT validate across worker processes or "
        "replicas. Set JWT_SECRET (or DASHBOARD_API_KEY) for any "
        "multi-process deployment."
    )
    return _EPHEMERAL_SECRET


def __getattr__(name: str) -> Any:
    """Dynamic module attribute accessor for backward-compatible SECRET_KEY resolution."""
    if name == "SECRET_KEY":
        return get_jwt_secret()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def generate_handoff_token(
    sub: str = "admin-user",
    plugin_id: str = "control-plane",
    audience: str = "agentv-plugin",
    expires_in_seconds: int = 900,
    **principal_claims: Any,
) -> str:
    """
    Generates a cryptographically signed, short-lived, audience-bound JWT
    for frontend-to-plugin and micro-frontend handoff.
    """
    now = datetime.datetime.now(UTC)
    payload = {
        "exp": now + datetime.timedelta(seconds=expires_in_seconds),
        "iat": now,
        "sub": sub,
        "aud": audience,
        "plugin_id": plugin_id,
        "scope": "console-handoff",
        "jti": secrets.token_hex(16),
    }
    # Handoff tokens deliberately have a narrow, stable principal schema.
    # Callers cannot smuggle unrelated request data into an extension token.
    for claim in HANDOFF_PRINCIPAL_CLAIMS:
        value = principal_claims.get(claim)
        if value is not None:
            payload[claim] = value
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def handoff_required(
    f: Any = None,
    *,
    plugin_id: str | None = None,
    scope: str | None = None,
) -> Any:
    """
    Route decorator that enforces a valid audience-bound handoff token on any
    route it protects.

    Accepts the token via:
      - Request header:   ``X-Handoff-Token: <jwt>`` or ``Authorization: Bearer <jwt>``
      - Query parameter:  ``?token=<jwt>`` (development/non-production only)

    Validates audience (``agentv-plugin``), signature, expiration, scope, and plugin binding.
    """

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        def decorated(*args: Any, **kwargs: Any) -> Any:
            is_prod = config.is_production()

            token = request.headers.get("X-Handoff-Token")
            if not token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:].strip()

            query_token = request.args.get("token")
            if query_token:
                if is_prod:
                    return (
                        jsonify(
                            {
                                "error": (
                                    "Forbidden: Query parameter tokens are disabled in production. "
                                    "Use 'X-Handoff-Token' header."
                                )
                            }
                        ),
                        400,
                    )
                if not token:
                    token = query_token

            if not token:
                return jsonify({"error": "Handoff token required"}), 401

            try:
                decoded = jwt.decode(
                    token,
                    get_jwt_secret(),
                    algorithms=["HS256"],
                    audience="agentv-plugin",
                )
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "Token expired"}), 401
            except jwt.InvalidTokenError as e:
                return jsonify({"error": f"Invalid token: {e}"}), 401
            if decoded.get("jti") in _REVOKED_HANDOFF_JTIS:
                return jsonify({"error": "Token revoked"}), 401

            # Validate scope binding
            token_scope = decoded.get("scope")
            expected_scope = scope or "console-handoff"
            if token_scope != expected_scope:
                return (
                    jsonify(
                        {
                            "error": (
                                f"Invalid token scope: expected '{expected_scope}', "
                                f"got '{token_scope}'"
                            )
                        }
                    ),
                    403,
                )

            # Validate plugin binding if required by decorator
            if plugin_id is not None:
                token_plugin_id = decoded.get("plugin_id")
                if token_plugin_id != plugin_id:
                    return (
                        jsonify(
                            {
                                "error": (
                                    f"PluginIdMismatch: token issued for plugin "
                                    f"'{token_plugin_id}', cannot access endpoint for "
                                    f"plugin '{plugin_id}'"
                                )
                            }
                        ),
                        403,
                    )

            return func(*args, **kwargs)

        return decorated

    if f is not None and callable(f):
        return decorator(f)
    return decorator


@auth_bp.route("/handoff", methods=["GET", "POST"])
def get_handoff_token():
    """
    Endpoint for plugin/extension runtime handoff.
    Requires authenticated operator with EXTENSIONS_RUN permission.
    Issues short-lived audience-bound token with explicit plugin identity.
    """
    is_prod = config.is_production()
    if is_prod and request.method != "POST":
        return (
            jsonify(
                {
                    "error": (
                        "Method Not Allowed: POST required for handoff token issuance in production"
                    )
                }
            ),
            405,
        )

    from .auth_manager import (
        Permission,
        extract_credentials_from_context,
        get_auth_provider,
        normalize_entitlements,
    )

    provider = get_auth_provider()
    user = session.get("user")
    if not user:
        bearer_token, api_key = extract_credentials_from_context(
            dict(request.headers), dict(request.args)
        )
        if bearer_token:
            user = provider.verify_token(bearer_token)
        elif api_key:
            user = provider.authenticate(api_key)

    if not user:
        return jsonify(
            {"error": "Unauthorized: authenticated operator session or API key required"}
        ), 401
    try:
        user = normalize_entitlements(user)
    except ValueError:
        return jsonify({"error": "Invalid configured principal entitlements"}), 403

    if not provider.has_permission(user, Permission.EXTENSIONS_RUN):
        return jsonify(
            {"error": f"Forbidden: Permission '{Permission.EXTENSIONS_RUN}' required"}
        ), 403

    payload_data = request.get_json(silent=True) or {}
    plugin_id = payload_data.get("plugin_id") or request.args.get("plugin_id", "control-plane")
    if (
        not plugin_id
        or not isinstance(plugin_id, str)
        or not re.match(r"^[a-zA-Z0-9_\-]+$", plugin_id)
    ):
        return jsonify(
            {"error": "Invalid plugin_id format: alphanumeric, underscore, hyphen only"}
        ), 400

    sub = user.get("id") or "authenticated-user"
    principal_claims = {
        claim: user[claim] for claim in HANDOFF_PRINCIPAL_CLAIMS if user.get(claim) is not None
    }
    token = generate_handoff_token(sub=sub, plugin_id=plugin_id, **principal_claims)
    decoded = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"], audience="agentv-plugin")
    session.setdefault("handoff_jtis", []).append(decoded["jti"])
    return jsonify(
        {
            "token": token,
            "expires_in": 900,
            "audience": "agentv-plugin",
            "plugin_id": plugin_id,
            "principal": sub,
        }
    )


@auth_bp.route("/me", methods=["GET"])
def get_current_user():
    """
    Returns the server-authoritative authenticated identity, role,
    and granular permissions for the active session.
    """
    from .auth_manager import Permission, get_auth_provider, normalize_entitlements

    provider = get_auth_provider()
    user = session.get("user")

    is_dev_mode = bool(
        getattr(config, "ENABLE_DEMO", False)
        or os.environ.get("DEV_PERSONA_SIMULATOR", "").lower() == "true"
    )

    if not user:
        # Check Authorization header (Bearer / API key)
        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-AES-API-KEY") or request.headers.get("X-API-Key")
        if auth_header.startswith("Bearer "):
            user = provider.verify_token(auth_header[7:].strip())
        elif api_key_header:
            user = provider.authenticate(api_key_header.strip())

    is_explicit_dev = os.getenv("AGENTV_ENV", "").lower() in ("dev", "development") or is_dev_mode
    is_loopback = request.remote_addr in ("127.0.0.1", "::1", "localhost") or (
        request.remote_addr is None and os.getenv("AGENTV_TEST_AUTH_BYPASS") == "1"
    )

    if not user and is_explicit_dev and is_loopback:
        # Local development persona default
        user = {
            "id": "dev-admin@agentv.local",
            "name": "Local Dev Admin",
            "role": "System Admin",
            "permissions": Permission.ADMIN(),
            "type": "local-dev",
        }

    if not user:
        return jsonify(
            {
                "authenticated": False,
                "user": None,
                "is_dev_mode": is_dev_mode,
            }
        ), 200
    try:
        user = normalize_entitlements(user)
    except ValueError:
        return jsonify(
            {
                "authenticated": False,
                "user": None,
                "error": "Invalid configured principal entitlements",
            }
        ), 403

    perms = user.get("permissions", [])
    if isinstance(perms, str):
        perms = perms.split()
    roles = user.get("roles", [])
    if isinstance(roles, str):
        roles = [roles]
    context = {claim: user.get(claim) for claim in CONTEXT_CLAIMS}
    # Infer standard role label from permissions if not explicitly stored
    role = user.get("role")
    if not role:
        if "*" in perms or set(Permission.ADMIN()).issubset(set(perms)):
            role = "System Admin"
        elif Permission.CERTIFY_WRITE in perms:
            role = "Compliance Auditor"
        elif Permission.SCENARIOS_WRITE in perms:
            role = "Scenario Designer"
        else:
            role = "MultiAgentOps Eng."

    return jsonify(
        {
            "authenticated": True,
            "context_version": user.get("context_version", "2"),
            "context": context,
            "authorized_contexts": user.get("authorized_contexts", []),
            "user": {
                "id": user.get("id", "user"),
                "email": user.get("email") or None,
                "name": user.get("name", "Authenticated User"),
                "role": role,
                "roles": roles,
                "permissions": perms,
                "type": user.get("type", "session"),
                **context,
                "is_dev_mode": is_dev_mode,
            },
        }
    )


@auth_bp.route("/context", methods=["POST"])
def switch_context():
    """Atomically select an already provider-authorized workspace/environment."""
    from .auth_manager import normalize_entitlements

    user = session.get("user")
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {"workspace_id", "active_environment"}:
        return jsonify({"error": "workspace_id and active_environment are required"}), 400
    workspace_id, environment = data["workspace_id"], data["active_environment"]
    if not isinstance(workspace_id, str) or not isinstance(environment, str):
        return jsonify({"error": "Invalid requested context"}), 400
    try:
        normalized = normalize_entitlements(user)
    except ValueError:
        return jsonify({"error": "Invalid configured principal entitlements"}), 403
    entry = next(
        (
            item
            for item in normalized["authorized_contexts"]
            if item["workspace_id"] == workspace_id and environment in item["environments"]
        ),
        None,
    )
    if entry is None:
        return jsonify({"error": "Requested context is not authorized"}), 403
    # No session mutation occurs until all validation succeeds.
    context = {key: entry[key] for key in CONTEXT_CLAIMS[:-1]}
    context["active_environment"] = environment
    normalized.update(context)
    normalized["context"] = context
    for jti in session.get("handoff_jtis", []):
        _REVOKED_HANDOFF_JTIS.add(jti)
    normalized["handoff_jtis"] = []
    session["user"] = normalized
    session["handoff_jtis"] = []
    return jsonify({"context_version": "2", "context": context})


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Terminates the active session and clears authentication cookies."""
    session.clear()
    return jsonify({"status": "success", "message": "Logged out successfully"})


@auth_bp.route("/login", methods=["POST"], strict_slashes=False)
def login():
    """Standard PBAC Login Gate for the Visual Suite."""
    from .auth_manager import Permission, get_auth_provider, normalize_entitlements

    ip = request.remote_addr or "127.0.0.1"
    now = time.time()

    with _LOGIN_ATTEMPT_LOCK:
        attempts = _FAILED_LOGIN_ATTEMPTS.get(ip, [])
        # Prune attempts outside the sliding window
        valid_attempts = [t for t in attempts if now - t < LOGIN_RATE_LIMIT_WINDOW]
        _FAILED_LOGIN_ATTEMPTS[ip] = valid_attempts

        if len(valid_attempts) >= LOGIN_RATE_LIMIT_MAX:
            retry_after = int(LOGIN_RATE_LIMIT_WINDOW - (now - valid_attempts[0]))
            return (
                jsonify(
                    {
                        "error": "Too many failed login attempts. Please wait before retrying.",
                        "retry_after_seconds": max(1, retry_after),
                    }
                ),
                429,
            )

    data = request.json or {}
    api_key = data.get("apiKey") or data.get("api_key") or data.get("key")

    if not api_key:
        return jsonify({"error": "Missing API Key"}), 400

    provider = get_auth_provider()
    user = provider.authenticate(api_key)

    if not user:
        with _LOGIN_ATTEMPT_LOCK:
            _FAILED_LOGIN_ATTEMPTS.setdefault(ip, []).append(now)
        return jsonify({"error": "Unauthorized: Invalid API Key"}), 401
    try:
        user = normalize_entitlements(user)
    except ValueError:
        return jsonify({"error": "Invalid configured principal entitlements"}), 403

    # Successful authentication resets failed attempts counter
    with _LOGIN_ATTEMPT_LOCK:
        _FAILED_LOGIN_ATTEMPTS.pop(ip, None)

    perms = user.get("permissions", [])
    # A verified identity provider may supply one of the Console's explicit
    # display roles (for example Clinical HITL Reviewer).  Preserve it; only
    # infer a label when the provider did not provide one.
    role = user.get("role") or (
        "System Admin"
        if ("*" in perms or set(Permission.ADMIN()).issubset(set(perms)))
        else "MultiAgentOps Eng."
    )
    user["role"] = role
    # Workspace scope must originate with the authenticated provider.  A login
    # request is not an authority to select or elevate tenant context.
    # Populate industrial-grade PBAC session
    session["user"] = user
    session.permanent = True

    return jsonify(
        {
            "status": "success",
            "message": "Authenticated successfully",
            "user": {
                "name": user["name"],
                "id": user["id"],
                "role": role,
                "permissions": user["permissions"],
                "workspace_id": user.get("workspace_id"),
            },
        }
    )
