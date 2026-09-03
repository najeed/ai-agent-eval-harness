import datetime
import functools
import logging
import os
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
    env = os.environ.get("AGENTV_ENV", "").strip().lower()
    if env in ("production", "prod"):
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


SECRET_KEY = get_jwt_secret()


def generate_handoff_token(
    sub: str = "admin-user",
    plugin_id: str = "control-plane",
    audience: str = "agentv-plugin",
    expires_in_seconds: int = 900,
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
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def handoff_required(f: Any) -> Any:
    """
    Route decorator that enforces a valid audience-bound handoff token on any
    route it protects.

    Usage (extension / enterprise control-plane routes):
        @app.route("/my-extension/secure-endpoint")
        @handoff_required
        def my_endpoint():
            ...

    Accepts the token via:
      - Query parameter:  ``?token=<jwt>``
      - Request header:   ``X-Handoff-Token: <jwt>``

    Validates audience (``agentv-plugin``), signature, and expiration against
    the same ``JWT_SECRET`` used by ``generate_handoff_token``.

    This decorator is part of the published AgentV extension API contract
    (see AUTHENTICATION.md § 4).  It is intentionally provided by the OSS
    runtime for extensions to consume on their own routes; OSS-internal routes
    do not use it because the OSS layer does not host extension-owned endpoints.
    """

    @functools.wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        token = request.args.get("token") or request.headers.get("X-Handoff-Token")

        if not token:
            return jsonify({"error": "Handoff token required"}), 401

        try:
            jwt.decode(
                token,
                get_jwt_secret(),
                algorithms=["HS256"],
                audience="agentv-plugin",
            )
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError as e:
            return jsonify({"error": f"Invalid token: {e}"}), 401

        return f(*args, **kwargs)

    return decorated


@auth_bp.route("/handoff", methods=["GET"])
def get_handoff_token():
    """
    Endpoint for plugin/extension runtime handoff.
    Issues short-lived audience-bound token with explicit plugin identity.
    """
    user = session.get("user") or {}
    sub = user.get("id", "admin-user")
    plugin_id = request.args.get("plugin_id", "control-plane")
    token = generate_handoff_token(sub=sub, plugin_id=plugin_id)
    return jsonify({"token": token, "expires_in": 900, "audience": "agentv-plugin"})


@auth_bp.route("/me", methods=["GET"])
def get_current_user():
    """
    Returns the server-authoritative authenticated identity, role,
    and granular permissions for the active session.
    """
    from .auth_manager import Permission, get_auth_provider

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
            "workspace_id": "ws-default",
        }

    if not user:
        return jsonify(
            {
                "authenticated": False,
                "user": None,
                "is_dev_mode": is_dev_mode,
            }
        ), 200

    perms = user.get("permissions", [])
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
            "user": {
                "id": user.get("id", "user"),
                "name": user.get("name", "Authenticated User"),
                "role": role,
                "permissions": perms,
                "type": user.get("type", "session"),
                "workspace_id": user.get("workspace_id", "ws-default"),
                "is_dev_mode": is_dev_mode,
            },
        }
    )


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Terminates the active session and clears authentication cookies."""
    session.clear()
    return jsonify({"status": "success", "message": "Logged out successfully"})


@auth_bp.route("/login", methods=["POST"], strict_slashes=False)
def login():
    """Standard PBAC Login Gate for the Visual Suite."""
    from .auth_manager import Permission, get_auth_provider

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

    # Successful authentication resets failed attempts counter
    with _LOGIN_ATTEMPT_LOCK:
        _FAILED_LOGIN_ATTEMPTS.pop(ip, None)

    perms = user.get("permissions", [])
    role = (
        "System Admin"
        if ("*" in perms or set(Permission.ADMIN()).issubset(set(perms)))
        else "MultiAgentOps Eng."
    )
    user["role"] = role
    user["workspace_id"] = data.get("workspace_id", "ws-default")

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
                "workspace_id": user["workspace_id"],
            },
        }
    )
