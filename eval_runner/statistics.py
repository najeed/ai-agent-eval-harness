"""
eval_runner.statistics
Standardized evaluation scoring semantics.

Separates materially different aggregate meanings that must never share one number:

  - attempt_success_rate: c / n (raw proportion across executed attempts)
  - pass@k: unbiased estimator P(at least one of k samples passes) =
        1 - prod_{i=0..k-1} (n - c - i) / (n - i)
    computed over n actually-executed attempts (never a requested-but-cancelled k)
  - all_pass / any_pass: conjunctive / disjunctive attempt semantics
  - confidence: Wilson score interval for the success proportion
"""

from __future__ import annotations

import math
from typing import Any

WILSON_Z_95 = 1.959963984540054


def pass_at_k_estimator(n: int, c: int, k: int) -> float:
    """
    Unbiased pass@k estimator (Codex/HumanEval convention).

    n: samples actually executed (n >= 1)
    c: successful samples
    k: requested subset size; clamped to [1, n]
    """
    if n <= 0 or c < 0 or k <= 0:
        return 0.0
    if c > n:
        raise ValueError(f"c ({c}) cannot exceed n ({n})")
    k_eff = min(k, n)
    if c == 0:
        return 0.0
    if n - c < k_eff:
        return 1.0
    log_comb_ratio = sum(math.log(n - c - i) - math.log(n - i) for i in range(k_eff))
    return round(1.0 - math.exp(log_comb_ratio), 10)


def wilson_interval(successes: int, total: int, z: float = WILSON_Z_95) -> dict[str, float]:
    """Wilson score interval for a binomial proportion."""
    if total <= 0:
        return {"lower": 0.0, "upper": 0.0, "confidence_level": 0.95}
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)) / denom
    return {
        "lower": round(max(0.0, center - margin), 6),
        "upper": round(min(1.0, center + margin), 6),
        "confidence_level": 0.95,
    }


def compute_attempt_statistics(
    attempts_results: list[list[dict[str, Any]]],
    is_successful,
    requested_k: int,
) -> dict[str, Any]:
    """
    Computes the full statistics contract over ACTUALLY EXECUTED attempts.

    Cancellation may stop execution early; every statistic here uses
    n = len(attempts_results), never the requested k.
    """
    n = len(attempts_results)
    successful = sum(1 for res in attempts_results if is_successful(res))
    k_requested = max(int(requested_k or 0), 0)
    truncated = n < k_requested

    return {
        "attempt_success_rate": round(successful / n, 10) if n else 0.0,
        "pass_at_k": pass_at_k_estimator(n, successful, k_requested or n),
        "pass_at_k_k": min(k_requested, n) if k_requested else n,
        "all_pass": n > 0 and successful == n,
        "any_pass": successful > 0,
        "successful_attempts": successful,
        "executed_attempts": n,
        "requested_attempts": k_requested,
        "truncated_by_cancellation": truncated,
        "confidence_interval": wilson_interval(successful, n)
        if n
        else {
            "lower": 0.0,
            "upper": 0.0,
            "confidence_level": 0.95,
        },
    }


__all__ = [
    "compute_attempt_statistics",
    "pass_at_k_estimator",
    "wilson_interval",
]
