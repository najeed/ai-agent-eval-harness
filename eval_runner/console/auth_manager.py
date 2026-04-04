import os
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Union

class Permission:
    """
    Standard Granular Permission Nodes for the AES Evaluation Harness (Strict PBAC).
    Enterprise plugins can define custom strings (e.g., "billing:admin").
    """
    # 1. Read-Only Nodes
    SCENARIOS_READ = "scenarios:read"
    RUNS_READ      = "runs:read"
    DOCS_READ      = "docs:read"
    DEBUG_READ     = "debugger:read"

    # 2. Operator Nodes (Execution)
    EVAL_TRIGGER   = "eval:trigger"
    DEMO_EXECUTE   = "demo:execute"
    INDEX_REFRESH  = "index:refresh"
    DEBUG_EVENT    = "debugger:event"

    # 3. Admin Nodes (Destructive / Config)
    SCENARIOS_WRITE  = "scenarios:write"
    SCENARIOS_DELETE = "scenarios:delete"
    DEBUG_RESET      = "debugger:reset"
    SYSTEM_CONFIG    = "system:config"

    # PBAC Collections (Standard Profiles)
    @classmethod
    def ALL_READ(cls) -> List[str]:
        return [cls.SCENARIOS_READ, cls.RUNS_READ, cls.DOCS_READ, cls.DEBUG_READ]

    @classmethod
    def OPERATOR(cls) -> List[str]:
        return cls.ALL_READ() + [cls.EVAL_TRIGGER, cls.DEMO_EXECUTE, cls.INDEX_REFRESH, cls.DEBUG_EVENT]

    @classmethod
    def ADMIN(cls) -> List[str]:
        return cls.OPERATOR() + [cls.SCENARIOS_WRITE, cls.SCENARIOS_DELETE, cls.DEBUG_RESET, cls.SYSTEM_CONFIG]

class AuthManager(ABC):
    """Base interface for authentication and PBAC integration."""
    
    @abstractmethod
    def authenticate(self, credentials: str) -> Optional[Dict]:
        """Verify credentials and return a user profile (id, name, permissions)."""
        pass

    @abstractmethod
    def has_permission(self, user: Dict, permission_node: str) -> bool:
        """Check if a user has the required granular permission node."""
        pass

class StaticKeyProvider(AuthManager):
    """Default OSS provider: Single Master/Root Key maps to full ADMIN suite."""
    
    def __init__(self, key: str):
        self.key = key

    def authenticate(self, credentials: str) -> Optional[Dict]:
        if not self.key or credentials != self.key:
            return None
            
        return {
            "id": "root-admin",
            "name": "System Administrator",
            "permissions": Permission.ADMIN(),
            "type": "static-root"
        }

    def has_permission(self, user: Dict, permission_node: str) -> bool:
        """Strict PBAC implementation: Verifies granular permissions node without RBAC fallback."""
        user_perms = user.get("permissions", [])
        # Authoritative PBAC check
        return permission_node in user_perms

def get_auth_provider() -> AuthManager:
    """Factory method to retrieve the active Auth Provider."""
    from .. import config
    # Ensure environment is loaded for the API key
    return StaticKeyProvider(config.DASHBOARD_API_KEY)

def require_permission(permission_node: str):
    """
    Unified decorator for Session-based (Browser) and Header-based (CLI) Auth.
    Supports granular permission nodes via Strict PBAC logic.
    """
    from flask import request, session, jsonify
    from functools import wraps
    
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            provider = get_auth_provider()
            user = session.get("user")
            
            # 1. Check Session (Browser UI)
            if user:
                if provider.has_permission(user, permission_node):
                    return f(*args, **kwargs)
                return jsonify({"error": f"Forbidden: Permission '{permission_node}' required"}), 403
            
            # 2. Check Header (CLI / Programmatic)
            api_key = request.headers.get("X-AES-API-KEY") or request.headers.get("X-API-Key")
            
            if api_key:
                user = provider.authenticate(api_key)
                if user:
                    if provider.has_permission(user, permission_node):
                        return f(*args, **kwargs)
                    return jsonify({"error": f"Forbidden: Permission '{permission_node}' required"}), 403
            
            if not api_key and not user:
                print(f"   [Auth] 401 Unauthorized - No session and no X-AES-API-KEY header (Path: {request.path})", flush=True)
            elif api_key and not user:
                print(f"   [Auth] 401 Unauthorized - Invalid API Key provided (Path: {request.path})", flush=True)

            return jsonify({"error": "Unauthorized: Invalid or missing API Key"}), 401
        return decorated_function
    return decorator
