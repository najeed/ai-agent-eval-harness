import os
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Union

class Role:
    """
    Standard Permission Nodes for the AES Evaluation Harness.
    Enterprise plugins can define custom strings (e.g., "billing:admin").
    """
    # Read-Only Nodes
    SCENARIOS_READ = "scenarios:read"
    RUNS_READ      = "runs:read"
    DOCS_READ      = "docs:read"
    DEBUG_READ     = "debugger:read"

    # Operator Nodes (Execution)
    EVAL_TRIGGER   = "eval:trigger"
    DEMO_EXECUTE   = "demo:execute"
    INDEX_REFRESH  = "index:refresh"
    DEBUG_EVENT    = "debugger:event"

    # Admin Nodes (Destructive / Config)
    SCENARIOS_WRITE  = "scenarios:write"
    SCENARIOS_DELETE = "scenarios:delete"
    DEBUG_RESET      = "debugger:reset"
    SYSTEM_CONFIG    = "system:config"

    # Legacy Compatibility Aliases (Standard Archetypes)
    @classmethod
    def READER(cls) -> List[str]:
        return [cls.SCENARIOS_READ, cls.RUNS_READ, cls.DOCS_READ, cls.DEBUG_READ]

    @classmethod
    def OPERATOR(cls) -> List[str]:
        return cls.READER() + [cls.EVAL_TRIGGER, cls.DEMO_EXECUTE, cls.INDEX_REFRESH, cls.DEBUG_EVENT]

    @classmethod
    def ADMIN(cls) -> List[str]:
        return cls.OPERATOR() + [cls.SCENARIOS_WRITE, cls.SCENARIOS_DELETE, cls.DEBUG_RESET, cls.SYSTEM_CONFIG]

class AuthManager(ABC):
    """Base interface for authentication and PBAC integration."""
    
    @abstractmethod
    def authenticate(self, credentials: str) -> Optional[Dict]:
        """Verify credentials and return a user profile (id, name, roles, permissions)."""
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
            "roles": ["admin"],
            "permissions": Role.ADMIN(),
            "type": "static-root"
        }

    def has_permission(self, user: Dict, permission_node: str) -> bool:
        # Static Root Key always has all permissions
        # In PBAC, we check if the requested node is in the user's permission list
        user_perms = user.get("permissions", [])
        return permission_node in user_perms or "admin" in user.get("roles", [])

def get_auth_provider() -> AuthManager:
    """Factory method to retrieve the active Auth Provider."""
    from .. import config
    return StaticKeyProvider(config.DASHBOARD_API_KEY)

def require_permission(permission_node: str):
    """
    Unified decorator for Session-based (Browser) and Header-based (CLI) Auth.
    Supports granular permission nodes.
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
            api_key = request.headers.get("X-AES-API-KEY")
            if api_key:
                user = provider.authenticate(api_key)
                if user:
                    if provider.has_permission(user, permission_node):
                        return f(*args, **kwargs)
                    return jsonify({"error": f"Forbidden: Permission '{permission_node}' required"}), 403
            
            return jsonify({"error": "Unauthorized: Invalid or missing API Key"}), 401
        return decorated_function
    return decorator
