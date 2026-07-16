import os
import shlex
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any


class SimulatorMiddleware(ABC):
    """
    Middleware interface to intercept/decorate simulator actions.
    Useful for introducing simulated latency, rate limiting, logging,
    or custom routing.
    """

    @abstractmethod
    async def process_action(
        self,
        simulator: "BaseSimulator",
        action: str,
        params: dict[str, Any],
        next_call: Callable[[], Coroutine[Any, Any, dict[str, Any]]],
    ) -> dict[str, Any]:
        pass


class BaseJailProvider(ABC):
    """
    Interface for terminal execution sandboxes/jails.
    Defaults to SubprocessJailProvider in Core, can be swapped for containerized providers.
    """

    @abstractmethod
    async def execute_command(
        self, cmd: str, cwd: str, env: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        pass

    @abstractmethod
    async def cleanup(self, run_id: str) -> None:
        """Teardown and clean up execution sandbox resources (e.g. Docker containers)
        associated with the run.
        """
        pass


class SubprocessJailProvider(BaseJailProvider):
    """
    Default Core implementation executing commands via isolated subprocesses.
    """

    async def execute_command(
        self, cmd: str, cwd: str, env: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        import sys

        is_windows = sys.platform == "win32"
        try:
            process = subprocess.run(
                shlex.split(cmd) if not is_windows else cmd,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=is_windows,  # nosec B602
                start_new_session=not is_windows,
            )
            return {
                "status": "success" if process.returncode == 0 else "error",
                "stdout": process.stdout,
                "stderr": process.stderr,
                "returncode": process.returncode,
                "cwd": cwd,
            }
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "message": f"Command timed out (Limit: {timeout}s)",
            }
        except Exception as e:
            return {"status": "error", "message": f"Execution Error: {str(e)}"}

    async def cleanup(self, run_id: str) -> None:
        # Subprocesses are self-terminating, no resources to release in standard core subprocess
        pass


class ShimResultProxy(dict):
    """
    Result wrapper proxy that shields internal metadata (like signing keys or raw telemetry DNA)
    from direct guest execution contexts. Inherits from dict for backward compatibility.

    Only guest-facing keys defined in the AES schema are allowed through. Telemetry/DNA
    metadata is stripped and must be retrieved via the secure side-channel `get_secure_metadata()`.
    """

    _GUEST_KEYS: frozenset[str] = frozenset(
        {
            "status",
            "message",
            "stdout",
            "stderr",
            "returncode",
            "cwd",
            "payload",  # The namespace containing all dynamic guest data
        }
    )

    def __init__(self, result: dict[str, Any], metadata: dict[str, Any] | None = None):
        guest_payload = {k: v for k, v in result.items() if k in self._GUEST_KEYS}
        super().__init__(guest_payload)
        self._secure_metadata = metadata or {}

    def get_secure_metadata(self) -> dict[str, Any]:
        """Provides secure metadata/keys to the auditing/verifier context only."""
        return self._secure_metadata


class BaseSimulator:
    """Base class for all world shims with state management."""

    def __init__(self, initial_state: dict[str, Any] = None, config: dict[str, Any] = None):
        self.state = initial_state or {}
        self.config = config or {}
        # [Turn 2 Hardening] Physical Jail Path
        self.terminal_jail: Any = None
        self._middlewares: list[SimulatorMiddleware] = []
        # [Industrial Hygiene] Global tracking for test suite cleanup
        if not hasattr(BaseSimulator, "_instances"):
            BaseSimulator._instances = set()
        BaseSimulator._instances.add(self)

    def register_middleware(self, middleware: SimulatorMiddleware):
        """Registers a simulator middleware dynamically."""
        self._middlewares.append(middleware)

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatches an action to a handler method through registered middlewares."""

        async def _core_execute():
            handler_name = f"handle_{action}"
            handler = getattr(self, handler_name, None)
            if handler:
                import inspect

                if inspect.iscoroutinefunction(handler):
                    return await handler(params)
                return handler(params)
            return {
                "status": "error",
                "message": f"Unknown action: {action} on {self.__class__.__name__}",
            }

        def make_next(index: int) -> Callable[[], Coroutine[Any, Any, dict[str, Any]]]:
            if index >= len(self._middlewares):
                return _core_execute

            middleware = self._middlewares[index]

            async def call_next() -> dict[str, Any]:
                try:
                    return await middleware.process_action(
                        self, action, params, make_next(index + 1)
                    )
                except Exception as e:
                    import logging

                    logging.getLogger(__name__).error(
                        f"[BaseSimulator] Middleware {middleware.__class__.__name__} failed: {e}. "
                        "Bypassing to next handler."
                    )
                    return await make_next(index + 1)()

            return call_next

        return await make_next(0)()

    async def cleanup(self):
        """[Turn 5] Explicit cleanup (e.g. closing browser, DB sessions)."""
        if hasattr(BaseSimulator, "_instances"):
            BaseSimulator._instances.discard(self)

    async def quiesce(self) -> None:
        """Lifecycle method to settle asynchronous tasks, database flushes, and pending I/O."""
        pass

    async def on_poll(self, condition: str, params: dict[str, Any]) -> bool:
        """
        Industrial Liveness Hook.
        Supports polling for asynchronous tool completions or state transitions.
        Checks if the internal state matches the requested condition.
        """
        # Priority 1: Exact value match if requested
        if "expected_value" in params:
            return self.state.get(condition) == params["expected_value"]

        # Priority 2: Truthiness of the state key
        if condition in self.state:
            return bool(self.state[condition])

        return True

    async def on_verify(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Standardized verification hook for shim-specific post-conditions.
        Compares internal state against provided criteria.
        """
        criteria = params.get("criteria", {})
        if not criteria:
            return {"status": "success"}

        errors = []
        for key, expected in criteria.items():
            actual = self.state.get(key)
            if actual != expected:
                errors.append(f"State mismatch for '{key}': expected {expected}, got {actual}")

        if errors:
            return {"status": "error", "message": "; ".join(errors)}
        return {"status": "success"}

    async def get_snapshot(self) -> dict[str, Any]:
        """
        Returns a point-in-time snapshot of the world state from this shim's perspective.
        This provides the "Ground Truth" for State Parity verification.
        """
        # Default behavior: Return a deep copy of the internal state dictionary
        # This prevents accidental mutations during the verification phase.
        import copy

        return copy.deepcopy(self.state)


class GitSimulator(BaseSimulator):
    """Simulates a dynamic Git repository state."""

    def __init__(self, *args, **kwargs):
        super().__init__({"history": [], "staged_files": []}, *args, **kwargs)
        self._repo = None

    def _get_repo(self):
        """Lazy initialization of GitPython Repo inside the terminal_jail."""
        if self._repo:
            return self._repo

        from pathlib import Path

        from git import Repo

        repo_path = Path(self.terminal_jail or ".tmp") / "repo"
        if (repo_path / ".git").exists():
            self._repo = Repo(repo_path)
        return self._repo

    async def handle_git_clone(self, params: dict) -> dict:
        """
        [Iteration 3: Industrial Git Engine]
        Clones a real repository into the terminal_jail.
        """
        from pathlib import Path

        from git import Repo

        url = params.get("url")
        dest = Path(self.terminal_jail or ".tmp") / "repo"

        # [Iteration 5: Resilience] Enforce Industrial Timeout
        # GitPython uses subprocess under the hood, but we wrap for safety
        try:
            if dest.exists():
                from .utils import rmtree_resilient

                rmtree_resilient(dest)

            # [RFC-002 Hybrid Registry]
            from . import config

            registry_resources = config.get_shim_config("git")
            default_branch = registry_resources.get("default_branch", "main")
            depth = 1 if registry_resources.get("shallow_clone", False) else None

            self._repo = Repo.clone_from(url, dest, branch=default_branch, depth=depth)
            return {
                "status": "success",
                "message": f"Cloned {url} into {dest} (branch={default_branch})",
            }
        except Exception as e:
            return {"status": "error", "message": f"Git Clone Error: {str(e)}"}

    async def handle_git_add(self, params: dict) -> dict:
        """Adds files to the repository index."""
        repo = self._get_repo()
        if not repo:
            return {"status": "error", "message": "No active repository found."}

        files = params.get("files", [])
        try:
            repo.index.add(files)
            return {"status": "success", "message": f"Staged {len(files)} files."}
        except Exception as e:
            return {"status": "error", "message": f"Git Add Error: {str(e)}"}

    async def handle_git_commit(self, params: dict) -> dict:
        """Commits staged changes."""
        repo = self._get_repo()
        if not repo:
            return {"status": "error", "message": "No active repository found."}

        msg = params.get("message", "Industrial Guard Trace Commit")
        try:
            commit = repo.index.commit(msg)
            return {
                "status": "success",
                "message": f"Committed: {commit.hexsha}",
                "dna": {"commit_sha": commit.hexsha, "author": str(commit.author)},
            }
        except Exception as e:
            return {"status": "error", "message": f"Git Commit Error: {str(e)}"}

    async def handle_git_push(self, params: dict) -> dict:
        """Simulates a push to origin (for safety in evaluation)."""
        return {"status": "success", "message": "Pushed to origin main (Simulated for safety)"}

    async def cleanup(self):
        """[Iteration 5: Secure Wipe] Release Git handles."""
        if self._repo:
            self._repo.close()
            self._repo = None


class ApiSimulator(BaseSimulator):
    """Simulates a generic REST API with dynamic registration."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            {
                "endpoints": {
                    "/api/v1/health": {"status": "healthy"},
                    "/api/v1/user/1": {"id": 1, "name": "Test User", "plan": "pro"},
                }
            },
            *args,
            **kwargs,
        )

    async def handle_api_request(self, params: dict) -> dict:
        """
        [Iteration 3: Industrial API Engine]
        Executes real asynchronous HTTP requests using HTTPX.
        Captures full Request/Response DNA for forensic auditing.
        """
        import time

        import httpx

        import eval_runner.config as config

        method = params.get("method", "GET").upper()
        url = params.get("url") or params.get("path", "")
        headers = params.get("headers", {})
        data = params.get("data")

        # [Iteration 1: Normalization] Prefixless URLs (Industrial Requirement #3)
        if url and not url.startswith(("http://", "https://", "ws://", "wss://")):
            url = f"http://{url}"

        if not url:
            return {"status": "error", "message": "Invalid API URL provided."}

        # [Iteration 6: RFC-002 Hybrid Registry]
        # Pull declarative resources from the central registry
        registry_resources = config.get_shim_config("api")

        # Merge registry headers into request
        default_headers = registry_resources.get("default_headers", {})
        headers = {**default_headers, **headers}

        # [Iteration 5: Resilience] Enforce Industrial Timeout
        try:
            # Fallback hierarchy: Registry -> Environment -> Default
            reg_timeout = registry_resources.get("global_timeout")
            timeout_str = os.getenv("SHIM_TIMEOUT", str(reg_timeout) if reg_timeout else "30.0")
            timeout = float(timeout_str) if timeout_str.replace(".", "", 1).isdigit() else 30.0
        except (ValueError, TypeError):
            timeout = 30.0

        # [Iteration 3: Live vs Mock Toggle]
        is_live = os.getenv("IS_LIVE", "false").lower() == "true"

        if not is_live:
            # Standard Industry Mock behavior (Turn 1/2)
            path = params.get("path", "/")
            result = self.state["endpoints"].get(path, {"error": "Not Found (MOCK_MODE)"})
            return {
                "status": "success" if "error" not in result else "error",
                "payload": {"data": result},
            }

        request_kwargs = {
            "method": method,
            "url": url,
            "headers": headers,
        }
        if data:
            request_kwargs["json"] = data

        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(**request_kwargs)
                latency = time.perf_counter() - start_time

                # [Iteration 3/4 DNA] capture telemetry
                dna = {
                    "request": {"method": method, "url": url, "headers": headers},
                    "response": {
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "latency_sec": latency,
                    },
                }

                return {
                    "status": "success" if response.is_success else "error",
                    "payload": {
                        "data": response.json()
                        if "application/json" in response.headers.get("Content-Type", "")
                        else response.text
                    },
                    "dna": dna,
                }
        except Exception as e:
            return {"status": "error", "message": f"API Execution Error: {str(e)}"}

    async def get_snapshot(self) -> dict[str, Any]:
        """Returns the registered endpoints and any captured telemetry state."""
        return {
            "endpoints": self.state.get("endpoints", {}),
            "is_live": os.getenv("IS_LIVE", "false").lower() == "true",
        }

    # Backward compatibility shim for old execute calls
    async def execute(self, action: str, params: dict) -> dict:
        if action in ["GET", "POST", "PUT", "DELETE"]:
            params["method"] = action
            return await self.handle_api_request(params)
        return await super().execute(action, params)


class DatabaseSimulator(BaseSimulator):
    """Simulates a dynamic secure SQL environment."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            {"tables": {}},
            *args,
            **kwargs,
        )
        self._engine = None
        self._forensics_provisioned = False

    def _get_engine(self):
        """Lazy initialization of SQLAlchemy engine inside the terminal_jail."""
        if self._engine:
            return self._engine

        from pathlib import Path

        from sqlalchemy import create_engine, text

        # New Standard -> Legacy Nesting -> Local Transient
        db_uri = self.config.get("primary_db", {}).get("connection") or self.config.get(
            "resources", {}
        ).get("primary_db", {}).get("connection")

        if not db_uri:
            db_path = Path(self.terminal_jail or ".tmp").resolve() / "state.db"
            # [Iteration 3 Normalization] Windows absolute path handling (sqlite:///C:/...)
            db_path_str = str(db_path).replace("\\", "/")
            db_uri = f"sqlite:///{db_path_str}"

        from sqlalchemy.pool import NullPool

        self._engine = create_engine(db_uri, poolclass=NullPool)

        # [Iteration 3 Init] Baseline Table Provisioning (Pre-Forensic)
        with self._engine.connect() as conn:
            # We provide a baseline 'users' table for backward compatibility with core tests.
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE,
                    role TEXT DEFAULT 'user',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            )
            conn.commit()

        # [Industrial Governance] Provision Forensic Infrastructure
        # (This will discover 'users' and install triggers)
        if not self._forensics_provisioned:
            self._provision_forensic_log(self._engine)
            self._forensics_provisioned = True

        # [Iteration 3 Seeding] Initial state mutations
        with self._engine.connect() as conn:
            # Seed if empty (Iteration 1 Baseline)
            res = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
            if res == 0:
                conn.execute(
                    text("INSERT INTO users (email, role) VALUES ('admin@test.com', 'admin')")
                )
            conn.commit()

        return self._engine

    def _provision_forensic_log(self, engine):
        """
        Installs SQLite triggers for row-level mutation tracking (CUD).
        Ensures all changes are recorded in _forensic_audit_log for lean forensics.
        """

        from sqlalchemy import inspect, text

        with engine.connect() as conn:
            # 1. Create Audit Table
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS _forensic_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    table_name TEXT,
                    action TEXT,
                    row_identity TEXT,
                    old_data TEXT,
                    new_data TEXT,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            )

            # 2. Discover Tables and Install Triggers
            inspector = inspect(engine)
            for table_name in inspector.get_table_names():
                if table_name.startswith("_"):  # Skip internal tables
                    continue

                columns = [c["name"] for c in inspector.get_columns(table_name)]
                if not columns:
                    continue

                # DNA Construction: Include rowid for reliable identity tracking
                new_json_parts = ", ".join([f"'{c}', NEW.\"{c}\"" for c in columns])
                new_json = f"json_object({new_json_parts})"
                old_json_parts = ", ".join([f"'{c}', OLD.\"{c}\"" for c in columns])
                old_json = f"json_object({old_json_parts})"

                # Escape table names for reserved keywords (e.g. "order")
                safe_table = f'"{table_name}"'

                # C: INSERT
                conn.execute(
                    text(f"""
                    CREATE TRIGGER IF NOT EXISTS _audit_insert_{table_name} 
                    AFTER INSERT ON {safe_table}
                    BEGIN
                        INSERT INTO _forensic_audit_log (table_name, action, row_identity, new_data)
                        VALUES ('{table_name}', 'INSERT', CAST(NEW.rowid AS TEXT), {new_json});
                    END;
                """)  # nosec B608
                )
                # U: UPDATE
                conn.execute(
                    text(f"""
                    CREATE TRIGGER IF NOT EXISTS _audit_update_{table_name} 
                    AFTER UPDATE ON {safe_table}
                    BEGIN
                        INSERT INTO _forensic_audit_log 
                            (table_name, action, row_identity, old_data, new_data)
                        VALUES 
                            ('{table_name}', 'UPDATE', CAST(NEW.rowid AS TEXT), 
                             {old_json}, {new_json});
                    END;
                """)  # nosec B608
                )
                # D: DELETE
                conn.execute(
                    text(f"""
                    CREATE TRIGGER IF NOT EXISTS _audit_delete_{table_name} 
                    AFTER DELETE ON {safe_table}
                    BEGIN
                        INSERT INTO _forensic_audit_log (table_name, action, row_identity, old_data)
                        VALUES ('{table_name}', 'DELETE', CAST(OLD.rowid AS TEXT), {old_json});
                    END;
                """)  # nosec B608
                )
            conn.commit()

    def log_forensic_event(self, conn, table_name: str, action: str, dna: dict | None = None):
        """[Industrial Forensic] Manually log a non-CUD event (like RS) to the audit log."""
        import json

        from sqlalchemy import text

        conn.execute(
            text("""
            INSERT INTO _forensic_audit_log (table_name, action, row_identity, new_data)
            VALUES (:table, :action, 'N/A', :dna)
        """),
            {"table": table_name, "action": action, "dna": json.dumps(dna) if dna else None},
        )

    async def handle_database_query(self, params: dict) -> dict:
        """
        [Iteration 3: Industrial SQL Engine]
        Executes a real SQL query using SQLAlchemy 2.0.
        Logs RS (Read/Search) metadata for forensic auditing.
        """
        from sqlalchemy import text

        q = params.get("query", "")
        engine = self._get_engine()

        try:
            with engine.connect() as conn:
                result = conn.execute(text(q))
                if result.returns_rows:
                    rows = [dict(row._mapping) for row in result]

                    # [Forensic Hardening] Log RS (Read/Search) Metadata
                    if q.strip().upper().startswith(("SELECT", "WITH")):
                        self.log_forensic_event(
                            conn, "N/A", "READ", {"query": q, "row_count": len(rows)}
                        )

                    conn.commit()
                    return {"status": "success", "payload": {"rows": rows}}

                conn.commit()

                # If a new table was created,
                # provision forensics for it immediately.
                if "CREATE TABLE" in q.upper():
                    self._provision_forensic_log(engine)

                return {"status": "success", "message": "Query executed successfully."}
        except Exception as e:
            return {"status": "error", "message": f"Database Error: {str(e)}"}

    async def get_snapshot(self) -> dict[str, Any]:
        """
        [Lean Forensics] Returns only the CRUDS audit log since the beginning of the turn.
        Never captures full table state, ensuring zero-leak compliance.
        """
        self._get_engine()
        if not self._engine:
            return {"audit_log": [], "engine": "mock"}

        import json

        from sqlalchemy import text

        snapshot = {"tables": {}, "audit_log": [], "engine": "sqlite"}
        try:
            with self._engine.connect() as conn:
                # [Industrial Rule] Only return the forensic log.
                # This ensures we don't snapshot a "trillion row db".
                result = conn.execute(
                    text("SELECT * FROM _forensic_audit_log ORDER BY timestamp ASC")
                ).fetchall()

                # We'll use a temporary map to track the latest state of each row
                # to provide a virtual 'tables' view for state parity checks.
                # Key: (table_name, row_identity)
                latest_rows = {}

                for row in result:
                    entry = dict(row._mapping)
                    tname = entry.get("table_name")
                    action = entry.get("action")

                    # Parse JSON data
                    old_data = None
                    new_data = None
                    if entry.get("old_data"):
                        try:
                            old_data = json.loads(entry.get("old_data"))
                        except Exception:
                            import logging

                            logging.debug("Failed to decode forensic old_data JSON")
                    if entry.get("new_data"):
                        try:
                            new_data = json.loads(entry.get("new_data"))
                        except Exception:
                            import logging

                            logging.debug("Failed to decode forensic new_data JSON")

                    entry["old_data"] = old_data
                    entry["new_data"] = new_data
                    snapshot["audit_log"].append(entry)

                    # Virtual Table Reconstruction (Lean Parity Support)
                    if tname and tname != "N/A":
                        row_id = entry.get("row_identity")
                        if action == "DELETE":
                            if (tname, row_id) in latest_rows:
                                del latest_rows[(tname, row_id)]
                        else:
                            latest_rows[(tname, row_id)] = new_data

                # Build the 'tables' view from latest_rows
                for (tname, _), data in latest_rows.items():
                    if tname not in snapshot["tables"]:
                        snapshot["tables"][tname] = []
                    snapshot["tables"][tname].append(data)

        except Exception as e:
            snapshot["error"] = f"Forensic snapshot failed: {e}"

        return snapshot

    async def cleanup(self):
        """[Iteration 5: Secure Wipe] Dispose SQLAlchemy engine to release file locks."""
        if self._engine:
            self._engine.dispose()
            self._engine = None
        await super().cleanup()


