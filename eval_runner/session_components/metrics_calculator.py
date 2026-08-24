"""
eval_runner.session_components.metrics_calculator
Calculates evaluation metrics and evaluates state hygiene assertions.

Strict Assertion Semantics (v2 contract):
  - Unknown metric            -> EVALUATION_INVALID (hard failure, never skipped)
  - Malformed criterion       -> EVALUATION_INVALID
  - Evaluator exception       -> EVALUATION_INVALID
  - Required state_hygiene    -> gating: any failed required rule fails the node
  - severity=informational    -> recorded but non-gating (explicit policy only)
"""

from __future__ import annotations

import copy
import inspect
import logging
from typing import Any

from eval_runner import metrics
from eval_runner.events import CoreEvents
from eval_runner.utils.path_resolver import PathResolver

logger = logging.getLogger(__name__)

EVALUATION_INVALID = "EVALUATION_INVALID"


class SessionMetricsCalculator:
    """Evaluates task metrics, state hygiene rules, and formats execution summaries."""

    def __init__(self, session_manager: Any):
        self.session_manager = session_manager

    @staticmethod
    def extract_agent_summary(history: list[dict[str, Any]]) -> str:
        """Extracts the latest agent text summary from conversation history."""
        agent_msgs = [m for m in history if m.get("role") == "agent"]
        if not agent_msgs:
            return ""
        last_content = agent_msgs[-1].get("content", "")
        if isinstance(last_content, dict):
            return (
                last_content.get("summary")
                or last_content.get("instructions")
                or last_content.get("message")
                or last_content.get("content")
                or ""
            )
        return str(last_content)

    async def calculate_metrics(
        self,
        node: dict[str, Any],
        attempt_number: int,
        turns: int,
        history: list[dict[str, Any]],
        sandbox: Any,
        actions: dict[str, Any],
    ) -> dict[str, Any]:
        node_id = node.get("id")
        sm = self.session_manager

        results: dict[str, Any] = {
            "task_id": node_id,
            "attempt": attempt_number,
            "turns_taken": turns,
            "conversation_history": history,
            "metrics": [],
            "evaluation_valid": True,
            "invalid_reasons": [],
            "protocol_sequence": list(getattr(sm, "protocol_sequence", [])),
            "state_snapshots": list(getattr(sm, "state_snapshots", [])),
            "resource_telemetry": list(getattr(sm, "resource_telemetry", [])),
            "tool_registry": (
                sm._extract_tool_registry() if hasattr(sm, "_extract_tool_registry") else {}
            ),
        }

        def _invalidate(reason: str) -> None:
            results["evaluation_valid"] = False
            results["triage_tag"] = EVALUATION_INVALID
            if reason not in results["invalid_reasons"]:
                results["invalid_reasons"].append(reason)

        # v1.2 Hardened Metrics -> v2 Gating State Hygiene assertions
        sh = node.get("state_hygiene", {})
        if sh:
            if hasattr(sm, "event_bus"):
                sm.event_bus.emit(
                    CoreEvents.STEP_START,
                    {"step_name": "state_hygiene_check"},
                    span_context=sm.session_metadata.get("span_context"),
                )

            hygiene_results = []
            for rule in sh.get("rules", []):
                path = rule.get("path")
                expected = rule.get("expected")
                op = rule.get("op", "eq")

                val = PathResolver.resolve(getattr(sandbox, "state", {}), path)

                success = False
                if op == "eq":
                    success = val == expected
                elif op == "exists":
                    success = val is not None
                elif op == "not_exists":
                    success = val is None
                elif op == "contains":
                    success = expected in val if val else False

                hygiene_results.append(
                    {
                        "path": path,
                        "op": op,
                        "expected": expected,
                        "actual": val,
                        "success": success,
                        "severity": rule.get("severity", "required"),
                    }
                )

            if hygiene_results:
                results["state_hygiene"] = hygiene_results
                failed_required = [
                    r
                    for r in hygiene_results
                    if not r["success"] and r["severity"] != "informational"
                ]
                if failed_required:
                    _invalidate(
                        "Required state_hygiene assertions failed: "
                        + ", ".join(f"{r['path']} ({r['op']})" for r in failed_required)
                    )
            if hasattr(sm, "event_bus"):
                sm.event_bus.emit(
                    CoreEvents.STEP_END,
                    {"step_name": "state_hygiene_check"},
                    span_context=sm.session_metadata.get("span_context"),
                )

        criteria = node.get("success_criteria", [])
        expected_outcome = node.get("expected_outcome")

        # Malformed criteria block => the evaluator itself is invalid.
        if criteria and not isinstance(criteria, list):
            _invalidate("success_criteria must be a list of criterion objects")
            criteria = []

        for criterion in criteria:
            try:
                if not isinstance(criterion, dict) or not criterion.get("metric"):
                    _invalidate(f"Malformed success criterion (missing 'metric'): {criterion!r}")
                    continue

                m_name = criterion.get("metric")
                threshold = criterion.get("threshold", 1.0)
                metric_func = metrics.MetricRegistry.get(m_name)

                if not metric_func:
                    _invalidate(
                        f"Unknown metric '{m_name}' referenced in success_criteria "
                        f"(threshold={threshold})."
                    )
                    results["metrics"].append(
                        {
                            "metric": m_name,
                            "status": EVALUATION_INVALID,
                            "score": None,
                            "threshold": threshold,
                            "success": False,
                            "reason": f"Metric '{m_name}' is not registered",
                        }
                    )
                    continue

                summary = self.extract_agent_summary(history)

                eval_context = criterion.copy()
                if "expected" not in eval_context and isinstance(expected_outcome, list):
                    primary_msg = next(
                        (a["expected"] for a in expected_outcome if a.get("target") == "message"),
                        None,
                    )
                    eval_context["expected"] = primary_msg

                async def _invoke(func, *args, **kwargs):
                    if inspect.iscoroutinefunction(func):
                        return await func(*args, **kwargs)
                    return func(*args, **kwargs)

                sig = inspect.signature(metric_func)
                params = sig.parameters

                m_source = metrics.MetricRegistry.get_source(m_name)
                is_core = m_source == "CORE"
                provenance = getattr(sm.plugin_manager, "provenance_map", {}).get(m_source, {})
                is_trusted = is_core or provenance.get("trusted", False)

                def get_isolated(key, data, _params=params, _is_core=is_core):
                    if key in _params and not _is_core and isinstance(data, (dict, list)):
                        return copy.deepcopy(data)
                    return data

                context_map = {
                    "criterion": eval_context,
                    "eval_context": eval_context,
                    "summary": summary,
                    "agent_summary": summary,
                    "history": get_isolated("history", history),
                    "conversation_history": get_isolated("conversation_history", history),
                    "identifier": getattr(sm, "identifier", "unknown"),
                    "actual_state": get_isolated("actual_state", getattr(sandbox, "state", {})),
                    "sandbox_state": get_isolated("sandbox_state", getattr(sandbox, "state", {})),
                    "actual_tools": actions.get("used_tools", []),
                    "used_tools": actions.get("used_tools", []),
                    "expected_tools": node.get("required_tools", []),
                    "required_tools": node.get("required_tools", []),
                    "expected_changes": node.get("expected_state_changes", []),
                    "expected_state_changes": node.get("expected_state_changes", []),
                    "turns_taken": turns,
                    "max_turns": getattr(sm, "max_turns", 10),
                    "attempt_number": attempt_number,
                    "expected": eval_context.get("expected"),
                    "actual": summary,
                    "agent_sequence": [
                        m.get("agent_id") for m in history if m.get("role") == "agent"
                    ],
                    "protocol_sequence": list(getattr(sm, "protocol_sequence", [])),
                    "metadata": getattr(sm, "scenario", {}).get("metadata", {}),
                    "action_trace": actions,
                }

                if is_trusted:
                    context_map["session_metadata"] = getattr(sm, "session_metadata", {})
                    context_map["forensic_telemetry"] = getattr(
                        sm.forensics, "resource_telemetry", []
                    )

                kwargs = {}
                for p_name in params:
                    if p_name in context_map:
                        kwargs[p_name] = context_map[p_name]

                score = await _invoke(metric_func, **kwargs)

                results["metrics"].append(
                    {
                        "metric": m_name,
                        "score": score,
                        "threshold": threshold,
                        "success": score >= threshold,
                    }
                )
                if hasattr(sm, "event_bus"):
                    sm.event_bus.emit(
                        CoreEvents.ADAPTER_DEBUG,
                        {"message": f"[Metric] {m_name}: {score:.2f} (Threshold: {threshold})"},
                    )
            except Exception as e:
                metric_name = (
                    criterion.get("metric") if isinstance(criterion, dict) else str(criterion)
                )
                _invalidate(f"Evaluator exception while computing metric '{metric_name}': {e}")
                results["metrics"].append(
                    {
                        "metric": metric_name,
                        "status": EVALUATION_INVALID,
                        "score": None,
                        "threshold": criterion.get("threshold", 1.0)
                        if isinstance(criterion, dict)
                        else 1.0,
                        "success": False,
                        "reason": str(e),
                    }
                )
                logger.error("      [Metric Invalid] %s: %s (%s)", node_id, metric_name, e)

        return results
