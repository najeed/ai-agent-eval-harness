import logging
import math
import os
import shlex
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any

from agentv_runtime.canonical import canonical_json_encode
from agentv_runtime.contracts import EvidenceBoundednessLimits, EvidenceReference
from agentv_runtime.interfaces import BoundedStateProvider

logger = logging.getLogger(__name__)


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

    def __init__(self) -> None:
        self._active_runs: dict[str, dict[str, Any]] = {}

    async def execute_command(
        self, cmd: str, cwd: str, env: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        import sys

        is_windows = sys.platform == "win32"
        run_id = env.get("AGENTV_RUN_ID", "default_run")
        self._active_runs[run_id] = {"last_cmd": cmd, "cwd": cwd}
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
            logger.debug(
                "SubprocessJailProvider command timed out after %ss: %s",
                timeout,
                cmd,
                exc_info=True,
            )
            return {
                "status": "error",
                "message": f"Command timed out (Limit: {timeout}s)",
            }
        except Exception as e:
            logger.debug("Failure in SubprocessJailProvider.execute_command", exc_info=True)
            return {"status": "error", "message": f"Execution Error: {str(e)}"}

    async def cleanup(self, run_id: str) -> None:
        """Clear tracked subprocess execution state associated with the run."""
        removed = self._active_runs.pop(run_id, None)
        if removed is not None:
            logger.debug("SubprocessJailProvider cleaned up run_id=%s", run_id)


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

    is_external: bool = False

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
        self._is_quiesced = True
        logger.debug("Quiesced simulator %s", self.__class__.__name__)

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
        super().__init__(
            {"history": [], "staged_files": [], "pushes": [], "pushed_commits": []},
            *args,
            **kwargs,
        )
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
            self.state["active_branch"] = default_branch
            self.state["remote_url"] = url
            return {
                "status": "success",
                "message": f"Cloned {url} into {dest} (branch={default_branch})",
            }
        except Exception as e:
            logger.debug("Failure in GitSimulator.handle_git_clone", exc_info=True)
            return {"status": "error", "message": f"Git Clone Error: {str(e)}"}

    async def handle_git_add(self, params: dict) -> dict:
        """Adds files to the repository index."""
        repo = self._get_repo()
        if not repo:
            return {"status": "error", "message": "No active repository found."}

        files = params.get("files", [])
        try:
            repo.index.add(files)
            staged = self.state.setdefault("staged_files", [])
            for file_path in files:
                if file_path not in staged:
                    staged.append(file_path)
            return {"status": "success", "message": f"Staged {len(files)} files."}
        except Exception as e:
            logger.debug("Failure in GitSimulator.handle_git_add", exc_info=True)
            return {"status": "error", "message": f"Git Add Error: {str(e)}"}

    async def handle_git_commit(self, params: dict) -> dict:
        """Commits staged changes."""
        repo = self._get_repo()
        if not repo:
            return {"status": "error", "message": "No active repository found."}

        msg = params.get("message", "Industrial Guard Trace Commit")
        try:
            commit = repo.index.commit(msg)
            commit_entry = {
                "commit_sha": commit.hexsha,
                "message": msg,
                "author": str(commit.author),
            }
            self.state.setdefault("history", []).append(commit_entry)
            self.state["staged_files"] = []
            return {
                "status": "success",
                "message": f"Committed: {commit.hexsha}",
                "dna": {"commit_sha": commit.hexsha, "author": str(commit.author)},
            }
        except Exception as e:
            logger.debug("Failure in GitSimulator.handle_git_commit", exc_info=True)
            return {"status": "error", "message": f"Git Commit Error: {str(e)}"}

    async def handle_git_push(self, params: dict) -> dict:
        """Simulates a push to origin and records pushed branch/commit state."""
        remote_raw = params.get("remote", "origin")
        branch_raw = params.get("branch", self.state.get("active_branch", "main"))
        remote = str(remote_raw).strip() if remote_raw is not None else ""
        branch = str(branch_raw).strip() if branch_raw is not None else ""
        if not remote or not branch:
            return {
                "status": "error",
                "message": "Invalid remote or branch specified for git push.",
            }

        repo = self._get_repo()
        if repo is None:
            return {"status": "error", "message": "No active repository found."}
        from git.exc import BadName, BadObject, GitError

        try:
            commit_sha = repo.commit(branch).hexsha
            if not isinstance(commit_sha, str) or not commit_sha:
                raise ValueError("Branch has no commit")
            if params.get("commit_sha", commit_sha) != commit_sha:
                raise ValueError("Requested commit does not match branch")
        except (GitError, BadName, BadObject, OSError, ValueError, TypeError, AttributeError):
            logger.debug("GitSimulator failed to resolve push branch", exc_info=True)
            return {"status": "error", "message": "Push branch or commit is invalid."}

        push_record = {
            "remote": remote,
            "branch": branch,
            "commit_sha": commit_sha,
            "repo_active": True,
        }
        self.state.setdefault("pushes", []).append(push_record)
        self.state.setdefault("pushed_commits", []).append(push_record)
        return {
            "status": "success",
            "message": f"Pushed to {remote} {branch} (Simulated for safety)",
            "push": push_record,
        }

    async def cleanup(self):
        """[Iteration 5: Secure Wipe] Release Git handles."""
        if self._repo:
            self._repo.close()
            self._repo = None
        await super().cleanup()


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
            logger.debug("Failure in ApiSimulator.handle_api_request", exc_info=True)
            return {"status": "error", "message": f"API Execution Error: {str(e)}"}

    async def get_snapshot(self) -> dict[str, Any]:
        """Returns the registered endpoints and any captured telemetry state."""
        import copy

        endpoints = copy.deepcopy(self.state.get("endpoints", {}))
        is_live = os.getenv("IS_LIVE", "false").lower() == "true"
        snapshot: dict[str, Any] = {
            "endpoints": endpoints,
            "is_live": is_live,
        }
        if "requests" in self.state:
            snapshot["requests"] = copy.deepcopy(self.state["requests"])
        return snapshot

    # Backward compatibility shim for old execute calls
    async def execute(self, action: str, params: dict) -> dict:
        if action in ["GET", "POST", "PUT", "DELETE"]:
            params["method"] = action
            return await self.handle_api_request(params)
        return await super().execute(action, params)


class DatabaseSimulator(BaseSimulator, BoundedStateProvider):
    """Simulates a dynamic secure SQL environment conforming to Evidence Boundedness Contract."""

    is_external: bool = True

    def __init__(self, *args, **kwargs):
        super().__init__(
            {"tables": {}},
            *args,
            **kwargs,
        )
        self._engine = None
        self._forensics_provisioned = False

    def query_bounded_reference(
        self,
        scope: str,
        selector: dict[str, Any] | str,
        max_items: int | None = None,
        max_bytes: int | None = None,
        **kwargs: Any,
    ) -> EvidenceReference:
        """
        Executes a bounded query/selector against the database and returns an EvidenceReference.
        Unbounded full-state materialization is strictly prevented.
        """
        import hashlib

        from sqlalchemy import text

        engine = self._get_engine()
        query_str = selector if isinstance(selector, str) else str(selector.get("query", ""))
        limit = min(
            max_items or EvidenceBoundednessLimits.MAX_INLINE_ITEMS,
            EvidenceBoundednessLimits.MAX_INLINE_ITEMS,
        )

        with engine.connect() as conn:
            result = conn.execute(text(query_str))
            rows = []
            if result.returns_rows:
                fetched = result.fetchmany(limit + 1)
                for r in fetched:
                    rows.append(dict(r._mapping))

            result_count = len(rows)
            sampled = rows[:limit]
            raw_bytes = canonical_json_encode(sampled)
            result_hash = hashlib.sha3_256(raw_bytes).hexdigest()
            query_hash = hashlib.sha3_256(query_str.encode("utf-8")).hexdigest()

            return EvidenceReference(
                source_id=f"db://{scope}",
                scope=scope,
                selector_hash=query_hash,
                query_or_operation_hash=query_hash,
                result_hash=result_hash,
                result_count=result_count,
                sampled_result=sampled,
                provenance={
                    "engine": "sqlite",
                    "bounded": True,
                    "max_items": limit,
                },
            )

    def commit_state_transition(
        self,
        scope: str,
        operation: str,
        delta: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> EvidenceReference:
        """Captures a bounded state transition/mutation as an EvidenceReference."""
        import hashlib

        from agentv_runtime.canonical import canonical_json_encode

        delta_bytes = canonical_json_encode(delta or {})
        result_hash = hashlib.sha3_256(delta_bytes).hexdigest()
        op_hash = hashlib.sha3_256(operation.encode("utf-8")).hexdigest()

        return EvidenceReference(
            source_id=f"db://{scope}",
            scope=scope,
            selector_hash=op_hash,
            query_or_operation_hash=op_hash,
            result_hash=result_hash,
            result_count=1 if delta else 0,
            sampled_result=delta,
            provenance={
                "operation": operation,
                "bounded": True,
            },
        )

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
            logging.getLogger(__name__).debug(
                "Failure in DatabaseSimulator.handle_database_query", exc_info=True
            )
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
                            logger.debug("Failed to decode forensic old_data JSON", exc_info=True)
                    if entry.get("new_data"):
                        try:
                            new_data = json.loads(entry.get("new_data"))
                        except Exception:
                            logger.debug("Failed to decode forensic new_data JSON", exc_info=True)

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
            logger.debug("Failure in DatabaseSimulator.get_snapshot", exc_info=True)
            snapshot["error"] = f"Forensic snapshot failed: {e}"

        return snapshot

    async def quiesce(self) -> None:
        """Flush pending SQLite WAL frames and release pooled database connections."""
        self.state["quiesced"] = False
        self._is_quiesced = False
        if self._engine is not None:
            from sqlalchemy import text

            checkpoint_failed = False
            try:
                with self._engine.connect() as conn:
                    checkpoint = conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
                    if checkpoint.fetchone()[0] != 0:
                        raise RuntimeError("Database checkpoint is busy")
                    conn.commit()
            except Exception:
                checkpoint_failed = True
                logger.debug("DatabaseSimulator WAL checkpoint failed", exc_info=True)
                raise
            finally:
                try:
                    self._engine.dispose()
                except Exception:
                    logger.debug("DatabaseSimulator pool disposal failed", exc_info=True)
                    if not checkpoint_failed:
                        raise
        self.state["quiesced"] = True
        await super().quiesce()

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
        folder = str(params.get("folder", "inbox") or "inbox").strip().lower()
        if folder == "all":
            messages = list(self.state.get("inbox", [])) + list(self.state.get("sent", []))
        else:
            messages = list(self.state.get(folder, []))

        sender = params.get("from") or params.get("sender")
        if sender:
            sender_norm = str(sender).strip().lower()
            messages = [m for m in messages if sender_norm in str(m.get("from", "")).lower()]

        recipient = params.get("to") or params.get("recipient")
        if recipient:
            recipient_norm = str(recipient).strip().lower()
            messages = [m for m in messages if recipient_norm in str(m.get("to", "")).lower()]

        status = params.get("status")
        if status:
            status_norm = str(status).strip().lower()
            messages = [
                m for m in messages if str(m.get("status", "")).strip().lower() == status_norm
            ]

        query = params.get("query") or params.get("subject")
        if query:
            query_norm = str(query).strip().lower()
            messages = [
                m
                for m in messages
                if query_norm in str(m.get("subject", "")).lower()
                or query_norm in str(m.get("body", "")).lower()
            ]

        return {"status": "success", "folder": folder, "messages": messages}


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
        project = str(params.get("project", "PROJ") or "PROJ").strip().upper()
        new_id = f"{project}-{len(self.state['issues']) + 1}"
        new_issue: dict[str, Any] = {
            "id": new_id,
            "summary": summary,
            "status": params.get("status", "To Do"),
        }
        if "assignee" in params:
            new_issue["assignee"] = params["assignee"]
        if "project" in params:
            new_issue["project"] = project
        self.state["issues"].append(new_issue)
        return {"status": "success", "id": new_id, "issue": new_issue}

    def handle_jira_update(self, params: dict) -> dict:
        issue_id = params.get("id")
        new_status = params.get("status")
        for issue in self.state["issues"]:
            if issue["id"] == issue_id:
                if new_status is not None:
                    issue["status"] = new_status
                if "assignee" in params:
                    issue["assignee"] = params["assignee"]
                if "summary" in params:
                    issue["summary"] = params["summary"]
                return {"status": "success", "id": issue_id, "new_status": issue["status"]}
        return {"status": "error", "message": f"Issue {issue_id} not found."}

    def handle_jira_list(self, params: dict) -> dict:
        issues = list(self.state.get("issues", []))
        status = params.get("status")
        if status:
            status_norm = str(status).strip().lower()
            issues = [i for i in issues if str(i.get("status", "")).strip().lower() == status_norm]

        assignee = params.get("assignee")
        if assignee:
            assignee_norm = str(assignee).strip().lower()
            issues = [
                i for i in issues if str(i.get("assignee", "")).strip().lower() == assignee_norm
            ]

        project = params.get("project")
        if project:
            project_norm = str(project).strip().upper()
            issues = [
                i
                for i in issues
                if str(i.get("project", "")).strip().upper() == project_norm
                or str(i.get("id", "")).upper().startswith(f"{project_norm}-")
            ]

        query = params.get("query")
        if query:
            query_norm = str(query).strip().lower()
            issues = [
                i
                for i in issues
                if query_norm in str(i.get("summary", "")).lower()
                or query_norm in str(i.get("id", "")).lower()
            ]

        return {"status": "success", "issues": issues}


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
        self.state["cleaned_up"] = False
        if hasattr(self, "jail_provider") and self.jail_provider:
            run_id = self.config.get("run_id") or "default_run"
            try:
                await self.jail_provider.cleanup(run_id)
            except Exception as e:
                logger.error(
                    f"[TerminalSimulator] Jail provider cleanup failed: {e}",
                    exc_info=True,
                )
                return
        self.state["cleaned_up"] = True
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
                env={"AGENTV_RUN_ID": self.config.get("run_id") or "default_run"},
                timeout=30.0,
            )
        except Exception as e:
            logging.getLogger(__name__).debug(
                "Failure in TerminalSimulator.handle_terminal_execute", exc_info=True
            )
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
        super().__init__({"url": "about:blank", "title": "", "history": []}, *args, **kwargs)
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

            self.state["url"] = current_url
            self.state["title"] = title
            self.state.setdefault("history", []).append({"url": current_url, "title": title})

            # [Iteration 3/4 DNA] capture telemetry
            dna = {
                "page": {"title": title, "url": current_url},
                "browser": "chromium-headless",
            }

            return {"status": "success", "title": title, "url": current_url, "dna": dna}
        except Exception as e:
            logger.debug("Failure in BrowserSimulator.handle_browser_go", exc_info=True)
            return {"status": "error", "message": f"Browser Execution Error: {str(e)}"}

    async def get_snapshot(self) -> dict[str, Any]:
        """Returns a point-in-time snapshot of the browser navigation state."""
        import copy

        snapshot = copy.deepcopy(self.state)
        snapshot["browser_active"] = self._page is not None
        return snapshot

    async def cleanup(self):
        """[Iteration 5: Secure Wipe] Close browser resources."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                logger.debug("BrowserSimulator context close failed", exc_info=True)
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._page = None
        await super().cleanup()


class KnowledgeBaseSimulator(BaseSimulator):
    """Simulates dynamic Knowledge Base."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            {"docs": [{"id": "D001", "title": "Onboarding", "content": "Welcome to the team!"}]},
            *args,
            **kwargs,
        )

    def handle_kb_search(self, params: dict) -> dict:
        docs = list(self.state.get("docs", []))
        raw_query = params.get("query") or params.get("keyword") or params.get("q")
        raw_keywords = params.get("keywords")
        tag_filter = params.get("tag")

        terms: list[str] = []
        if isinstance(raw_keywords, list):
            terms.extend(str(k).strip().lower() for k in raw_keywords if str(k).strip())
        elif isinstance(raw_keywords, str) and raw_keywords.strip():
            terms.extend(t.lower() for t in raw_keywords.split() if t.strip())

        if isinstance(raw_query, str) and raw_query.strip():
            terms.extend(t.lower() for t in raw_query.split() if t.strip())

        scored_results: list[tuple[int, dict[str, Any]]] = []
        for doc in docs:
            if tag_filter:
                doc_tags = [str(t).lower() for t in doc.get("tags", [])]
                if str(tag_filter).strip().lower() not in doc_tags:
                    continue

            if not terms:
                scored_results.append((1, doc))
                continue

            haystack = " ".join(
                [
                    str(doc.get("id", "")),
                    str(doc.get("title", "")),
                    str(doc.get("content", "")),
                    " ".join(str(t) for t in doc.get("tags", [])),
                ]
            ).lower()
            score = sum(1 for term in terms if term in haystack)
            if score > 0:
                scored_results.append((score, doc))

        scored_results.sort(key=lambda item: item[0], reverse=True)
        results = [doc for _, doc in scored_results]

        limit = params.get("limit", params.get("top_k"))
        if limit is not None:
            try:
                limit = int(limit)
                if limit < 0:
                    raise ValueError("Search limit must be nonnegative")
                results = results[:limit]
            except (ValueError, TypeError):
                logger.debug("Invalid limit parameter in handle_kb_search", exc_info=True)
                return {"status": "error", "message": "Invalid search limit."}

        return {"status": "success", "results": results, "total": len(results)}


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
        """Social specific polling."""
        if condition == "post_confirmed":
            post_id = params.get("post_id")
            return any(p.get("id") == post_id for p in self.state["posts"])
        return False


