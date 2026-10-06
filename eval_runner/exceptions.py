"""
eval_runner.exceptions — Authoritative Exception Hierarchy.
"""

from __future__ import annotations

from eval_runner.run_lifecycle import RunSuspendedForApproval, TraceClosedError

__all__ = [
    "RunSuspendedForApproval",
    "TraceClosedError",
]
