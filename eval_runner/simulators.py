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
            return {"status": "success", "data": {"id": 999, "status": "created"}}
        return {"status": "error", "message": f"Unsupported method: {method}"}

class DatabaseSimulator:
    """Simulates a secure SQL environment."""
    def __init__(self):
        self.tables = {
            "users": [{"id": 1, "email": "admin@example.com", "role": "admin"}],
            "logs": []
        }

    def execute(self, action: str, params: dict) -> dict:
        if action == "database_query":
            q = params.get("query", "").lower()
            if "select" in q: return {"status": "success", "rows": self.tables["users"]}
            if "insert" in q: 
                self.tables["logs"].append(params.get("data", {}))
                return {"status": "success", "message": "Row inserted"}
        return {"status": "error", "message": "Access denied or bad query"}

class SlackSimulator:
    """Simulates a corporate Slack workspace."""
    def __init__(self):
        self.messages = []

    def execute(self, action: str, params: dict) -> dict:
        if action == "slack_send":
            channel = params.get("channel", "general")
            msg = params.get("message", "")
            self.messages.append({"channel": channel, "text": msg})
            return {"status": "success", "ts": "123456.789"}
        return {"status": "error", "message": "Slack API down"}

class CRMSimulator:
    """Simulates an enterprise Customer Relationship Management system."""
    def __init__(self):
        self.leads = [{"id": "L101", "name": "Acme Corp", "status": "New"}]

    def execute(self, action: str, params: dict) -> dict:
        if action == "crm_update_lead":
            lead_id = params.get("id")
            new_status = params.get("status")
            for lead in self.leads:
                if lead["id"] == lead_id:
                    lead["status"] = new_status
                    return {"status": "success"}
        return {"status": "error", "message": "Lead not found"}

class EmailSimulator:
    """Simulates a corporate email server."""
    def __init__(self):
        self.inbox = [{"id": "M001", "from": "boss@corp.com", "subject": "Status?"}]
        self.sent = []

    def execute(self, action: str, params: dict) -> dict:
        if action == "email_send":
            self.sent.append(params)
            return {"status": "success", "id": "M002"}
        if action == "email_list":
            return {"status": "success", "messages": self.inbox}
        return {"status": "error", "message": "SMTP connection failed"}

class CalendarSimulator:
    """Simulates a calendar system (GCal/Outlook)."""
    def __init__(self):
        self.events = [{"title": "Eval Kickoff", "time": "2026-03-20T10:00"}]

    def execute(self, action: str, params: dict) -> dict:
        if action == "calendar_book":
            self.events.append(params)
            return {"status": "success"}
        return {"status": "error", "message": "Conflict detected"}

class JiraSimulator:
    """Simulates Jira/Issue tracking."""
    def __init__(self, initial_issues: list = None):
        self.issues = initial_issues if initial_issues is not None else [
            {"id": "PROJ-1", "summary": "Fix login bug", "status": "Todo"},
            {"id": "PROJ-2", "summary": "Implement Auth", "status": "In Progress"}
        ]

    def execute(self, action: str, params: dict) -> dict:
        if action == "jira_create":
            new_id = f"PROJ-{len(self.issues) + 1}"
            self.issues.append({
                "id": new_id,
                "summary": params.get("summary", "New issue"),
                "status": "Todo"
            })
            return {"status": "success", "id": new_id}
        elif action == "jira_update":
            issue_id = params.get("id")
            for i in self.issues:
                if i["id"] == issue_id:
                    i["status"] = params.get("status")
                    return {"status": "success"}
        elif action == "jira_list":
            return {"status": "success", "issues": self.issues}
        return {"status": "error", "message": "Issue not found or unknown action"}

class CloudSimulator:
    """Simulates AWS/GCP infrastructure."""
    def __init__(self):
        self.instances = [{"id": "i-1234", "type": "t2.micro", "status": "running"}]

    def execute(self, action: str, params: dict) -> dict:
        if action == "cloud_launch":
            self.instances.append({"id": "i-5678", "status": "pending"})
            return {"status": "success", "id": "i-5678"}
        return {"status": "error", "message": "Quota exceeded"}

class TerminalSimulator:
    """Simulates a remote SSH/Bash terminal."""
    def __init__(self):
        self.cwd = "/home/user"

    def execute(self, action: str, params: dict) -> dict:
        cmd = params.get("cmd", "")
        if "ls" in cmd: return {"status": "success", "output": "file1.txt\nfile2.py"}
        if "cd" in cmd: 
            self.cwd = params.get("path", self.cwd)
            return {"status": "success"}
        return {"status": "success", "output": f"Command executed in {self.cwd}"}

class StripeSimulator:
    """Simulates a payment gateway."""
    def __init__(self):
        self.charges = []

    def execute(self, action: str, params: dict) -> dict:
        if action == "stripe_charge":
            self.charges.append(params)
            return {"status": "success", "id": "ch_123"}
        return {"status": "error", "message": "Card declined"}

