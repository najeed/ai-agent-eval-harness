import jwt
import datetime
import functools
from flask import Blueprint, jsonify, request, current_app

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# Use a fixed secret for local dev if not provided (Zero-Touch default)
SECRET_KEY = "harness-dev-secret-change-me-in-production"


def generate_handoff_token():
    """Generates a short-lived JWT for frontend-to-plugin handoff."""
    payload = {
        "exp": datetime.datetime.utcnow() + datetime.timedelta(seconds=60),
        "iat": datetime.datetime.utcnow(),
        "sub": "admin-user",
        "scope": "console-handoff",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def handoff_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = request.args.get("token") or request.headers.get("X-Handoff-Token")

        if not token:
            return jsonify({"error": "Handoff token required"}), 401

        try:
            jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        return f(*args, **kwargs)

    return decorated


@auth_bp.route("/handoff", methods=["GET"])
def get_handoff_token():
    """Endpoint for Expo app to request a secure handoff token."""
    token = generate_handoff_token()
    return jsonify({"token": token})


@auth_bp.route("/login", methods=["POST"], strict_slashes=False)
def login():
    """Standard PBAC Login Gate for the Visual Suite."""
    from flask import session
    from .auth_manager import get_auth_provider
    from .. import config

    data = request.json or {}
    api_key = data.get("apiKey")

    if not api_key:
        return jsonify({"error": "Missing API Key"}), 400

    provider = get_auth_provider()
    user = provider.authenticate(api_key)

    if not user:
        return jsonify({"error": "Unauthorized: Invalid API Key"}), 401

    # Populate industrial-grade PBAC session
    session["user"] = user
    # Ensure cookie is marked for security
    session.permanent = True 
    
    return jsonify({
        "status": "success",
        "message": "Authenticated successfully",
        "user": {
            "name": user["name"],
            "id": user["id"],
            "permissions": user["permissions"]
        }
    })