class SlackSimulator(BaseSimulator):
    """Simulates a dynamic Slack workspace."""

    def __init__(self, *args, **kwargs):
        super().__init__({"messages": []}, *args, **kwargs)

    def handle_slack_send(self, params: dict) -> dict:
        channel = params.get("channel", "general")
        msg = params.get("message", "")
        self.state["messages"].append({"channel": channel, "text": msg})
        return {"status": "success", "ts": "123456.789"}


class CRMSimulator(BaseSimulator):
    """Simulates a dynamic CRM system."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            {"leads": [{"id": "L101", "name": "Acme Corp", "status": "New"}]}, *args, **kwargs
        )

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

    def __init__(self, *args, **kwargs):
        super().__init__(
            {"inbox": [{"id": "M001", "from": "boss@corp.com", "subject": "Status?"}], "sent": []},
            *args,
            **kwargs,
        )

    def handle_email_send(self, params: dict) -> dict:
        self.state["sent"].append(params)
        return {"status": "success", "id": f"M{len(self.state['sent']) + 2:03d}"}

    def handle_email_list(self, params: dict) -> dict:
        return {"status": "success", "messages": self.state["inbox"]}


class CalendarSimulator(BaseSimulator):
    """Simulates a dynamic calendar system."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            {"events": [{"title": "Eval Kickoff", "time": "2026-03-20T10:00"}]}, *args, **kwargs
        )

    def handle_calendar_book(self, params: dict) -> dict:
        # Check for conflicts in a real implementation
        self.state["events"].append(params)
        return {"status": "success"}


