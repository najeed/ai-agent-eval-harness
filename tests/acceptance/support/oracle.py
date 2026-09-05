"""
tests.acceptance.support.oracle
Authoritative independent oracle comparing observable product outcomes against acceptance contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OracleFailure:
    """Individual discrepancy identified by the acceptance oracle."""

    dimension: str
    expected: Any
    actual: Any
    reason: str


def compare_expectations(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[OracleFailure]:
    """
    Compares independently observed facts against the acceptance case contract.
    Never relies on the agent's self-reported success or internal harness claims.
    """
    failures: list[OracleFailure] = []

    # 1. Verification Success Dimension
    if "verification_success" in expected:
        exp_verif = expected["verification_success"]
        act_verif = actual.get("verification_success")
        if exp_verif != act_verif:
            failures.append(
                OracleFailure(
                    dimension="verification_success",
                    expected=exp_verif,
                    actual=act_verif,
                    reason=f"Expected verification_success={exp_verif}, got {act_verif}",
                )
            )

    # 2. Execution Status Dimension
    if "execution_status" in expected:
        exp_status = expected["execution_status"]
        act_status = actual.get("execution_status")
        if exp_status != act_status:
            failures.append(
                OracleFailure(
                    dimension="execution_status",
                    expected=exp_status,
                    actual=act_status,
                    reason=f"Expected execution_status='{exp_status}', got '{act_status}'",
                )
            )

    # 3. State Parity / Mutation Commit Dimension
    if "state" in expected and "commit_allowed" in expected["state"]:
        exp_commit = expected["state"]["commit_allowed"]
        act_commit = actual.get("state", {}).get("commit_allowed")
        if exp_commit != act_commit:
            failures.append(
                OracleFailure(
                    dimension="state.commit_allowed",
                    expected=exp_commit,
                    actual=act_commit,
                    reason=f"Expected state commit_allowed={exp_commit}, got {act_commit}",
                )
            )

    # 4. Policy Decision Dimension
    if "policy" in expected and "decision" in expected["policy"]:
        exp_decision = expected["policy"]["decision"].upper()
        act_decision = actual.get("policy", {}).get("decision", "").upper()
        if exp_decision != act_decision:
            failures.append(
                OracleFailure(
                    dimension="policy.decision",
                    expected=exp_decision,
                    actual=act_decision,
                    reason=f"Expected policy decision '{exp_decision}', got '{act_decision}'",
                )
            )

    # 5. Evidence Integrity Dimension
    if "evidence" in expected:
        exp_ev = expected["evidence"]
        act_ev = actual.get("evidence", {})

        if exp_ev.get("required") and not act_ev.get("required"):
            failures.append(
                OracleFailure(
                    dimension="evidence.required",
                    expected=True,
                    actual=act_ev.get("required"),
                    reason="Required execution trace run.jsonl was not found",
                )
            )

        if exp_ev.get("certificate_required") and not act_ev.get("certificate_required"):
            failures.append(
                OracleFailure(
                    dimension="evidence.certificate_required",
                    expected=True,
                    actual=act_ev.get("certificate_required"),
                    reason="Required verification certificate was missing or unverified",
                )
            )

        if exp_ev.get("sealed_required") and not act_ev.get("sealed_required"):
            failures.append(
                OracleFailure(
                    dimension="evidence.sealed_required",
                    expected=True,
                    actual=act_ev.get("sealed_required"),
                    reason="Required .sealed vault sentinel was not present",
                )
            )

        need_ledger = exp_ev.get("ledger_verification_required")
        if need_ledger and not act_ev.get("ledger_verification_required"):
            failures.append(
                OracleFailure(
                    dimension="evidence.ledger_verification_required",
                    expected=True,
                    actual=act_ev.get("ledger_verification_required"),
                    reason="Required evidence ledger cryptographic verification failed",
                )
            )

    return failures


__all__ = ["OracleFailure", "compare_expectations"]
