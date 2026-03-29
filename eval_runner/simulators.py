"""
simulators.py

Standard simulation shims for common agent environments (Git, API).
"""

from typing import Any, Dict


class BaseSimulator:
    """Base class for all world shims with state management."""
    def __init__(self, initial_state: Dict[str, Any] = None):
        self.state = initial_state or {}

    def execute(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches an action to a handler method."""
        handler_name = f"handle_{action}"
        handler = getattr(self, handler_name, None)
        if handler:
            return handler(params)
        return {"status": "error", "message": f"Unknown action: {action} on {self.__class__.__name__}"}

    def cleanup(self):
        """Perform lifecycle cleanup (close files, sockets, etc.)."""
        # Default behavior: No-op for pure-Python simulators
        pass

    def __del__(self):
        """Destructor to safeguard against resource leaks."""
        try:
            self.cleanup()
        except:
            pass


class GitSimulator(BaseSimulator):
    """Simulates a dynamic Git repository state."""

    def __init__(self):
        super().__init__({
            "current_branch": "main",
            "file_tree": {}, # path -> content
            "staged_files": [],
            "history": [{"commit": "init", "message": "Initial commit"}],
        })

    def handle_git_clone(self, params: dict) -> dict:
        repo = params.get("url")
        return {"status": "success", "message": f"Cloned {repo} into /tmp/repo"}

    def handle_git_add(self, params: dict) -> dict:
        files = params.get("files", [])
        self.state["staged_files"].extend(files)
        return {"status": "success", "message": f"Staged {len(files)} files."}

    def handle_git_commit(self, params: dict) -> dict:
        msg = params.get("message", "Update")
        commit_id = f"commit_{len(self.state['history'])}"
        self.state["history"].append({"commit": commit_id, "message": msg})
        self.state["staged_files"] = []
        return {"status": "success", "message": f"Committed with message: {msg}"}

    def handle_git_push(self, params: dict) -> dict:
        return {"status": "success", "message": "Pushed to origin main"}


class ApiSimulator(BaseSimulator):
    """Simulates a generic REST API with dynamic registration."""

    def __init__(self):
        super().__init__({
            "endpoints": {
                "/api/v1/health": {"status": "healthy"},
                "/api/v1/user/1": {"id": 1, "name": "Test User", "plan": "pro"},
            }
        })

    def handle_api_request(self, params: dict) -> dict:
        method = params.get("method", "GET").upper()
        path = params.get("path", "/")

        if method == "GET":
            result = self.state["endpoints"].get(path, {"error": "Not Found"})
            return {
                "status": "success" if "error" not in result else "error",
                "data": result,
            }
        elif method == "POST":
            # Real implementation: allow adding endpoints dynamically
            if "path" in params and "data" in params:
                 self.state["endpoints"][params["path"]] = params["data"]
            return {"status": "success", "data": {"id": 999, "status": "created"}}
        return {"status": "error", "message": f"Unsupported method: {method}"}

    # Backward compatibility shim for old execute calls
    def execute(self, action: str, params: dict) -> dict:
        if action in ["GET", "POST", "PUT", "DELETE"]:
            params["method"] = action
            return self.handle_api_request(params)
        return super().execute(action, params)


class DatabaseSimulator(BaseSimulator):
    """Simulates a dynamic secure SQL environment."""

    def __init__(self):
        super().__init__({
            "tables": {
                "users": [{"id": 1, "email": "admin@example.com", "role": "admin"}],
                "logs": [],
            }
        })

    def handle_database_query(self, params: dict) -> dict:
        q = params.get("query", "").lower()
        if "select" in q:
            return {"status": "success", "rows": self.state["tables"]["users"]}
        if "insert" in q:
            self.state["tables"]["logs"].append(params.get("data", {}))
            return {"status": "success", "message": "Row inserted"}
        return {"status": "error", "message": "Access denied or bad query"}


class SlackSimulator(BaseSimulator):
    """Simulates a dynamic Slack workspace."""

    def __init__(self):
        super().__init__({"messages": []})

    def handle_slack_send(self, params: dict) -> dict:
        channel = params.get("channel", "general")
        msg = params.get("message", "")
        self.state["messages"].append({"channel": channel, "text": msg})
        return {"status": "success", "ts": "123456.789"}


class CRMSimulator(BaseSimulator):
    """Simulates a dynamic CRM system."""

    def __init__(self):
        super().__init__({
            "leads": [{"id": "L101", "name": "Acme Corp", "status": "New"}]
        })

    def handle_crm_update_lead(self, params: dict) -> dict:
        lead_id = params.get("id")
        new_status = params.get("status")
        for lead in self.state["leads"]:
            if lead["id"] == lead_id:
                lead["status"] = new_status
                return {"status": "success"}
        return {"status": "error", "message": "Lead not found"}


class EmailSimulator(BaseSimulator):
    """Simulates a dynamic email server."""

    def __init__(self):
        super().__init__({
            "inbox": [{"id": "M001", "from": "boss@corp.com", "subject": "Status?"}],
            "sent": []
        })

    def handle_email_send(self, params: dict) -> dict:
        self.state["sent"].append(params)
        return {"status": "success", "id": f"M{len(self.state['sent']) + 2:03d}"}

    def handle_email_list(self, params: dict) -> dict:
        return {"status": "success", "messages": self.state["inbox"]}


class CalendarSimulator(BaseSimulator):
    """Simulates a dynamic calendar system."""

    def __init__(self):
        super().__init__({
            "events": [{"title": "Eval Kickoff", "time": "2026-03-20T10:00"}]
        })

    def handle_calendar_book(self, params: dict) -> dict:
        # Check for conflicts in a real implementation
        self.state["events"].append(params)
        return {"status": "success"}


class JiraSimulator(BaseSimulator):
    """Simulates a dynamic Jira project management environment."""

    def __init__(self):
        super().__init__({
            "issues": [{"id": "PROJ-1", "summary": "Initial Bug", "status": "To Do"}],
            "projects": ["PROJ"]
        })

    def handle_jira_create(self, params: dict) -> dict:
        summary = params.get("summary", "New Task")
        new_id = f"PROJ-{len(self.state['issues']) + 1}"
        new_issue = {"id": new_id, "summary": summary, "status": "To Do"}
        self.state["issues"].append(new_issue)
        return {"status": "success", "id": new_id, "issue": new_issue}

    def handle_jira_update(self, params: dict) -> dict:
        issue_id = params.get("id")
        new_status = params.get("status")
        for issue in self.state["issues"]:
            if issue["id"] == issue_id:
                issue["status"] = new_status
                return {"status": "success", "id": issue_id, "new_status": new_status}
        return {"status": "error", "message": f"Issue {issue_id} not found."}

    def handle_jira_list(self, params: dict) -> dict:
        return {"status": "success", "issues": self.state["issues"]}


class CloudSimulator(BaseSimulator):
    """Simulates dynamic AWS/GCP infrastructure."""

    def __init__(self):
        super().__init__({
            "instances": [{"id": "i-1234", "type": "t2.micro", "status": "running"}]
        })

    def handle_cloud_launch(self, params: dict) -> dict:
        new_id = f"i-{len(self.state['instances']) + 5678}"
        instance = {"id": new_id, "type": params.get("type", "t2.micro"), "status": "pending"}
        self.state["instances"].append(instance)
        return {"status": "success", "id": new_id, "instance": instance}


class TerminalSimulator(BaseSimulator):
    """Simulates a dynamic SSH/Bash terminal."""

    def __init__(self):
        super().__init__({
            "cwd": "/home/user",
            "history": []
        })

    def handle_terminal_execute(self, params: dict) -> dict:
        cmd = params.get("cmd", "")
        self.state["history"].append(cmd)
        if "ls" in cmd:
            return {"status": "success", "output": "file1.txt\nfile2.py"}
        if "cd" in cmd:
            self.state["cwd"] = params.get("path", self.state["cwd"])
            return {"status": "success"}
        return {"status": "success", "output": f"Command executed in {self.state['cwd']}"}

    # Backward compatibility shim for execute(cmd, params)
    def execute(self, action: str, params: dict) -> dict:
        if action not in ["terminal_execute"]:
             params["cmd"] = action # If called directly as execute("ls", {})
             return self.handle_terminal_execute(params)
        return super().execute(action, params)


class StripeSimulator(BaseSimulator):
    """Simulates a dynamic payment gateway."""

    def __init__(self):
        super().__init__({"charges": []})

    def handle_stripe_charge(self, params: dict) -> dict:
        self.state["charges"].append(params)
        return {"status": "success", "id": f"ch_{len(self.state['charges'])}"}


class ERPSimulator(BaseSimulator):
    """Simulates a dynamic ERP system."""

    def __init__(self):
        super().__init__({
            "orders": [{"id": "O-99", "item": "Widget", "qty": 100}]
        })

    def handle_erp_create_order(self, params: dict) -> dict:
        self.state["orders"].append(params)
        return {"status": "success"}


class BrowserSimulator(BaseSimulator):
    """Simulates dynamic headless browser DOM."""

    def __init__(self):
        super().__init__({"url": "about:blank"})

    def handle_browser_go(self, params: dict) -> dict:
        self.state["url"] = params.get("url")
        return {"status": "success", "title": "Mock Page"}


class KnowledgeBaseSimulator(BaseSimulator):
    """Simulates dynamic Knowledge Base."""

    def __init__(self):
        super().__init__({
            "docs": [{"id": "D001", "title": "Onboarding", "content": "Welcome to the team!"}]
        })

    def handle_kb_search(self, params: dict) -> dict:
        return {"status": "success", "results": self.state["docs"]}


class SupportDeskSimulator(BaseSimulator):
    """Simulates dynamic ticketing system."""

    def __init__(self):
        super().__init__({
            "tickets": [{"id": "TKT-123", "subject": "Billing issue", "status": "open"}]
        })

    def handle_support_close(self, params: dict) -> dict:
        ticket_id = params.get("id")
        for t in self.state["tickets"]:
            if t["id"] == ticket_id:
                t["status"] = "closed"
                return {"status": "success"}
        return {"status": "error", "message": "Ticket not found"}


class SocialMediaSimulator(BaseSimulator):
    """Simulates dynamic social media interactions."""

    def __init__(self):
        super().__init__({"posts": []})

    def handle_social_post(self, params: dict) -> dict:
        self.state["posts"].append(params)
        return {"status": "success", "id": f"p_{len(self.state['posts'])}"}


class VectorDBSimulator(BaseSimulator):
    """Simulates dynamic Vector Database."""

    def __init__(self):
        super().__init__({"vectors": []})

    def handle_vector_query(self, params: dict) -> dict:
        return {"status": "success", "matches": [{"id": "v1", "score": 0.99}]}


class CICDSimulator(BaseSimulator):
    """Simulates dynamic CI/CD pipeline."""

    def __init__(self):
        super().__init__({
            "builds": [{"id": "B-1", "status": "success"}]
        })

    def handle_cicd_deploy(self, params: dict) -> dict:
        new_id = f"B-{len(self.state['builds']) + 1}"
        self.state["builds"].append({"id": new_id, "status": "running"})
        return {"status": "success", "id": new_id}


class IoTSimulator(BaseSimulator):
    """Simulates dynamic IoT device interaction."""

    def __init__(self):
        super().__init__({
            "devices": {"thermostat": "72F", "lights": "off"}
        })

    def handle_iot_update(self, params: dict) -> dict:
        device = params.get("device")
        if device in self.state["devices"]:
            self.state["devices"][device] = params.get("state", self.state["devices"][device])
            return {"status": "success", "state": self.state["devices"][device]}
        return {"status": "error", "message": "Device offline"}

    # Special case execute for IoT
    def execute(self, action: str, params: dict) -> dict:
        if action == "iot_update":
             return self.handle_iot_update(params)
        return super().execute(action, params)


class SecuritySimulator(BaseSimulator):
    """Simulates dynamic Identity & Access Management."""

    def __init__(self):
        super().__init__({
            "users": [{"id": "u_99", "role": "admin"}]
        })

    def handle_security_auth(self, params: dict) -> dict:
        return {"status": "success", "token": "jwt_token_xyz"}


# Registry of simulator classes for factory instantiation
_INTERNAL_SIMULATOR_CLASSES = {
    "git": GitSimulator,
    "api": ApiSimulator,
    "database": DatabaseSimulator,
    "slack": SlackSimulator,
    "crm": CRMSimulator,
    "email": EmailSimulator,
    "calendar": CalendarSimulator,
    "jira": JiraSimulator,
    "cloud": CloudSimulator,
    "terminal": TerminalSimulator,
    "stripe": StripeSimulator,
    "erp": ERPSimulator,
    "browser": BrowserSimulator,
    "kb": KnowledgeBaseSimulator,
    "support": SupportDeskSimulator,
    "social": SocialMediaSimulator,
    "vector": VectorDBSimulator,
    "cicd": CICDSimulator,
    "iot": IoTSimulator,
    "security": SecuritySimulator,
}


def get_simulator_registry() -> dict:
    """
    Returns a fresh registry of world shims (new instances).
    """
    from eval_runner import plugins

    # Return new instances of all internal simulators
    registry = {name: cls() for name, cls in _INTERNAL_SIMULATOR_CLASSES.items()}

    # Trigger plugin hook to allow external shims to register themselves (they should provide instances or factory)
    plugins.manager.trigger("on_register_simulators", registry)

    return registry
