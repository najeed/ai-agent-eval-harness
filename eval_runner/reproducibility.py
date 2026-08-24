"""
eval_runner.reproducibility
Explicit evaluation reproducibility contract (P1 #16).

Deterministic evaluation cannot rely on seed propagation alone. Every run must
publish a fingerprint binding:

    scenario_version + executor_version + adapter_version
        + environment_fingerprint + model/provider configuration
        + seed + input fixture hashes

NIST TEVV favors repeatable, measurable evaluation over opaque pass/fail.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from typing import Any


def _canonical_hash(obj: Any) -> str:
    canonical = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def build_reproducibility_contract(
    scenario: dict[str, Any],
    resolved_config: Any = None,
    seed: int | None = None,
    attempts: int = 1,
    execution_mode: str | None = None,
    adapter_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Builds the immutable reproducibility descriptor for an evaluation run.
    Pure function of its inputs; no ambient state beyond the interpreter version.
    """
    from . import config as harness_config

    adapter_meta = dict(adapter_metadata or {})
    scenario_meta = scenario.get("metadata", {}) if isinstance(scenario, dict) else {}

    contract = {
        "contract_version": "1.0.0",
        "executor_version": getattr(harness_config, "VERSION", "unknown"),
        "execution_ir_version": "2.0.0",
        "scenario_version": _canonical_hash(
            {k: v for k, v in (scenario or {}).items() if k != "run_id"}
        ),
        "scenario_id": (scenario or {}).get("id") or scenario_meta.get("name"),
        "adapter": {
            "protocol": adapter_meta.get("protocol"),
            "endpoint": adapter_meta.get("agent"),
            "adapter_version": adapter_meta.get("adapter_version"),
            "provider_model": adapter_meta.get("model") or scenario_meta.get("model") or None,
        },
        "environment_fingerprint": {
            "python": sys.version.split(" ", 1)[0],
            "platform": platform.platform(),
            "executable": sys.executable,
        },
        "seed": seed,
        "seeding_strategy": "base_seed_plus_attempt_index" if seed is not None else "none",
        "attempts_requested": attempts,
        "input_fixture_hashes": {
            "tools": _canonical_hash((scenario or {}).get("tools", {})),
            "initial_state": _canonical_hash((scenario or {}).get("initial_state", {})),
            "workflow": _canonical_hash((scenario or {}).get("workflow", {})),
        },
        "config_hash": getattr(resolved_config, "config_hash", None),
    }
    if execution_mode:
        contract["execution_mode"] = execution_mode
    return contract


def fingerprint(contract: dict[str, Any]) -> str:
    """Single stable digest over the full reproducibility contract."""
    core = {k: v for k, v in contract.items() if k != "fingerprint"}
    return _canonical_hash(core)


__all__ = ["build_reproducibility_contract", "fingerprint"]
