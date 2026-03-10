"""
simulators.py

Standard simulation shims for common agent environments (Git, API).
"""

from typing import Any, Dict

class GitSimulator:
    """Simulates a Git repository state."""
    def __init__(self):
        self.state = {
            "current_branch": "main",
            "staged_files": [],
            "history": [{"commit": "init", "message": "Initial commit"}]
        }

    def execute(self, action: str, params: dict) -> dict:
        if action == "git_clone":
            repo = params.get("url")
            return {"status": "success", "message": f"Cloned {repo} into /tmp/repo"}
        elif action == "git_commit":
            msg = params.get("message", "Update")
            self.state["history"].append({"commit": "abc123", "message": msg})
            return {"status": "success", "message": f"Committed with message: {msg}"}
        elif action == "git_push":
            return {"status": "success", "message": "Pushed to origin main"}
        return {"status": "error", "message": f"Unknown git action: {action}"}

class ApiSimulator:
    """Simulates a generic REST API."""
    def __init__(self):
        self.endpoints = {
            "/api/v1/health": {"status": "healthy"},
            "/api/v1/user/1": {"id": 1, "name": "Test User", "plan": "pro"}
        }

    def execute(self, action: str, params: dict) -> dict:
        method = params.get("method", "GET").upper()
        path = params.get("path", "/")
        
        if method == "GET":
            result = self.endpoints.get(path, {"error": "Not Found"})
            return {"status": "success" if "error" not in result else "error", "data": result}
        elif method == "POST":
            # Simulate a successful post
            return {"status": "success", "data": {"id": 999, "status": "created"}}
        return {"status": "error", "message": f"Unsupported method: {method}"}

# Global registry of simulators for the sandbox
SIMULATOR_REGISTRY = {
    "git": GitSimulator(),
    "api": ApiSimulator()
}
