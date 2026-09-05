"""
tests.acceptance.test_acceptance_corpus
Authoritative End-to-End Acceptance Test Suite and Corpus Sentinel.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from tests.acceptance.result import AcceptanceResult
from tests.acceptance.support.artifact_reader import load_run_artifacts, normalize_actual_result
from tests.acceptance.support.case_loader import discover_corpus_cases, load_manifest
from tests.acceptance.support.oracle import compare_expectations

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ALL_CASES = discover_corpus_cases()


# ---------------------------------------------------------------------------
# 1. Corpus-Level Inventory Sentinel
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
def test_acceptance_corpus_inventory():
    """
    Corpus-level architectural sentinel enforcing:
    - Every case validates against acceptance_case.schema.json
    - Every required category has >= 1 case
    - No duplicate IDs across the corpus
    - Every referenced scenario path exists on disk
    - Every referenced agent fixture path exists on disk
    - Release manifest references valid cases
    """
    cases = discover_corpus_cases()
    assert len(cases) >= 4, f"Acceptance corpus must contain >= 4 cases, found {len(cases)}"

    # Required categories check
    required_categories = {
        "pass",
        "fail",
        "false_positive",
        "false_negative",
        "security",
        "resilience",
        "multi_agent",
        "hitl",
        "evidence",
    }
    found_categories = {c.get("category") for c in cases}
    missing_cats = required_categories - found_categories
    assert not missing_cats, f"Acceptance corpus missing mandatory categories: {missing_cats}"

    # Unique IDs check
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), f"Duplicate case IDs found: {ids}"

    # File existence checks
    for c in cases:
        scen_p = REPO_ROOT / c["scenario"]["path"]
        assert scen_p.exists(), f"Case {c['id']} points to missing scenario: {scen_p}"

        agent_p = c["scenario"].get("agent")
        if agent_p:
            resolved_agent = REPO_ROOT / agent_p
            assert resolved_agent.exists(), (
                f"Case {c['id']} points to missing agent fixture: {resolved_agent}"
            )

    # Manifest validity check
    release_manifest_path = REPO_ROOT / "tests" / "acceptance" / "manifests" / "release.yaml"
    assert release_manifest_path.exists(), f"Missing release manifest: {release_manifest_path}"
    manifest = load_manifest(release_manifest_path)
    assert len(manifest["loaded_cases"]) >= 4, "Release manifest contains fewer than 4 cases"


# ---------------------------------------------------------------------------
# 2. Parametrized Acceptance Execution
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
@pytest.mark.acceptance_release
@pytest.mark.parametrize("case", ALL_CASES, ids=[c["id"] for c in ALL_CASES])
def test_agentv_acceptance_case(case, isolated_acceptance_env, acceptance_aggregator):
    """
    Executes an acceptance test case against the observable AgentV product contract.
    """
    env = isolated_acceptance_env
    runner = env["runner"]

    # 1. Setup isolated Run ID
    scenario_cfg = case["scenario"]
    scenario_rel_path = scenario_cfg["path"]
    scenario_full_path = REPO_ROOT / scenario_rel_path
    agent_path = (REPO_ROOT / scenario_cfg["agent"]) if scenario_cfg.get("agent") else None
    run_id = f"at-{case['id'].lower()}-{uuid.uuid4().hex[:8]}"

    # 2. Execute Scenario via CLI
    run_res = runner.run(
        scenario_path=scenario_full_path,
        agent=str(agent_path) if agent_path else None,
        protocol=scenario_cfg.get("protocol", "local"),
        seed=scenario_cfg.get("seed", 1000),
        attempts=scenario_cfg.get("attempts", 1),
        run_id=run_id,
        run_log_dir=env["runs_dir"],
    )

    # 3. If certification is expected, execute certify CLI
    expect_cfg = case["expect"]
    cert_res = None
    if expect_cfg.get("evidence", {}).get("certificate_required", False):
        cert_res = runner.certify(run_id=run_id)

    # 4. Gate verification check
    gate_res = runner.gate(run_id=run_id, verify_ledger=True)

    # 5. Read Observable Artifacts
    artifacts = load_run_artifacts(
        run_id=run_id,
        repo_root=REPO_ROOT,
        custom_run_dir=env["runs_dir"],
        custom_reports_dir=env["reports_dir"],
    )

    # 6. Normalize Actual Results
    actual = normalize_actual_result(
        artifacts=artifacts,
        cli_gate_exit_code=gate_res.exit_code,
        cli_verify_exit_code=0 if (cert_res and cert_res.exit_code == 0) else None,
    )

    # 7. Independent Oracle Evaluation
    oracle_failures = compare_expectations(expected=expect_cfg, actual=actual)
    failure_messages = tuple(f.reason for f in oracle_failures)
    is_accepted = len(oracle_failures) == 0

    # 8. Record Acceptance Result
    result = AcceptanceResult(
        case_id=case["id"],
        accepted=is_accepted,
        expected=expect_cfg,
        actual=actual,
        failures=failure_messages,
        run_id=run_id,
        agentv_version="2.0.0",
        git_commit="head",
        evidence_verified=artifacts.has_trace,
        certificate_verified=artifacts.has_certificate and gate_res.exit_code == 0,
        ledger_verified=gate_res.exit_code == 0,
    )
    acceptance_aggregator.add_result(result)

    # 9. Assert Outcome
    if expect_cfg["acceptance"] == "PASS":
        c_code = cert_res.exit_code if cert_res else "N/A"
        c_out = cert_res.stdout if cert_res else ""
        c_err = cert_res.stderr if cert_res else ""
        cert_out = f"Certify CLI Output (exit={c_code}):\n{c_out}\n{c_err}"
        gate_out = (
            f"Gate CLI Output (exit={gate_res.exit_code}):\n{gate_res.stdout}\n{gate_res.stderr}"
        )
        assert is_accepted, (
            f"Acceptance case {case['id']} FAILED product contract!\n"
            f"Oracle Discrepancies:\n"
            + "\n".join(f"  - {f.dimension}: {f.reason}" for f in oracle_failures)
            + f"\nRun CLI Output (exit={run_res.exit_code}):\n{run_res.stdout}\n{run_res.stderr}\n"
            + f"{cert_out}\n{gate_out}"
        )
    else:
        assert not is_accepted, f"Acceptance case {case['id']} was expected to fail, but passed."