class ERPSimulator:
    """Simulates an ERP system (SAP/Oracle)."""
    def __init__(self):
        self.orders = [{"id": "O-99", "item": "Widget", "qty": 100}]

    def execute(self, action: str, params: dict) -> dict:
        if action == "erp_create_order":
            self.orders.append(params)
            return {"status": "success"}
        return {"status": "error", "message": "Inventory low"}

class BrowserSimulator:
    """Simulates a headless browser DOM."""
    def __init__(self):
        self.url = "about:blank"

    def execute(self, action: str, params: dict) -> dict:
        if action == "browser_go":
            self.url = params.get("url")
            return {"status": "success", "title": "Mock Page"}
        return {"status": "success", "url": self.url}

class KnowledgeBaseSimulator:
    """Simulates a Knowledge Base (Confluence/Notion/Wiki)."""
    def __init__(self):
        self.docs = [{"id": "D001", "title": "Onboarding", "content": "Welcome to the team!"}]

    def execute(self, action: str, params: dict) -> dict:
        if action == "kb_search":
            return {"status": "success", "results": self.docs}
        return {"status": "error", "message": "Document not found"}

class SupportDeskSimulator:
    """Simulates a ticketing system (Zendesk/Intercom)."""
    def __init__(self):
        self.tickets = [{"id": "TKT-123", "subject": "Billing issue", "status": "open"}]

    def execute(self, action: str, params: dict) -> dict:
        if action == "support_close":
            ticket_id = params.get("id")
            for t in self.tickets:
                if t["id"] == ticket_id:
                    t["status"] = "closed"
                    return {"status": "success"}
        return {"status": "error", "message": "Ticket not found"}

class SocialMediaSimulator:
    """Simulates social media interactions (X/LinkedIn)."""
    def __init__(self):
        self.posts = []

    def execute(self, action: str, params: dict) -> dict:
        if action == "social_post":
            self.posts.append(params)
            return {"status": "success", "id": "p_998"}
        return {"status": "success", "feed": self.posts}

class VectorDBSimulator:
    """Simulates a Vector Database (Pinecone/Milvus) for RAG."""
    def __init__(self):
        self.vectors = []

    def execute(self, action: str, params: dict) -> dict:
        if action == "vector_query":
            return {"status": "success", "matches": [{"id": "v1", "score": 0.99}]}
        return {"status": "success"}

class CICDSimulator:
    """Simulates a CI/CD pipeline (Jenkins/Actions)."""
    def __init__(self):
        self.builds = [{"id": "B-1", "status": "success"}]

    def execute(self, action: str, params: dict) -> dict:
        if action == "cicd_deploy":
            self.builds.append({"id": "B-2", "status": "running"})
            return {"status": "success", "id": "B-2"}
        return {"status": "success", "builds": self.builds}

class IoTSimulator:
    """Simulates IoT device interaction."""
    def __init__(self):
        self.devices = {"thermostat": "72F", "lights": "off"}

    def execute(self, action: str, params: dict) -> dict:
        device = params.get("device")
        if device in self.devices:
            self.devices[device] = params.get("state", self.devices[device])
            return {"status": "success", "state": self.devices[device]}
        return {"status": "error", "message": "Device offline"}

class SecuritySimulator:
    """Simulates Identity & Access Management (Auth0/Okta)."""
    def __init__(self):
        self.users = [{"id": "u_99", "role": "admin"}]

    def execute(self, action: str, params: dict) -> dict:
        if action == "security_auth":
            return {"status": "success", "token": "jwt_token_xyz"}
        return {"status": "error", "message": "Invalid credentials"}

# Internal world shims (immutable core defaults)
_INTERNAL_SIMULATORS = {
    "git": GitSimulator(),
    "api": ApiSimulator(),
    "database": DatabaseSimulator(),
    "slack": SlackSimulator(),
    "crm": CRMSimulator(),
    "email": EmailSimulator(),
    "calendar": CalendarSimulator(),
    "jira": JiraSimulator(),
    "cloud": CloudSimulator(),
    "terminal": TerminalSimulator(),
    "stripe": StripeSimulator(),
    "erp": ERPSimulator(),
    "browser": BrowserSimulator(),
    "kb": KnowledgeBaseSimulator(),
    "support": SupportDeskSimulator(),
    "social": SocialMediaSimulator(),
    "vector": VectorDBSimulator(),
    "cicd": CICDSimulator(),
    "iot": IoTSimulator(),
    "security": SecuritySimulator()
}

def get_simulator_registry() -> dict:
    """
    Returns the full registry of world shims, combining internal defaults
    with external shims discovered via the Zero-Touch plugin architecture.
    """
    from . import plugins
    
    # Start with a copy of internal defaults
    registry = _INTERNAL_SIMULATORS.copy()
    
    # Trigger plugin hook to allow external shims to register themselves
    plugins.manager.trigger("on_register_simulators", registry)
    
    return registry