class JiraSimulator(BaseSimulator):
    """Simulates a dynamic Jira project management environment."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            {
                "issues": [{"id": "PROJ-1", "summary": "Initial Bug", "status": "To Do"}],
                "projects": ["PROJ"],
            },
            *args,
            **kwargs,
        )

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

    def __init__(self, *args, **kwargs):
        super().__init__(
            {"instances": [{"id": "i-1234", "type": "t2.micro", "status": "running"}]},
            *args,
            **kwargs,
        )

    async def handle_cloud_launch(self, params: dict) -> dict:
        """
        [Iteration 3: Industrial Cloud Engine]
        Manages virtual infrastructure state with lifecyle transitions.
        """
        instance_type = params.get("type", "t2.micro")
        new_id = f"i-{len(self.state['instances']) + 1000}"

        instance = {
            "id": new_id,
            "type": instance_type,
            "status": "pending",
            "launch_time": datetime.now().isoformat(),
        }
        self.state["instances"].append(instance)

        return {
            "status": "success",
            "instance_id": new_id,
            "dna": {"provider": "mock-industrial-v1", "region": "us-east-1"},
        }

    async def on_poll(self, condition: str, params: dict) -> bool:
        """[Turn 1 Hook] Handle pending -> running transitions."""
        if condition == "instance_running":
            iid = params.get("instance_id")
            for inst in self.state["instances"]:
                if inst["id"] == iid:
                    inst["status"] = "running"
                    return True
        return False


class TerminalSimulator(BaseSimulator):
    """Simulates a dynamic SSH/Bash terminal."""

    def __init__(self, *args, **kwargs):
        super().__init__({"cwd": "/home/user", "history": []}, *args, **kwargs)
        self.jail_provider = self.config.get("jail_provider") or SubprocessJailProvider()

    def set_jail_provider(self, provider: BaseJailProvider):
        """Allows swapping the execution jail provider (e.g. for containerized Docker)."""
        self.jail_provider = provider

    async def cleanup(self):
        """Clean up active jail provider resources during simulator teardown."""
        if hasattr(self, "jail_provider") and self.jail_provider:
            run_id = self.config.get("run_id") or "default_run"
            try:
                await self.jail_provider.cleanup(run_id)
            except Exception as e:
                import logging

                logging.getLogger(__name__).error(
                    f"[TerminalSimulator] Jail provider cleanup failed: {e}"
                )
        await super().cleanup()

    async def handle_terminal_execute(self, params: dict) -> dict:
        """
        Executes a real shell command within the terminal_jail boundary.
        Delegates the physical command execution to the pluggable jail_provider.
        """
        from .utils import is_path_safe

        cmd = params.get("cmd") or ""
        if not cmd:
            return {"status": "error", "message": "Command not provided."}

        self.state["history"].append(cmd)

        # [Iteration 2: Physical Containment] Anchor to terminal_jail
        if not self.terminal_jail:
            return {"status": "error", "message": "Terminal Jail not provisioned."}

        jail_path = Path(self.terminal_jail).resolve()

        # [Iteration 5 Prevention] Handle 'cd' as a special case for state management
        if cmd.startswith("cd "):
            target_path = Path(cmd.split("cd ", 1)[1].strip())
            if not target_path.is_absolute():
                target_path = (Path(self.state.get("cwd", jail_path)) / target_path).resolve()

            if is_path_safe(target_path, jail_path):
                self.state["cwd"] = str(target_path)
                return {"status": "success", "message": f"Changed directory to {target_path}"}
            return {"status": "error", "message": "Security Violation: Path traversal blocked."}

        # [Iteration 3: Execution] Pluggable execution jail with env isolation
        try:
            cwd = self.state.get("cwd", str(jail_path))
            # Industrial Guard: Ensure current state CWD is still within jail
            if not is_path_safe(cwd, jail_path):
                cwd = str(jail_path)

            return await self.jail_provider.execute_command(
                cmd=cmd,
                cwd=cwd,
                env={},  # Extreme Isolation: No host env leakage
                timeout=30.0,
            )
        except Exception as e:
            return {"status": "error", "message": f"Execution Error: {str(e)}"}

    # Backward compatibility shim for execute(cmd, params)
    async def execute(self, action: str, params: dict) -> dict:
        if action not in ["terminal_execute"]:
            params["cmd"] = action  # If called directly as execute("ls", {})
            return await self.handle_terminal_execute(params)
        return await super().execute(action, params)


class StripeSimulator(BaseSimulator):
    """Simulates a dynamic payment gateway."""

    def __init__(self, *args, **kwargs):
        super().__init__({"charges": []}, *args, **kwargs)

    def handle_stripe_charge(self, params: dict) -> dict:
        self.state["charges"].append(params)
        return {"status": "success", "id": f"ch_{len(self.state['charges'])}"}


class ERPSimulator(BaseSimulator):
    """Simulates a dynamic ERP system."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            {"orders": [{"id": "O-99", "item": "Widget", "qty": 100}]}, *args, **kwargs
        )

    def handle_erp_create_order(self, params: dict) -> dict:
        self.state["orders"].append(params)
        return {"status": "success"}


