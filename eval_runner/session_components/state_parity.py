"""
eval_runner.session_components.state_parity
Transition-based state verification across simulators, shims, and sandbox state.

Verification model (v2 contract):

    precondition -> observed action -> expected transition
        -> actual transition -> postcondition

Evidence records carry the actual before/after values and the assertion result,
not merely a final boolean.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from eval_runner.events import CoreEvents
from eval_runner.utils.path_resolver import PathResolver

logger = logging.getLogger(__name__)

DEFAULT_NUMERICAL_TOLERANCE = 1e-9


class SessionStateParityVerifier:
    """Verifies implicit and explicit state transition assertions with retry logic."""

    def __init__(self, session_manager: Any):
        self.session_manager = session_manager

    async def get_shim_snapshots(self, sandbox: Any, shim_ids: list[str]) -> dict[str, Any]:
        """Queries active simulators for point-in-time state snapshots."""
        simulators = (
            sandbox.get_active_simulators() if hasattr(sandbox, "get_active_simulators") else {}
        )
        shim_snapshots: dict[str, Any] = {}
        if not shim_ids:
            return shim_snapshots

        tasks = []
        valid_ids = []
        for sid in shim_ids:
            shim = simulators.get(sid)
            if shim:
                if hasattr(shim, "get_snapshot"):
                    sn = shim.get_snapshot()
                    if asyncio.iscoroutine(sn):
                        tasks.append(sn)
                        valid_ids.append(sid)
                    else:
                        shim_snapshots[sid] = sn
                elif hasattr(shim, "get_state"):
                    st = shim.get_state()
                    if asyncio.iscoroutine(st):
                        tasks.append(st)
                        valid_ids.append(sid)
                    else:
                        shim_snapshots[sid] = st
                elif hasattr(shim, "state"):
                    shim_snapshots[sid] = shim.state
            else:
                logger.warning(f"      [Session] [Parity] Unknown shim target: {sid}")

        if tasks:
            results = await asyncio.gather(*tasks)
            for vid, res in zip(valid_ids, results, strict=True):
                shim_snapshots[vid] = res

        return shim_snapshots

    @staticmethod
    def _tolerance_for(node: dict[str, Any], assertion: dict[str, Any]) -> float:
        raw = assertion.get("tolerance")
        if raw is None:
            raw = node.get("verification_tolerance")
        try:
            return float(raw) if raw is not None else DEFAULT_NUMERICAL_TOLERANCE
        except (TypeError, ValueError):
            return DEFAULT_NUMERICAL_TOLERANCE

    async def _resolve_target(
        self,
        assertion: dict[str, Any],
        sandbox: Any,
        history: list[dict[str, Any]],
        shim_snapshots: dict[str, Any],
    ) -> tuple[Any, str | None]:
        target = assertion.get("target", "message")
        property_path = assertion.get("property")

        if target.startswith("shim:"):
            raw_target = target.split(":", 1)[1]
            if "." in raw_target:
                shim_id, ext_path = raw_target.split(".", 1)
                actual_val = shim_snapshots.get(shim_id)
                property_path = f"{ext_path}.{property_path}" if property_path else ext_path
            else:
                shim_id = raw_target
                actual_val = shim_snapshots.get(shim_id)
            if actual_val is None:
                # Oracle resolution contract: a declared observation
                # source that does not exist is an INVALID observation, never
                # an observed value of None (which could vacuously match an
                # expected null and produce a false PASS).
                return None, "__unobserved_source__"
            return actual_val, property_path
        if target == "message":
            actual_val = ""
            for item in reversed(history or []):
                if isinstance(item, dict) and item.get("role") in ("agent", "assistant"):
                    content = item.get("content")
                    if isinstance(content, dict):
                        actual_val = (
                            content.get("message")
                            or content.get("content")
                            or content.get("action")
                            or str(content)
                        )
                    elif isinstance(content, str):
                        actual_val = content
                    break
            if not actual_val and hasattr(self.session_manager, "_extract_agent_summary"):
                try:
                    actual_val = self.session_manager._extract_agent_summary(history)
                except Exception as exc:
                    logger.debug("Failed to extract agent summary: %s", exc)
            return actual_val, property_path
        if target == "state":
            actual_val = (
                await sandbox.get_full_state()
                if hasattr(sandbox, "get_full_state")
                else getattr(sandbox, "state", {})
            )
            return actual_val, property_path
        return None, "__unsupported__"

    @staticmethod
    def _match(actual_val: Any, expected: Any, mode: str, tolerance: float) -> bool:
        if mode == "exact":
            return actual_val == expected
        if mode == "regex" or (isinstance(expected, str) and expected.startswith("regex:")):
            pattern = str(expected)[6:] if str(expected).startswith("regex:") else str(expected)
            return bool(re.search(pattern, str(actual_val), re.IGNORECASE))
        if mode == "numerical_tolerance":
            try:
                return abs(float(actual_val) - float(expected)) <= abs(tolerance)
            except (ValueError, TypeError):
                return False
        if mode == "contains":
            if isinstance(expected, list):
                return any(str(e).lower() in str(actual_val).lower() for e in expected)
            return str(expected).lower() in str(actual_val).lower()
        return False

    async def verify_state_parity(
        self,
        node: dict[str, Any],
        sandbox: Any,
        history: list[dict[str, Any]],
        state_before: dict[str, Any] | None = None,
    ) -> tuple[bool, list[dict[str, Any]]]:
        """
        Transition-based verification.

        Returns (all_passed, transition_evidence) where each evidence row records
        the assertion, expected value, before/after observed values and outcome.
        """
        assertions = node.get("expected_outcome", [])
        if not isinstance(assertions, list) or not assertions:
            # "No parity assertions" must be distinguishable from
            # "parity successfully verified": record an explicit
            # NOT_APPLICABLE outcome with its reason in the evidence trail.
            return True, [
                {
                    "assertion": {"target": "__state_parity__"},
                    "outcome": "NOT_APPLICABLE",
                    "passed": True,
                    "reason": (
                        "No expected_outcome assertions declared on this node; "
                        "no state transition verification was required."
                    ),
                }
            ]

        timeout = float(node.get("timeout", 30))
        interval = 2.0
        start_time = asyncio.get_event_loop().time()
        sm = self.session_manager

        logger.info(
            f"      [Session] Starting Implicit Verification Phase "
            f"({len(assertions)} assertions) | Timeout: {timeout}s"
        )

        shim_ids = list(
            {
                a.get("target").split(":", 1)[1].split(".", 1)[0]
                for a in assertions
                if str(a.get("target")).startswith("shim:")
            }
        )

        while True:
            shim_snapshots = await self.get_shim_snapshots(sandbox, shim_ids)
            all_passed = True
            failed_reason = None
            evidence_rows: list[dict[str, Any]] = []

            for assertion in assertions:
                expected = assertion.get("expected")
                mode = assertion.get("mode", "exact")
                tolerance = self._tolerance_for(node, assertion)

                after_val, property_path = await self._resolve_target(
                    assertion, sandbox, history, shim_snapshots
                )
                if property_path == "__unsupported__":
                    all_passed = False
                    failed_reason = f"Unsupported target: {assertion.get('target')}"
                    evidence_rows.append(
                        {
                            "assertion": assertion,
                            "mode": mode,
                            "expected": expected,
                            "actual_before": None,
                            "actual_after": None,
                            "passed": False,
                            "invalid": True,
                            "outcome": "INVALID",
                            "error": failed_reason,
                        }
                    )
                    break

                # A declared observation source that never produced a
                # snapshot is an INVALID oracle resolution, not an observed
                # value — fail closed immediately instead of comparing None.
                if property_path == "__unobserved_source__":
                    all_passed = False
                    failed_reason = (
                        f"Unobservable oracle target '{assertion.get('target')}': "
                        "no active shim/simulator produced a snapshot. Missing "
                        "observation source = INVALID, never an observed value."
                    )
                    evidence_rows.append(
                        {
                            "assertion": assertion,
                            "mode": mode,
                            "expected": expected,
                            "actual_before": None,
                            "actual_after": None,
                            "passed": False,
                            "invalid": True,
                            "outcome": "INVALID",
                            "error": failed_reason,
                        }
                    )
                    break

                before_val = self._before_value(state_before, assertion, property_path)
                resolved_after = (
                    PathResolver.resolve(after_val, property_path)
                    if property_path and not str(property_path).startswith("__")
                    else after_val
                )
                match = self._match(resolved_after, expected, mode, tolerance)

                evidence_rows.append(
                    {
                        "assertion": assertion,
                        "mode": mode,
                        "expected": expected,
                        "actual_before": before_val,
                        "actual_after": resolved_after,
                        "tolerance": tolerance if mode == "numerical_tolerance" else None,
                        "passed": match,
                        "outcome": "PASS" if match else "FAIL",
                    }
                )

                if not match:
                    all_passed = False
                    failed_reason = (
                        f"{assertion.get('target', 'message')}.{property_path or ''} | "
                        f"Expected: {expected} | Actual: {resolved_after} "
                        f"(before: {before_val})"
                    )

            if all_passed:
                logger.info(f"      [Session] [Parity] All {len(assertions)} assertions PASSED.")
                return True, evidence_rows

            if asyncio.get_event_loop().time() - start_time > timeout:
                logger.info(
                    f"      [Session] [Parity-Audit] TIMEOUT reached. Last failure: {failed_reason}"
                )
                if hasattr(sm, "event_bus"):
                    sm.event_bus.emit(
                        CoreEvents.ADAPTER_DEBUG,
                        {
                            "message": f"Parity FAILED after {timeout}s: {failed_reason}",
                            "category": "PARITY_STATE_DIVERGENCE",
                            "is_root_cause": True,
                            # [Strict StateComparison contract] Structured,
                            # fallback-free evidence for debugger rendering.
                            # Consumers must render ONLY these fields; absence
                            # of this object means no structured comparison
                            # exists — never guess from message text.
                            "state_comparison": {
                                "expected": [row.get("expected") for row in evidence_rows],
                                "actual": [row.get("actual_after") for row in evidence_rows],
                                "comparison": {
                                    "kind": "transition_verification",
                                    "failed_assertion": failed_reason,
                                },
                                "assertions": evidence_rows,
                                "source": "state_parity.transition_verification",
                                "timestamp": datetime.now().isoformat(),
                            },
                        },
                    )
                return False, evidence_rows

            await asyncio.sleep(interval)

    @staticmethod
    def _before_value(
        state_before: dict[str, Any] | None,
        assertion: dict[str, Any],
        property_path: str | None,
    ) -> Any:
        """Resolves the precondition value of an assertion target when available."""
        if state_before is None:
            return None
        target = assertion.get("target", "message")
        if target != "state":
            return None
        if not property_path:
            return state_before
        try:
            return PathResolver.resolve(state_before, property_path)
        except Exception as exc:  # noqa: BLE001 - evidence only
            logger.debug("Path resolution failed for before state: %s", exc)
            return None