class VectorDBSimulator(BaseSimulator):
    """Simulates dynamic Vector Database."""

    def __init__(self, *args, **kwargs):
        super().__init__({"vectors": []}, *args, **kwargs)

    def handle_vector_upsert(self, params: dict) -> dict:
        vectors = params.get("vectors")
        if isinstance(vectors, list):
            self.state.setdefault("vectors", []).extend(vectors)
            count = len(vectors)
        elif isinstance(params.get("id"), str):
            self.state.setdefault("vectors", []).append(dict(params))
            count = 1
        else:
            return {"status": "error", "message": "No valid vectors provided for upsert."}
        return {"status": "success", "upserted_count": count}

    def handle_vector_query(self, params: dict) -> dict:
        """Rank stored vectors by cosine similarity or text-term overlap."""
        try:
            top_k = int(params.get("top_k", params.get("limit", 10)))
            if top_k < 0:
                raise ValueError("top_k must be nonnegative")
            min_score = float(params.get("min_score", -1))
            if not math.isfinite(min_score):
                raise ValueError("min_score must be finite")
            query_vec = params.get("vector", params.get("vec", params.get("embedding")))
            query_text = params.get("query", params.get("text", ""))
            filter_meta = params.get("filter", params.get("metadata", {}))
            if not isinstance(query_text, str) or not isinstance(filter_meta, dict):
                raise ValueError("Query must be text and filter must be an object")
            if query_vec is not None:
                if not isinstance(query_vec, list) or not query_vec:
                    raise ValueError("Query vector must be a nonempty list")
                query_vec = [float(value) for value in query_vec]
                if not all(math.isfinite(value) for value in query_vec):
                    raise ValueError("Vector values must be finite")
                query_norm = math.hypot(*query_vec)
                if query_norm == 0:
                    raise ValueError("Query vector must have nonzero norm")
            terms = query_text.lower().split()
            matches = []
            for item in self.state.get("vectors", []):
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    raise ValueError("Stored vectors must have string identities")
                metadata = item.get("metadata", {})
                if not isinstance(metadata, dict):
                    raise ValueError("Stored metadata must be an object")
                if not all(metadata.get(key) == value for key, value in filter_meta.items()):
                    continue
                score = None
                if query_vec is not None:
                    values = item.get("values", item.get("vector", item.get("embedding")))
                    if not isinstance(values, list) or len(values) != len(query_vec):
                        raise ValueError("Stored vector dimensions must match query")
                    values = [float(value) for value in values]
                    norm = math.hypot(*values)
                    if not all(math.isfinite(value) for value in values) or norm == 0:
                        raise ValueError("Stored vector must be finite with nonzero norm")
                    score = sum(
                        (a / query_norm) * (b / norm)
                        for a, b in zip(query_vec, values, strict=True)
                    )
                if terms:
                    text = " ".join(
                        str(item.get(key, "")) for key in ("id", "text", "content")
                    ).lower()
                    overlap = sum(term in text for term in terms) / len(terms)
                    if overlap == 0:
                        continue
                    score = overlap if score is None else (score + overlap) / 2
                if score is None:
                    raise ValueError("A vector or text query is required")
                if score < min_score:
                    continue
                match = {"id": item["id"], "score": round(score, 4)}
                for key in ("metadata", "text"):
                    if key in item:
                        import copy

                        match[key] = copy.deepcopy(item[key])
                matches.append(match)
            matches.sort(key=lambda match: match["score"], reverse=True)
            return {"status": "success", "matches": matches[:top_k]}
        except (ValueError, TypeError, OverflowError):
            logger.debug("Vector query rejected invalid input or stored state", exc_info=True)
            return {"status": "error", "message": "Invalid vector query or stored vector data."}


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
    from eval_runner.runtime_services import resolve_plugin_registry

    # Baseline: Populate with internal simulator classes for legacy discovery compatibility.
    # [Hardening] We use name-based keys to align with the registry-manager discovery pattern.
    registry = {k: v for k, v in _INTERNAL_SIMULATOR_CLASSES.items()}

    # Trigger plugin hook to allow external shims to register themselves
    pm = plugin_manager or resolve_plugin_registry()
    pm.trigger("on_register_simulators", registry)

    return registry