class BrowserSimulator(BaseSimulator):
    """Simulates dynamic headless browser DOM."""

    def __init__(self, *args, **kwargs):
        super().__init__({"url": "about:blank"}, *args, **kwargs)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def _get_page(self):
        """Lazy initialization of Playwright headless browser."""
        if self._page:
            return self._page

        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        # [Iteration 5: Resilience] Isolated Browser Instance
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()

        return self._page

    async def handle_browser_go(self, params: dict) -> dict:
        """
        [Iteration 3: Industrial Browser Engine]
        Navigates to a real URL using Playwright.
        Captures Page DNA (Title, URL, Screenshot metadata).
        """
        url = params.get("url", "https://google.com")
        page = await self._get_page()

        # [Iteration 5: Resilience] Enforce Industrial Timeout
        timeout = float(os.getenv("SHIM_TIMEOUT", "30.0")) * 1000  # ms

        try:
            await page.goto(url, timeout=timeout)
            title = await page.title()
            current_url = page.url

            # [Iteration 3/4 DNA] capture telemetry
            dna = {
                "page": {"title": title, "url": current_url},
                "browser": "chromium-headless",
            }

            return {"status": "success", "title": title, "url": current_url, "dna": dna}
        except Exception as e:
            return {"status": "error", "message": f"Browser Execution Error: {str(e)}"}

    async def cleanup(self):
        """[Iteration 5: Secure Wipe] Close browser resources."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()


class KnowledgeBaseSimulator(BaseSimulator):
    """Simulates dynamic Knowledge Base."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            {"docs": [{"id": "D001", "title": "Onboarding", "content": "Welcome to the team!"}]},
            *args,
            **kwargs,
        )

    def handle_kb_search(self, params: dict) -> dict:
        return {"status": "success", "results": self.state["docs"]}


