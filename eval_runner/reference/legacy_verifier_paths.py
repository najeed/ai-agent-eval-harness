"""Filesystem compatibility helpers for legacy fixture migration only.

These helpers are deliberately outside Core verification.  Production code
must use ``RunStorageProvider.get_manifest`` and ``get_trace_bytes``.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval_runner import config


def is_plain_execution_manifest(path: Path | str) -> bool:
    """Identify a pre-certification execution manifest in a legacy fixture."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    certificate_markers = {
        "trace_hash",
        "verification_package",
        "provenance_chain",
        "signature",
        "signatures",
        "vc_version",
        "compliance",
        "compliance_status",
        "certificate_hash",
    }
    if certificate_markers.intersection(data):
        return False
    execution_markers = {
        "agent_config",
        "runtime_config",
        "producer_identity",
        "attempt_statistics",
        "pass_at_k",
    }
    return bool(
        str(data.get("manifest_id", "")).startswith("man_")
        or (data.get("scenario_id") and data.get("scenario_hash"))
        or execution_markers.intersection(data)
    )


def locate_certificate_file(run_id: str) -> Path | None:
    """Locate a fixture certificate; not available to production Core code."""
    if not run_id or not isinstance(run_id, str) or ".." in run_id:
        return None
    reports_dir = Path(config.REPORTS_DIR)
    runs_dir = Path(config.RUN_LOG_DIR)
    candidates = (
        reports_dir / "certificates" / f"{run_id}_vc.json",
        runs_dir / run_id / "run_manifest.json",
        runs_dir / run_id / f"{run_id}_certificate.json",
        runs_dir / run_id / f"{run_id}_vc.json",
        reports_dir / "certificates" / f"{run_id}_certificate.json",
    )
    for candidate in candidates:
        if candidate.is_file() and not (
            candidate.name == "run_manifest.json" and is_plain_execution_manifest(candidate)
        ):
            return candidate.resolve()
    return None
