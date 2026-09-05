"""
tests.acceptance.support.acceptance_runner
Subprocess CLI runner executing AgentV product commands against the external CLI contract.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    """Outcome of a CLI command invocation."""

    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


class AgentVAcceptanceRunner:
    """
    Executes AgentV CLI commands via subprocess to enforce strict boundary separation
    between the test harness and the system under test.
    """

    def __init__(self, repo_root: Path | str | None = None, env: dict[str, str] | None = None):
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
        self.base_env = dict(os.environ)
        if env:
            self.base_env.update(env)
        # Ensure UTF-8 execution and PYTHONPATH includes repo root
        current_pythonpath = self.base_env.get("PYTHONPATH", "")
        self.base_env["PYTHONPATH"] = (
            f"{str(self.repo_root)}{os.pathsep}{current_pythonpath}"
            if current_pythonpath
            else str(self.repo_root)
        )
        self.base_env["PYTHONUTF8"] = "1"
        self.base_env["PYTHONIOENCODING"] = "utf-8"

    def _exec(self, args: list[str], timeout: float = 60.0) -> CommandResult:
        cmd = [sys.executable, "-m", "eval_runner.cli", *args]
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self.base_env,
                timeout=timeout,
            )
            duration = time.perf_counter() - start
            return CommandResult(
                command=cmd,
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired as err:
            duration = time.perf_counter() - start
            return CommandResult(
                command=cmd,
                exit_code=-999,
                stdout=err.stdout or "",
                stderr=f"Command timed out after {timeout} seconds: {err}",
                duration_seconds=duration,
            )

    def run(
        self,
        scenario_path: Path | str,
        agent: str | None = None,
        protocol: str = "local",
        seed: int | None = None,
        attempts: int = 1,
        run_id: str | None = None,
        run_log_dir: str | Path | None = None,
    ) -> CommandResult:
        """Execute: agentv run --scenario ..."""
        args = ["run", "--scenario", str(scenario_path)]
        if agent:
            # If agent points to a .py file, pass python executable prefix.
            # Use forward slashes to prevent shlex.split backslash stripping on Windows
            agent_str = str(agent).replace("\\", "/")
            py_exe = sys.executable.replace("\\", "/")
            if agent_str.endswith(".py") and not agent_str.startswith(py_exe):
                agent_str = f'"{py_exe}" "{agent_str}"'
            args.extend(["--agent", agent_str])
        if protocol:
            args.extend(["--protocol", protocol])
        if seed is not None:
            args.extend(["--seed", str(seed)])
        if attempts > 1:
            args.extend(["--attempts", str(attempts)])
        if run_id:
            args.extend(["--run-id", run_id])
        if run_log_dir:
            args.extend(["--run-log-dir", str(run_log_dir)])
        return self._exec(args)

    def certify(self, run_id: str, identity: str = "system_id") -> CommandResult:
        """Execute: agentv certify --run-id ..."""
        args = ["certify", "--run-id", run_id, "--identity", identity]
        return self._exec(args)

    def verify(
        self,
        run_id: str | None = None,
        trace_path: Path | str | None = None,
        manifest_path: Path | str | None = None,
        verify_ledger: bool = True,
        pqc: bool = False,
    ) -> CommandResult:
        """Execute: agentv verify --run-id ..."""
        target_id = run_id
        if not target_id and trace_path:
            target_id = Path(trace_path).parent.name
        if not target_id:
            raise ValueError("Either run_id or trace_path must be provided to verify")
        args = ["verify", "--run-id", str(target_id)]
        if pqc:
            args.append("--pqc")
        return self._exec(args)

    def verify_package(
        self,
        package_path: Path | str,
        raw_trace_path: Path | str | None = None,
        public_key_pem: Path | str | None = None,
        require_signature: bool = False,
    ) -> CommandResult:
        """Execute: agentv verify-package <package_path>"""
        args = ["verify-package", str(package_path)]
        if raw_trace_path:
            args.extend(["--trace", str(raw_trace_path)])
        if public_key_pem:
            args.extend(["--public-key", str(public_key_pem)])
        if require_signature:
            args.append("--require-signature")
        return self._exec(args)

    def gate(
        self,
        run_id: str,
        commit_hash: str | None = None,
        verify_ledger: bool = True,
    ) -> CommandResult:
        """Execute: agentv gate --run-id ..."""
        args = ["gate", "--run-id", run_id]
        if commit_hash:
            args.extend(["--hash", commit_hash])
        if verify_ledger:
            args.append("--verify-ledger")
        return self._exec(args)


__all__ = ["AgentVAcceptanceRunner", "CommandResult"]