class SupportDeskSimulator(BaseSimulator):
    """Simulates dynamic ticketing system."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            {"tickets": [{"id": "TKT-123", "subject": "Billing issue", "status": "open"}]},
            *args,
            **kwargs,
        )

    def handle_support_close(self, params: dict) -> dict:
        ticket_id = params.get("id")
        for t in self.state["tickets"]:
            if t["id"] == ticket_id:
                t["status"] = "closed"
                return {"status": "success"}
        return {"status": "error", "message": "Ticket not found"}


class SocialMediaSimulator(BaseSimulator):
    """Simulates dynamic social media interactions."""

    def __init__(self, *args, **kwargs):
        super().__init__({"posts": []}, *args, **kwargs)

    def handle_social_post(self, params: dict) -> dict:
        post_id = f"p_{len(self.state['posts']) + 1}"
        params["id"] = post_id
        self.state["posts"].append(params)
        return {"status": "success", "id": post_id}

    async def on_poll(self, condition: str, params: dict) -> bool:
        """Social specific polling (Line 639 coverage check)."""
        if condition == "post_confirmed":
            post_id = params.get("post_id")
            return any(p.get("id") == post_id for p in self.state["posts"])
        return False


class VectorDBSimulator(BaseSimulator):
    """Simulates dynamic Vector Database."""

    def __init__(self, *args, **kwargs):
        super().__init__({"vectors": []}, *args, **kwargs)

    def handle_vector_query(self, params: dict) -> dict:
        return {"status": "success", "matches": [{"id": "v1", "score": 0.99}]}


class CICDSimulator(BaseSimulator):
    """Simulates dynamic CI/CD pipeline."""

    def __init__(self, *args, **kwargs):
        super().__init__({"builds": [{"id": "B-1", "status": "success"}]}, *args, **kwargs)

    async def handle_cicd_deploy(self, params: dict) -> dict:
        """
        [Iteration 3: Industrial CI/CD Engine]
        Simulates structured pipeline execution.
        """
        env = params.get("environment", "staging")
        build_id = f"B-{len(self.state['builds']) + 100}"

        build = {
            "id": build_id,
            "status": "queued",
            "env": env,
            "logs": [f"Starting deployment to {env}..."],
        }
        self.state["builds"].append(build)

        return {"status": "success", "build_id": build_id}

    async def on_poll(self, condition: str, params: dict) -> bool:
        """[Turn 1 Hook] Progression of pipeline builds."""
        if condition == "build_complete":
            bid = params.get("build_id")
            for b in self.state["builds"]:
                if b["id"] == bid:
                    b["status"] = "success"
                    b["logs"].append("Deployment successful.")
                    return True
        return False


class IoTSimulator(BaseSimulator):
    """Simulates dynamic IoT device interaction."""

    def __init__(self, *args, **kwargs):
        super().__init__({"devices": {"thermostat": "72F", "lights": "off"}}, *args, **kwargs)

    def handle_iot_update(self, params: dict) -> dict:
        device = params.get("device")
        if device in self.state["devices"]:
            self.state["devices"][device] = params.get("state", self.state["devices"][device])
            return {"status": "success", "state": self.state["devices"][device]}
        return {"status": "error", "message": "Device offline"}

    # Special case execute for IoT
    async def execute(self, action: str, params: dict) -> dict:
        if action == "iot_update":
            return self.handle_iot_update(params)
        return await super().execute(action, params)


class SecuritySimulator(BaseSimulator):
    """Simulates dynamic Identity & Access Management."""

    def __init__(self, *args, **kwargs):
        super().__init__({"users": [{"id": "u_99", "role": "admin"}]}, *args, **kwargs)

    async def handle_security_auth(self, params: dict) -> dict:
        """
        [Iteration 3: Industrial Security Engine]
        Implements a permission-scoped registry.
        """
        import uuid

        scope = params.get("scope", "read-only")
        token = str(uuid.uuid4())

        self.state["active_tokens"] = self.state.get("active_tokens", {})
        self.state["active_tokens"][token] = {
            "scope": scope,
            "expires": (datetime.now().timestamp() + 3600),
        }

        return {
            "status": "success",
            "token": token,
            "dna": {"auth_method": "OIDC/PBAC", "perms": [scope]},
        }


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


def get_simulator_registry(plugin_manager=None) -> dict:
    """
    Returns a fresh registry of world shims (new instances).
    """
    from eval_runner import plugins

    # Baseline: Populate with internal simulator classes for legacy discovery compatibility.
    # [Hardening] We use name-based keys to align with the registry-manager discovery pattern.
    registry = {k: v for k, v in _INTERNAL_SIMULATOR_CLASSES.items()}

    # Trigger plugin hook to allow external shims to register themselves
    pm = plugin_manager or plugins.manager
    pm.trigger("on_register_simulators", registry)

    return registry
