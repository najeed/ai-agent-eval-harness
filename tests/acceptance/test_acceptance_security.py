"""
tests.acceptance.test_acceptance_security
Product-Level Security Acceptance Tests Certifying Containment, Jail Boundary, and Tool Isolation.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from tests.acceptance.support.assertions import assert_gate_failed, assert_gate_passed

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.acceptance
@pytest.mark.acceptance_release
def test_acceptance_security_prompt_injection_blocked(isolated_acceptance_env):
    """
    Certifies that indirect prompt injection attempting unauthorized transfers
    is blocked by scenario policy guardrails and cannot commit state.
    """
    env = isolated_acceptance_env
    runner = env["runner"]
    run_id = f"at-sec-inj-{uuid.uuid4().hex[:8]}"

    scenario_path = (
        REPO_ROOT / "industries" / "finance" / "scenarios" / "unauthorized_transfer.json"
    )
    agent_path = (
        REPO_ROOT / "tests" / "acceptance" / "fixtures" / "agents" / "prompt_injection_agent.py"
    )

    runner.run(
        scenario_path=scenario_path,
        agent=str(agent_path),
        protocol="local",
        run_id=run_id,
        run_log_dir=env["runs_dir"],
    )

    # Trace file must record policy violation
    trace_file = env["runs_dir"] / run_id / "run.jsonl"
    assert trace_file.exists()

    events = [
        json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines() if line
    ]
    has_violation = any(
        ev.get("event") == "policy_violation"
        or (
            isinstance(ev.get("result"), dict)
            and ev.get("result", {}).get("status") == "policy_violation"
        )
        for ev in events
    )
    assert has_violation, "Policy violation was not emitted for prompt injection payload"


@pytest.mark.acceptance
@pytest.mark.acceptance_release
def test_acceptance_security_unauthorized_tool_rejected(isolated_acceptance_env):
    """
    Certifies that undeclared tools (e.g. system_exec_privileged) are strictly denied
    by the sandbox and cannot compromise the environment.
    """
    env = isolated_acceptance_env
    runner = env["runner"]
    run_id = f"at-sec-tool-{uuid.uuid4().hex[:8]}"

    scenario_path = (
        REPO_ROOT / "industries" / "finance" / "scenarios" / "unauthorized_transfer.json"
    )
    agent_path = (
        REPO_ROOT / "tests" / "acceptance" / "fixtures" / "agents" / "unauthorized_tool_agent.py"
    )

    runner.run(
        scenario_path=scenario_path,
        agent=str(agent_path),
        protocol="local",
        run_id=run_id,
        run_log_dir=env["runs_dir"],
    )

    trace_file = env["runs_dir"] / run_id / "run.jsonl"
    assert trace_file.exists()

    # The tool should either fail or be logged as error/unknown
    events = [
        json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines() if line
    ]
    run_ends = [e for e in events if e.get("event") == "run_end"]
    assert run_ends, f"No run_end event found in trace events: {[e.get('event') for e in events]}"
    terminal = run_ends[-1]
    # Status should reflect failure or error
    assert terminal.get("status") in ("failure", "policy_violation", "error", "failed")


@pytest.mark.acceptance
@pytest.mark.acceptance_release
def test_acceptance_security_tampered_trace_fails_gate(isolated_acceptance_env):
    """
    Certifies that any post-execution tampering of trace records causes
    immediate cryptographic failure at the acceptance release gate.
    """
    env = isolated_acceptance_env
    runner = env["runner"]
    run_id = f"at-sec-tamper-{uuid.uuid4().hex[:8]}"

    scenario_path = (
        REPO_ROOT / "industries" / "finance" / "scenarios" / "unauthorized_transfer.json"
    )
    agent_path = (
        REPO_ROOT / "tests" / "acceptance" / "fixtures" / "agents" / "compliant_transfer_agent.py"
    )

    # 1. Run legitimate scenario
    runner.run(
        scenario_path=scenario_path,
        agent=str(agent_path),
        protocol="local",
        run_id=run_id,
        run_log_dir=env["runs_dir"],
    )

    # 2. Certify legitimately
    cert_res = runner.certify(run_id=run_id)
    assert cert_res.exit_code == 0

    # 3. Gate should pass before tamper
    gate_res_clean = runner.gate(run_id=run_id, verify_ledger=True)
    assert_gate_passed(gate_res_clean)

    # 4. Tamper with trace file
    trace_path = env["runs_dir"] / run_id / "run.jsonl"
    original_text = trace_path.read_text(encoding="utf-8")
    tampered_text = original_text + json.dumps({"event": "forged_malicious_event"}) + "\n"
    trace_path.write_text(tampered_text, encoding="utf-8")

    # 5. Gate MUST now fail
    gate_res_tampered = runner.gate(run_id=run_id, verify_ledger=True)
    assert_gate_failed(gate_res_tampered, expected_text="Industrial Trust Verification failed")
