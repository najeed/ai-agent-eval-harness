"""
tests.acceptance.support.artifact_reader
Authoritative reader and outcome normalizer for AgentV evidence artifacts and vaults.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .trace_reader import TraceReader


class RunArtifacts:
    """Encapsulates observable artifacts produced by an AgentV run."""

    def __init__(
        self,
        run_id: str,
        run_vault_dir: Path,
        trace_path: Path,
        manifest_path: Path | None,
        sealed_path: Path | None,
        certificate_path: Path | None,
        trace_reader: TraceReader,
    ):
        self.run_id = run_id
        self.run_vault_dir = run_vault_dir
        self.trace_path = trace_path
        self.manifest_path = manifest_path
        self.sealed_path = sealed_path
        self.certificate_path = certificate_path
        self.trace_reader = trace_reader

    @property
    def has_trace(self) -> bool:
        return self.trace_path.exists()

    @property
    def has_manifest(self) -> bool:
        return self.manifest_path is not None and self.manifest_path.exists()

    @property
    def is_sealed(self) -> bool:
        return self.sealed_path is not None and self.sealed_path.exists()

    @property
    def has_certificate(self) -> bool:
        return self.certificate_path is not None and self.certificate_path.exists()

    def get_manifest(self) -> dict[str, Any]:
        if not self.has_manifest:
            return {}
        with open(self.manifest_path, encoding="utf-8") as f:
            return json.load(f)

    def get_certificate(self) -> dict[str, Any]:
        if not self.has_certificate:
            return {}
        with open(self.certificate_path, encoding="utf-8") as f:
            return json.load(f)


def load_run_artifacts(
    run_id: str,
    repo_root: str | Path | None = None,
    custom_run_dir: str | Path | None = None,
    custom_reports_dir: str | Path | None = None,
) -> RunArtifacts:
    """Locate and assemble all observable artifacts for a given run ID."""
    root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
    runs_dir = Path(custom_run_dir).resolve() if custom_run_dir else (root / "runs")
    reports_dir = Path(custom_reports_dir).resolve() if custom_reports_dir else (root / "reports")

    vault_dir = runs_dir / run_id
    trace_path = vault_dir / "run.jsonl"
    manifest_path = vault_dir / "run_manifest.json"
    sealed_path = vault_dir / ".sealed"
    certificate_path = reports_dir / "certificates" / f"{run_id}_vc.json"

    trace_reader = TraceReader(trace_path)
    return RunArtifacts(
        run_id=run_id,
        run_vault_dir=vault_dir,
        trace_path=trace_path,
        manifest_path=manifest_path if manifest_path.exists() else None,
        sealed_path=sealed_path if sealed_path.exists() else None,
        certificate_path=certificate_path if certificate_path.exists() else None,
        trace_reader=trace_reader,
    )


def normalize_actual_result(
    artifacts: RunArtifacts,
    cli_gate_exit_code: int | None = None,
    cli_verify_exit_code: int | None = None,
) -> dict[str, Any]:
    """
    Extracts independently observable facts into a normalized result matching
    the acceptance expectations contract.
    """
    trace = artifacts.trace_reader
    exec_status = trace.execution_status

    # Policy decision determination
    policy_decisions = trace.policy_decisions
    decision = "ALLOW"
    for p in policy_decisions:
        dec = p.get("decision", "").upper()
        if dec in ("BLOCK", "REJECT", "REQUIRE_HITL"):
            decision = dec
            break

    # Commit allowed determination:
    # If policy was blocked/rejected/paused for HITL or execution failed due to violation,
    # commit was not allowed
    commit_allowed = True
    if decision in ("BLOCK", "REJECT", "REQUIRE_HITL") or exec_status == "policy_violation":
        commit_allowed = False

    # Verification success determination
    # Reflects whether the agent/scenario behavior verified compliant/pass (vs caught and failed)
    verification_success = False
    manifest = artifacts.get_manifest()
    if manifest:
        compliance = manifest.get("compliance", {})
        compliance_status = str(compliance.get("status", "")).lower()
        if compliance_status in ("pass", "passed", "success"):
            verification_success = True
        elif compliance_status in ("fail", "failed"):
            verification_success = False
        else:
            verification_success = float(compliance.get("score", 0.0)) >= 1.0
    elif exec_status in ("success", "passed"):
        verification_success = True

    return {
        "execution_status": exec_status,
        "verification_success": verification_success,
        "state": {
            "commit_allowed": commit_allowed,
        },
        "policy": {
            "decision": decision,
        },
        "evidence": {
            "required": artifacts.has_trace,
            "certificate_required": artifacts.has_certificate,
            "ledger_verification_required": (
                (cli_gate_exit_code == 0)
                if cli_gate_exit_code is not None
                else (cli_verify_exit_code == 0 if cli_verify_exit_code is not None else False)
            ),
            "sealed_required": artifacts.is_sealed,
        },
    }


__all__ = ["RunArtifacts", "load_run_artifacts", "normalize_actual_result"]
