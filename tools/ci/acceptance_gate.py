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
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


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
    """Evaluates acceptance summary against strict release certification thresholds."""
    total = int(summary.get("total_cases", 0))
    passed_cases = int(summary.get("passed_cases", 0))
    failed_cases = int(summary.get("failed_cases", 0))
    fn = int(summary.get("false_negatives", 0))
    fp = int(summary.get("false_positives", 0))
    sec = int(summary.get("security_failures", 0))
    evid = int(summary.get("evidence_failures", 0))
    err = int(summary.get("execution_errors", 0))

    thresholds = (suite or {}).get("thresholds", {})
    expected_case_ids = {Path(str(case)).stem for case in (suite or {}).get("cases", [])}
    observed_case_ids = {str(result.get("case_id", "")) for result in summary.get("results", [])}
    reasons: list[str] = []

    if total == 0:
        reasons.append("Zero acceptance cases evaluated; suite cannot be empty.")
    if failed_cases > 0:
        reasons.append(f"{failed_cases} acceptance test case(s) failed.")
    if expected_case_ids != observed_case_ids:
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
