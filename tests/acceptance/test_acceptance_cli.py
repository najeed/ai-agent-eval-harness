"""
tests.acceptance.test_acceptance_cli
Product-Level CLI Contract Tests Certifying Public Commands and Error Boundaries.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from tests.acceptance.support.assertions import assert_gate_failed, assert_gate_passed

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.acceptance
def test_acceptance_cli_run_help(isolated_acceptance_env):
    """Certifies that --help works on the CLI entry point."""
    runner = isolated_acceptance_env["runner"]
    res = runner._exec(["--help"])
    assert res.exit_code == 0
    assert "agentv" in res.stdout or "evaluation" in res.stdout.lower()


@pytest.mark.acceptance
def test_acceptance_cli_run_nonexistent_scenario(isolated_acceptance_env):
    """Certifies that running a non-existent scenario path fails fast with clear error."""
    runner = isolated_acceptance_env["runner"]
    res = runner.run(scenario_path="nonexistent/scenario.json")
    assert res.exit_code != 0


@pytest.mark.acceptance
def test_acceptance_cli_certify_missing_run_id(isolated_acceptance_env):
    """Certifies that certify fails if run_id does not exist."""
    runner = isolated_acceptance_env["runner"]
    res = runner.certify(run_id="non-existent-run-id-999")
    assert res.exit_code != 0
    err_msg = res.stdout.lower() + "\n" + res.stderr.lower()
    assert "not found" in err_msg or res.exit_code == 1


@pytest.mark.acceptance
def test_acceptance_cli_gate_missing_run_id(isolated_acceptance_env):
    """Certifies that gate rejects a non-existent run ID."""
    runner = isolated_acceptance_env["runner"]
    res = runner.gate(run_id="non-existent-run-id-999")
    assert_gate_failed(res)


@pytest.mark.acceptance
def test_acceptance_cli_full_chain(isolated_acceptance_env):
    """Certifies end-to-end CLI workflow: run -> certify -> verify -> gate."""
    env = isolated_acceptance_env
    runner = env["runner"]
    run_id = f"at-cli-chain-{uuid.uuid4().hex[:8]}"

    scenario_path = (
        REPO_ROOT / "industries" / "finance" / "scenarios" / "unauthorized_transfer.json"
    )
    agent_path = (
        REPO_ROOT / "tests" / "acceptance" / "fixtures" / "agents" / "compliant_transfer_agent.py"
    )

    # 1. run
    run_res = runner.run(
        scenario_path=scenario_path,
        agent=str(agent_path),
        protocol="local",
        run_id=run_id,
        run_log_dir=env["runs_dir"],
    )
    assert run_res.exit_code == 0

    # 2. certify
    cert_res = runner.certify(run_id=run_id)
    assert cert_res.exit_code == 0
    assert "Verification Certificate generated" in cert_res.stdout

    # 3. verify
    trace_path = env["runs_dir"] / run_id / "run.jsonl"
    manifest_path = env["runs_dir"] / run_id / "run_manifest.json"
    verify_res = runner.verify(
        trace_path=trace_path, manifest_path=manifest_path, verify_ledger=True
    )
    assert verify_res.exit_code == 0

    # 4. gate
    gate_res = runner.gate(run_id=run_id, verify_ledger=True)
    assert_gate_passed(gate_res)
