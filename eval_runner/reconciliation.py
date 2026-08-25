"""
eval_runner.reconciliation — [E4] LIVE/HYBRID evidence reconciliation.

For live/hybrid executions the kernel records an independent, per-node
reconciliation of the OBSERVED world state against the DECLARED expectations:

  - SHA3-256 commitments over the exact before/after state snapshots,
  - field-level comparison of every declared `expected_state_changes` entry
    against the observed post-state (no inference: missing fields are
    reported as mismatches),
  - the real captured observation set (tools actually invoked).

The record is appended to the task result as `reconciliation` and therefore
flows into the trace, the verification decision inputs, and evidence packages.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from eval_runner.utils.path_resolver import PathResolver


def _state_hash(state: dict[str, Any] | None) -> str | None:
    if state is None:
        return None
    canonical = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha3_256:{hashlib.sha3_256(canonical.encode()).hexdigest()}"


def build_reconciliation_record(
    *,
    node_id: str,
    execution_mode: str,
    state_before: dict[str, Any] | None,
    state_after: dict[str, Any] | None,
    expected_state_changes: list[dict[str, Any]] | None = None,
    observations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Builds one immutable reconciliation record from REAL observations."""

    checks: list[dict[str, Any]] = []
    for change in expected_state_changes or []:
        path = change.get("path")
        if not path:
            continue
        expected = change.get("value")
        actual = PathResolver.resolve(state_after or {}, path)
        checks.append(
            {
                "path": path,
                "expected": expected,
                "actual": actual,
                "matched": actual == expected,
            }
        )

    return {
        "node_id": node_id,
        "execution_mode": execution_mode,
        "state_hash_before": _state_hash(state_before),
        "state_hash_after": _state_hash(state_after),
        "expected_change_checks": checks,
        "reconciled": bool(checks) and all(c["matched"] for c in checks),
        # Real captured observations only — never synthesized.
        "observations": dict(observations or {}),
    }
