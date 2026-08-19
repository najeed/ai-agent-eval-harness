"""
eval_runner.session_components.state_parity
Verifies point-in-time state parity across simulators, shims, and sandbox state.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from eval_runner.events import CoreEvents
from eval_runner.utils.path_resolver import PathResolver

logger = logging.getLogger(__name__)


class SessionStateParityVerifier:
    """Verifies implicit and explicit state parity assertions with retry logic."""

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

    async def verify_state_parity(
        self, node: dict[str, Any], sandbox: Any, history: list[dict[str, Any]]
    ) -> bool:
        assertions = node.get("expected_outcome", [])
        if not isinstance(assertions, list) or not assertions:
            return True

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

            for assertion in assertions:
                target = assertion.get("target", "message")
                expected = assertion.get("expected")
                property_path = assertion.get("property")
                mode = assertion.get("mode", "exact")

                if target.startswith("shim:"):
                    raw_target = target.split(":", 1)[1]
                    if "." in raw_target:
                        shim_id = raw_target.split(".", 1)[0]
                        property_path_ext = raw_target.split(".", 1)[1]
                        actual_val = shim_snapshots.get(shim_id)
                        if property_path:
                            property_path = f"{property_path_ext}.{property_path}"
                        else:
                            property_path = property_path_ext
                    else:
                        shim_id = raw_target
                        actual_val = shim_snapshots.get(shim_id)
                elif target == "message":
                    actual_val = (
                        sm._extract_agent_summary(history)
                        if hasattr(sm, "_extract_agent_summary")
                        else ""
                    )
                elif target == "state":
                    actual_val = (
                        await sandbox.get_full_state()
                        if hasattr(sandbox, "get_full_state")
                        else getattr(sandbox, "state", {})
                    )
                else:
                    logger.warning(
                        f"      [Session] [Parity] Unsupported assertion target: {target}"
                    )
                    all_passed = False
                    failed_reason = f"Unsupported target: {target}"
                    break

                if property_path:
                    actual_val = PathResolver.resolve(actual_val, property_path)

                match = False
                if mode == "exact":
                    match = actual_val == expected
                elif mode == "regex" or (
                    isinstance(expected, str) and expected.startswith("regex:")
                ):
                    pattern = (
                        str(expected)[6:] if str(expected).startswith("regex:") else str(expected)
                    )
                    match = bool(re.search(pattern, str(actual_val), re.IGNORECASE))
                elif mode == "numerical_tolerance":
                    try:
                        match = abs(float(actual_val) - float(expected)) < 1e-9
                    except (ValueError, TypeError):
                        match = False
                elif mode == "contains":
                    if isinstance(expected, list):
                        match = any(str(e).lower() in str(actual_val).lower() for e in expected)
                    else:
                        match = str(expected).lower() in str(actual_val).lower()

                if not match:
                    all_passed = False
                    failed_reason = (
                        f"{target}.{property_path or ''} | "
                        f"Expected: {expected} | Actual: {actual_val}"
                    )
                    break

            if all_passed:
                logger.info(f"      [Session] [Parity] All {len(assertions)} assertions PASSED.")
                return True

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
                        },
                    )
                return False

            await asyncio.sleep(interval)
