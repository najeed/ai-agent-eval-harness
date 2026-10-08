"""
eval_runner.exceptions — Authoritative Exception Hierarchy.
"""

from __future__ import annotations

from eval_runner.run_lifecycle import RunSuspendedForApproval, TraceClosedError


class AirgappedConfigurationError(RuntimeError):
    """
    Raised when an endpoint or provider configuration violates
    strict air-gapped isolation boundaries.
    """


__all__ = [
    "AirgappedConfigurationError",
    "RunSuspendedForApproval",
    "TraceClosedError",
]
