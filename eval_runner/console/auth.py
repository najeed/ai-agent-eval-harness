import datetime
import functools
import logging
import os
import secrets
from datetime import UTC
from typing import Any

import jwt
from flask import Blueprint, jsonify, request, session

from eval_runner import config

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

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


def handoff_required(f):
    @functools.wraps(f)
    def decorated(*args: Any, **kwargs: Any):
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

    if not user and is_dev_mode and request.remote_addr in ("127.0.0.1", "::1"):
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

    data = request.json or {}
    api_key = data.get("apiKey") or data.get("api_key") or data.get("key")

    if not api_key:
        return jsonify({"error": "Missing API Key"}), 400

    provider = get_auth_provider()
    user = provider.authenticate(api_key)

    if not user:
        return jsonify({"error": "Unauthorized: Invalid API Key"}), 401

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
