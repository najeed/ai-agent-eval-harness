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
import inspect
import logging
import re
from datetime import datetime
from typing import Any

from eval_runner.events import CoreEvents
from eval_runner.reference.field_policy import BasicFieldPolicyEvaluator
from eval_runner.state_authority import bound_state_snapshot, state_authority_registry
from eval_runner.utils.path_resolver import PathResolver

logger = logging.getLogger(__name__)

DEFAULT_NUMERICAL_TOLERANCE = 1e-9


class SessionStateParityVerifier:
    """Verifies implicit and explicit state transition assertions with retry logic."""

    def __init__(self, session_manager: Any):
        self.session_manager = session_manager

    async def get_shim_snapshots(self, sandbox: Any, shim_ids: list[str]) -> dict[str, Any]:
        """Queries active simulators for point-in-time state snapshots."""
        shim_snapshots: dict[str, Any] = {}
        if not shim_ids:
            return shim_snapshots

        simulator_getter = getattr(sandbox, "get_active_simulators", None)
        if not callable(simulator_getter):
            logger.warning("[StateParity] Sandbox does not declare get_active_simulators")
            return shim_snapshots
        simulators = simulator_getter()
        if inspect.isawaitable(simulators):
            simulators = await simulators
        if not isinstance(simulators, dict):
            logger.warning("[StateParity] Sandbox returned an invalid simulator registry")
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
        node: dict[str, Any] | None = None,
    ) -> tuple[Any, str | None]:
        target = assertion.get("target", "message")
        property_path = assertion.get("property")

        # P0-05: External State Authorities (HTTP / REST / MCP observation)
        if (
            str(target).startswith("authority:")
            or str(target).startswith("external:")
            or target in ("external_state", "state_authority")
        ):
            scenario = getattr(self.session_manager, "scenario", {}) or {}
            scenario_authorities = scenario.get("state_authorities") or scenario.get(
                "state_authority"
            )
            if isinstance(scenario_authorities, dict) and "url" in scenario_authorities:
                scenario_authorities = {"default": scenario_authorities}

            target_str = str(target)
            if target_str.startswith("authority:"):
                raw_auth = target_str.split(":", 1)[1]
            elif target_str.startswith("external:"):
                raw_auth = target_str.split(":", 1)[1]
            else:
                raw_auth = "default"

            # Check if property path was appended to target name (e.g. authority:auth_name.prop)
            if (
                "." in raw_auth
                and not raw_auth.startswith("http://")
                and not raw_auth.startswith("https://")
            ):
                auth_name, subpath = raw_auth.split(".", 1)
                property_path = f"{subpath}.{property_path}" if property_path else subpath
            else:
                auth_name = raw_auth

            try:
                connector = state_authority_registry.get_connector(
                    auth_name, scenario_authorities=scenario_authorities
                )
                raw_state = await connector.fetch_state()
            except Exception as auth_err:
                logger.warning(
                    f"[StateParity] External state authority '{auth_name}' observation failed: "
                    f"{auth_err}"
                )
                return None, "__unobserved_source__"

            # P0-06: Apply Bounded State Capture & Projection
            proj = assertion.get("projection") or (node.get("state_projection") if node else None)
            bounded_state, _ = bound_state_snapshot(raw_state, projection=proj)
            return bounded_state, property_path

        # A policy assertion is evaluated against an explicitly declared,
        # independently observable evidence source.  Runtime never infers a
        # policy standard from a target name: control content belongs to a
        # scenario pack / Control Plane, not the execution engine.
        if isinstance(target, str) and target.startswith("policy:"):
            policy_id = target.split(":", 1)[1].strip()
            scenario = getattr(self.session_manager, "scenario", {}) or {}
            policies = (scenario.get("metadata") or {}).get("policies") or {}
            policy_spec = policies.get(policy_id) if isinstance(policies, dict) else None
            if not isinstance(policy_spec, dict):
                logger.warning("[StateParity] Unknown or non-executable policy '%s'", policy_id)
                return None, "__unobserved_source__"
            assertion_oracle_id = assertion.get("id") or assertion.get("oracle_id")
            if (
                policy_spec.get("required") is True
                and policy_spec.get("oracle_id") != assertion_oracle_id
            ):
                logger.warning(
                    "[StateParity] Required policy '%s' has a mismatched oracle ID", policy_id
                )
                return None, "__unobserved_source__"

            evidence_target = policy_spec.get("evidence_target")
            if not isinstance(evidence_target, str) or not evidence_target:
                logger.warning(
                    "[StateParity] Policy '%s' has no explicit observable evidence_target",
                    policy_id,
                )
                return None, "__unobserved_source__"

            evidence_assertion = {
                "target": evidence_target,
                "projection": policy_spec.get("projection"),
            }
            observed, observation_path = await self._resolve_target(
                evidence_assertion, sandbox, history, shim_snapshots, node=node
            )
            if observation_path in ("__unobserved_source__", "__unsupported__") or not isinstance(
                observed, dict
            ):
                logger.warning(
                    "[StateParity] Policy '%s' evidence source '%s' was not observable",
                    policy_id,
                    evidence_target,
                )
                return None, "__unobserved_source__"

            evaluator = BasicFieldPolicyEvaluator()
            eval_res = evaluator.evaluate_policy(policy_spec, observed)
            if property_path == "violations":
                return eval_res.violations, None
            if property_path == "reason":
                return eval_res.reason, None
            return eval_res.allowed, property_path

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
            proj = assertion.get("projection") or (node.get("state_projection") if node else None)
            if not proj and property_path:
                proj = [property_path]
            bounded_getter = getattr(sandbox, "get_bounded_state", None)
            if callable(bounded_getter) and inspect.iscoroutinefunction(bounded_getter):
                if not proj:
                    logger.warning("[StateParity] Unprojected state assertion rejected")
                    return None, "__unobserved_source__"
                raw_val = await bounded_getter(proj)
                if not isinstance(raw_val, dict):
                    # Older third-party sandboxes and loose test doubles can
                    # expose an unimplemented dynamic attribute. They do not
                    # satisfy the bounded-acquisition contract.
                    raw_val = None
            else:
                raw_val = None

            if raw_val is None:
                logger.warning(
                    "[StateParity] State assertion rejected: sandbox does not provide "
                    "a valid bounded-acquisition result"
                )
                return None, "__unobserved_source__"
            bounded_val, _ = bound_state_snapshot(raw_val, projection=proj)
            return bounded_val, property_path
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
                    assertion, sandbox, history, shim_snapshots, node=node
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
                    from agentv_runtime.state_comparison import StateComparison

                    node_id = str(node.get("id") or node.get("node_id") or "unknown_node")
                    exec_instance_id = getattr(
                        sm, "current_execution_instance_id", None
                    ) or getattr(sm, "run_id", "unknown_instance")
                    first_failing = next((r for r in evidence_rows if not r.get("passed")), None)
                    assertion_id = (
                        (
                            (first_failing.get("assertion", {}) or {}).get("id")
                            or (first_failing.get("assertion", {}) or {}).get("target")
                            or (first_failing.get("assertion", {}) or {}).get("property")
                            or "parity_assertion"
                        )
                        if first_failing
                        else "parity_assertion"
                    )

                    st_comp = StateComparison(
                        scenario_node_id=node_id,
                        execution_instance_id=exec_instance_id,
                        assertion_id=str(assertion_id),
                        expected=[row.get("expected") for row in evidence_rows],
                        actual=[row.get("actual_after") for row in evidence_rows],
                        comparison_result="diverged",
                        evidence_ref="run.jsonl",
                        comparison={
                            "kind": "transition_verification",
                            "failed_assertion": failed_reason,
                        },
                        assertions=evidence_rows,
                        source="state_parity.transition_verification",
                        timestamp=datetime.now().isoformat(),
                    )
                    divergence_payload = {
                        "message": f"Parity FAILED after {timeout}s: {failed_reason}",
                        "category": "PARITY_STATE_DIVERGENCE",
                        "is_root_cause": True,
                        "scenario_node_id": node_id,
                        "execution_instance_id": exec_instance_id,
                        "assertion_id": str(assertion_id),
                        "state_comparison": st_comp.to_dict(),
                    }
                    sm.event_bus.emit(CoreEvents.PARITY_STATE_DIVERGENCE, divergence_payload)
                    sm.event_bus.emit(CoreEvents.ADAPTER_DEBUG, divergence_payload)
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
        if (
            target not in ("state", "external_state", "state_authority")
            and not str(target).startswith("authority:")
            and not str(target).startswith("external:")
        ):
            return None
        if not property_path:
            return state_before
        try:
            return PathResolver.resolve(state_before, property_path)
        except Exception as exc:  # noqa: BLE001 - evidence only
            logger.debug("Path resolution failed for before state: %s", exc)
            return None
