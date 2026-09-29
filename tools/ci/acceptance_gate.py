#!/usr/bin/env python3
"""
tools/ci/acceptance_gate.py
Authoritative Release Certification Gate for AgentV.

Enforces zero-tolerance release rules against observable acceptance facts:
  - Zero False Negatives (P0 Hard Gate)
  - Zero False Positives (P0 Hard Gate)
  - Zero Security Failures (P0 Hard Gate)
  - Zero Evidence/Ledger Failures (P0 Hard Gate)
  - Zero Execution Errors (P0 Hard Gate)
  - Total Certified Acceptance Cases > 0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from agentv_runtime.canonical import canonical_json_encode

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_expected_oracle_url(value: Any) -> str:
    """Resolve an acceptance manifest environment reference without guessing."""
    if not isinstance(value, str) or not value:
        return ""
    if value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "").rstrip("/")
    return value.rstrip("/")


def _validate_external_oracle_observations(results: list[dict[str, Any]]) -> list[str]:
    """Require one fresh, case/run-bound receipt for every oracle-backed case."""
    reasons: list[str] = []
    seen_receipts: set[str] = set()
    for result in results:
        expected_state = result.get("expected", {}).get("state", {})
        authority_url = _resolve_expected_oracle_url(expected_state.get("oracle_url"))
        if not authority_url:
            continue
        state = result.get("actual", {}).get("state", {})
        binding = state.get("oracle_observation") if isinstance(state, dict) else None
        case_id = str(result.get("case_id") or "")
        run_id = str(result.get("run_id") or "")
        if not isinstance(binding, dict):
            reasons.append(f"CRITICAL: Case {case_id} lacks a bound external oracle observation.")
            continue
        receipt_hash = binding.get("receipt_hash")
        if (
            not isinstance(receipt_hash, str)
            or not receipt_hash
            or receipt_hash != state.get("oracle_receipt_hash")
        ):
            reasons.append(f"CRITICAL: Case {case_id} has an invalid external oracle receipt.")
            continue
        if receipt_hash in seen_receipts:
            reasons.append(f"CRITICAL: External oracle receipt was reused by case {case_id}.")
        seen_receipts.add(receipt_hash)
        if (
            binding.get("case_id") != case_id
            or binding.get("run_id") != run_id
            or binding.get("authority_url") != authority_url
        ):
            reasons.append(
                f"CRITICAL: Case {case_id} external oracle binding does not match "
                "its case/run/authority."
            )
            continue
        final_state = state.get("final_state")
        if not isinstance(final_state, dict):
            reasons.append(
                f"CRITICAL: Case {case_id} external oracle binding lacks observed state."
            )
            continue
        observed_state_hash = (
            "sha3_256:" + hashlib.sha3_256(canonical_json_encode(final_state)).hexdigest()
        )
        if binding.get("observed_state_hash") != observed_state_hash:
            reasons.append(
                f"CRITICAL: Case {case_id} external oracle observed-state hash mismatch."
            )
            continue
        unsigned_binding = {
            key: binding[key]
            for key in ("authority_url", "case_id", "observed_state_hash", "receipt_hash", "run_id")
        }
        binding_hash = (
            "sha3_256:" + hashlib.sha3_256(canonical_json_encode(unsigned_binding)).hexdigest()
        )
        if binding.get("binding_hash") != binding_hash:
            reasons.append(f"CRITICAL: Case {case_id} external oracle binding hash mismatch.")
    return reasons


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    total_cases: int
    passed_cases: int
    failed_cases: int
    false_negatives: int
    false_positives: int
    security_failures: int
    evidence_failures: int
    execution_errors: int
    reasons: list[str]


def evaluate_summary(summary: dict[str, Any], suite: dict[str, Any] | None = None) -> GateDecision:
    """
    Evaluates acceptance summary against strict release certification thresholds
    by independently recomputing all metrics from individual result records.
    """
    raw_results = summary.get("results", [])
    total = len(raw_results)
    passed_cases = sum(1 for r in raw_results if r.get("accepted") is True)
    failed_cases = sum(1 for r in raw_results if not r.get("accepted"))

    fn = 0
    fp = 0
    sec = 0
    evid = 0
    err = 0

    for r in raw_results:
        if not r.get("accepted"):
            exp = r.get("expected", {})
            act = r.get("actual", {})
            exp_dec = str(exp.get("policy", {}).get("decision", "")).upper()
            act_dec = str(act.get("policy", {}).get("decision", "")).upper()
            if exp_dec in {"BLOCK", "REJECT", "REQUIRE_HITL"} and act_dec == "ALLOW":
                fn += 1
            elif exp_dec == "ALLOW" and act_dec in {"BLOCK", "REJECT", "REQUIRE_HITL"}:
                fp += 1
            if r.get("category") == "security":
                sec += 1
            failures = r.get("failures", [])
            if any("evidence" in f.lower() or f.startswith("Required evidence") for f in failures):
                evid += 1
            if any(
                "execution_status" in f.lower() or f.startswith("Expected execution_status")
                for f in failures
            ):
                err += 1

    thresholds = (suite or {}).get("thresholds", {})
    expected_case_ids = {Path(str(case)).stem for case in (suite or {}).get("cases", [])}
    observed_case_ids = {str(result.get("case_id", "")) for result in raw_results}
    reasons: list[str] = []

    claimed_total = int(summary.get("total_cases", 0))
    if claimed_total != total and claimed_total != 0:
        reasons.append(
            f"Summary integrity breach: claimed total_cases={claimed_total} != computed {total}."
        )

    if total == 0:
        reasons.append("Zero acceptance cases evaluated; suite cannot be empty.")
    if failed_cases > 0:
        reasons.append(f"{failed_cases} acceptance test case(s) failed.")
    if expected_case_ids and expected_case_ids != observed_case_ids:
        reasons.append(
            "Suite membership mismatch: "
            f"missing={sorted(expected_case_ids - observed_case_ids)}, "
            f"unexpected={sorted(observed_case_ids - expected_case_ids)}."
        )
    if fn > int(thresholds.get("allow_false_negatives", 0)):
        reasons.append(f"CRITICAL: {fn} False Negative(s) detected. Release blocked.")
    if fp > int(thresholds.get("allow_false_positives", 0)):
        reasons.append(f"CRITICAL: {fp} False Positive(s) detected. Release blocked.")
    if sec > int(thresholds.get("allow_security_failures", 0)):
        reasons.append(f"CRITICAL: {sec} Security Failure(s) detected. Release blocked.")
    if evid > int(thresholds.get("allow_evidence_failures", 0)):
        reasons.append(f"CRITICAL: {evid} Evidence Integrity Failure(s) detected. Release blocked.")
    if err > int(thresholds.get("allow_execution_errors", 0)):
        reasons.append(f"CRITICAL: {err} Execution Error(s) detected. Release blocked.")
    skipped = sum(
        1 for r in raw_results if r.get("skipped") is True or r.get("status") == "skipped"
    )
    if skipped > 0:
        reasons.append(
            f"CRITICAL: {skipped} skipped acceptance test case(s) detected. "
            "Release gate strictly forbids skipped cases."
        )

    require_oracle = (suite or {}).get("require_external_oracle", False) or os.environ.get(
        "AGENTV_REQUIRE_EXTERNAL_ORACLE"
    ) == "1"
    if require_oracle:
        reasons.extend(_validate_external_oracle_observations(raw_results))

    gate_passed = len(reasons) == 0
    return GateDecision(
        passed=gate_passed,
        total_cases=total,
        passed_cases=passed_cases,
        failed_cases=failed_cases,
        false_negatives=fn,
        false_positives=fp,
        security_failures=sec,
        evidence_failures=evid,
        execution_errors=err,
        reasons=reasons,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AgentV Acceptance Release Gate",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="reports/acceptance/latest",
        help="Path to directory containing acceptance-summary.json",
    )
    parser.add_argument(
        "--manifest",
        default="tests/acceptance/manifests/release.yaml",
        help="Authoritative acceptance suite manifest defining cases and thresholds",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON gate evaluation",
    )

    args = parser.parse_args()

    report_p = Path(args.report_dir)
    if not report_p.is_absolute():
        report_p = (REPO_ROOT / report_p).resolve()

    summary_file = report_p / "acceptance-summary.json"
    if not summary_file.exists():
        print(f"[ACCEPTANCE GATE] ERROR: Summary file not found at {summary_file}", file=sys.stderr)
        return 1

    try:
        with open(summary_file, encoding="utf-8") as f:
            summary = json.load(f)
    except Exception as e:
        print(f"[ACCEPTANCE GATE] ERROR: Failed to parse summary: {e}", file=sys.stderr)
        return 1

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = (REPO_ROOT / manifest_path).resolve()
    try:
        suite = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[ACCEPTANCE GATE] ERROR: Invalid suite manifest: {exc}", file=sys.stderr)
        return 1
    decision = evaluate_summary(summary, suite)

    if args.json:
        print(json.dumps(asdict(decision), indent=2))
    else:
        print("\n========================================================")
        print("          AGENTV ACCEPTANCE RELEASE GATE                ")
        print("========================================================")
        print(f"Total Cases Evaluated: {decision.total_cases}")
        print(f"Passed Cases:         {decision.passed_cases}")
        print(f"Failed Cases:         {decision.failed_cases}")
        print("--------------------------------------------------------")
        print(f"False Negatives:      {decision.false_negatives} (Allowed: 0)")
        print(f"False Positives:      {decision.false_positives} (Allowed: 0)")
        print(f"Security Failures:    {decision.security_failures} (Allowed: 0)")
        print(f"Evidence Failures:    {decision.evidence_failures} (Allowed: 0)")
        print(f"Execution Errors:     {decision.execution_errors} (Allowed: 0)")
        print("========================================================")

        if decision.passed:
            print(">>> RELEASE GATE STATUS: [PASSED] ALL THRESHOLDS SATISFIED <<<\n")
        else:
            print(">>> RELEASE GATE STATUS: [FAILED] ZERO-TOLERANCE BREACH <<<\n")
            for r in decision.reasons:
                print(f"  - {r}")
            print()

    return 0 if decision.passed else 1


if __name__ == "__main__":
    sys.exit(main())
