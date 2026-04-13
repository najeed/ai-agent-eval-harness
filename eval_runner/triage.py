"""
triage.py

Industrial Triage Engine (AES v1.5).
Categorizes and explains evaluation failures using a weighted evidence model.
"""

from __future__ import annotations

from typing import Any

from .taxonomy import FailureCategory, FailureTaxonomy


class Confidence:
    """Industrial Confidence Levels for Forensic Attribution."""

    CERTAIN = 1.0  # Explicit status or forensic report
    HIGH = 0.95  # Pattern-matched with evidence
    MEDIUM_HIGH = 0.85  # Sequential logic derivation
    MEDIUM = 0.7  # Heuristic pattern match
    LOW = 0.5  # Significant signal match
    WEAK = 0.3  # Weak correlation
    INCONCLUSIVE = 0.1  # Guessing / Fallback


SUGGESTION_TEMPLATES = {
    FailureCategory.POLICY_VIOLATION: (
        "Review the agent's safety filters or policy constraints at turn {index}."
    ),
    FailureCategory.SECURITY_PII_LEAK: (
        "Check evaluation guardrails and input sanitization near turn {index}."
    ),
    FailureCategory.LOGIC_STATE_STALL: (
        "Review the agent's tool-use logic; it is repeating the base action "
        "'{evidence}' without progress."
    ),
    FailureCategory.LOGIC_PLANNING_ERROR: (
        "Check if the tool is providing sufficient feedback or if the agent "
        "is stuck in a circular reasoning loop."
    ),
    FailureCategory.INFRA_TIMEOUT: (
        "Increase the tool sandbox timeout or optimize the backend service for turn {index}."
    ),
    FailureCategory.INFRA_OOM: "Optimize memory usage or increase the container's RAM allocation.",
    FailureCategory.INFRA_RESOURCE_EXHAUSTED: (
        "Resource spike (CPU/MEM) detected at turn {index}. Scale vertically "
        "or optimize the agent's footprint."
    ),
    FailureCategory.LOGIC_UNCERTAINTY: (
        "Agent expresses confusion or doubt. Refine the system prompt or provide more context."
    ),
    FailureCategory.LOGIC_ABANDONMENT: (
        "Agent terminated prematurely with 0.0 metrics. Ensure termination "
        "guards are correctly configured."
    ),
    FailureCategory.UNKNOWN_FAILURE: (
        "Inconclusive results; review the raw trajectory in the visual console."
    ),
}


class TriageEngine:
    """Analyzes evaluation results to categorize failures using Forensic Weighted Evidence."""

    @staticmethod
    def categorize_failure(task_result: dict[str, Any]) -> str:
        """
        Refined v1.5.0 baseline: Delegates classification to the FailureTaxonomy.
        Returns standardized industrial codes (Standardized PBAC).
        """
        # 1. Prefer existing report if available
        report = task_result.get("diagnostic_report")
        if report and "root_cause" in report:
            return str(report["root_cause"]).upper()

        # 2. Delegate to authoritative taxonomy
        category = FailureTaxonomy.classify(task_result)

        # Standardized Industrial Output
        return str(category.name).upper()

    @staticmethod
    def identify_root_cause(data: list[dict[str, Any]] | dict[str, Any]) -> dict[str, Any]:
        """
        Pinpoints the root cause with a confidence score and explanation.
        Uses a Weighted Evidence Model with 'Step-Back' anchoring for agent attribution.
        """
        if isinstance(data, list):
            task_result = {"conversation_history": data}
        else:
            task_result = data

        history = task_result.get("conversation_history", [])
        if not history:
            return {"index": -1, "confidence": Confidence.INCONCLUSIVE, "reason": "No history"}

        # Evidence Collection Pool
        evidence_pool: list[dict[str, Any]] = []

        # 1. Forensic Report (Highest Weight)
        if report := TriageEngine._check_forensic_report(task_result, history):
            evidence_pool.append(report)

        # 2. Infrastructure & Telemetry correlation
        if infra := TriageEngine._check_infra_and_telemetry(task_result, history):
            evidence_pool.append(infra)

        # 3. Explicit Violations (Safety/Policy/Error)
        if violation := TriageEngine._check_explicit_violations(history):
            evidence_pool.append(violation)

        # 4. Agent Behavioral Loops & Stalls
        if behavior := TriageEngine._check_behavioral_patterns(task_result, history):
            evidence_pool.append(behavior)

        # 5. Metric Failures
        if metrics := TriageEngine._check_metric_failures(history):
            evidence_pool.append(metrics)

        # 6. Rank evidence and perform Step-Back pivot
        if not evidence_pool:
            return TriageEngine._fallback_diagnosis(history)

        # Weighted Sort
        evidence_pool.sort(
            key=lambda x: x["confidence"] * (1.0 + x.get("rank", 0) / 10.0), reverse=True
        )

        top_match = evidence_pool[0]

        # --- ROBUST STEP-BACK ANCHORING ---
        # If the failure is infrastructure-internal or a metric divergence,
        # we scan backward for the last authoritative Agent stimulus.
        curr_idx = top_match.get("index", -1)
        if curr_idx > 0:
            cat = top_match.get("category")
            is_infra_error = cat in (
                FailureCategory.INFRA_SIMULATOR_EXCEPTION,
                FailureCategory.INFRA_CONNECTION_FAILED,
                FailureCategory.INFRA_TIMEOUT,
            )
            is_metric_failure = cat in (
                FailureCategory.LOGIC_PLANNING_ERROR,
                FailureCategory.LOGIC_STATE_MISMATCH,
            )

            if is_infra_error or is_metric_failure:
                # Backward scan for Agent Identity or Agent Response signature
                found_anchor = False
                for i in range(curr_idx - 1, -1, -1):
                    turn = history[i]
                    is_agent = (
                        turn.get("identity") == "agent_id"
                        or turn.get("role") == "agent"
                        or turn.get("event") == "agent_response"
                    )
                    if is_agent:
                        top_match["index"] = i
                        top_match["reason"] = (
                            f"Root cause anchored to agent action preceding {cat}: "
                            f"{top_match['reason']}"
                        )
                        found_anchor = True
                        break

                if not found_anchor:
                    # Fallback Identification: Fault attributed to provider identity directly
                    provider = (
                        history[curr_idx].get("identity")
                        or history[curr_idx].get("identity_id")
                        or "infrastructure_provider"
                    )
                    top_match["reason"] = (
                        f"Fault attributed to provider {provider} "
                        f"(No direct agent stimulus found): {top_match['reason']}"
                    )

        # Inject suggestion
        cat = top_match.get("category", FailureCategory.UNKNOWN_FAILURE)
        format_args = {
            "index": top_match.get("index"),
            "evidence": top_match.get("evidence", ""),
            "tool": top_match.get("tool", "unknown"),
        }
        top_match["suggestion"] = SUGGESTION_TEMPLATES.get(
            cat, SUGGESTION_TEMPLATES[FailureCategory.UNKNOWN_FAILURE]
        ).format(**format_args)

        return top_match

    @staticmethod
    def identify_root_cause_index(history: list[dict[str, Any]]) -> int:
        """Backwards compatible wrapper for the index only."""
        return TriageEngine.identify_root_cause(history)["index"]

    @classmethod
    def apply_triage(cls, all_results: list[dict[str, Any]]) -> None:
        """Adds triage tags to all failed results."""
        for result in all_results:
            metrics = result.get("metrics", [])
            is_success = metrics and all(m.get("success", False) for m in metrics)
            result["triage_tag"] = cls.categorize_failure(result) if not is_success else "SUCCESS"

    # --------------------------------------------------------------------------
    # Private Forensic Analyzers
    # --------------------------------------------------------------------------

    @staticmethod
    def _check_forensic_report(
        task_result: dict[str, Any], history: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        report = task_result.get("diagnostic_report")
        if not report or not report.get("causal_chain"):
            return None

        chain = report["causal_chain"]
        if not chain:
            return None

        # Sort chain by rank DESC (primary first) then timestamp ASC
        sorted_chain = sorted(
            chain, key=lambda x: (x.get("rank", 0), -x.get("timestamp", 0)), reverse=True
        )
        root_trigger = sorted_chain[0]

        cat = root_trigger.get("trigger")
        evidence = root_trigger.get("evidence")
        t_index = root_trigger.get("turn_index")

        if t_index is not None and 0 <= t_index < len(history):
            return {
                "index": t_index,
                "confidence": Confidence.CERTAIN,
                "category": cat,
                "evidence": evidence,
                "reason": f"Forensic Root Cause ({cat}): {evidence}",
                "rank": root_trigger.get("rank", 0),
            }
        return None

    @staticmethod
    def _check_infra_and_telemetry(
        task_result: dict[str, Any], history: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Analyzes hardware usage spikes and correlates them with turn failure."""
        telemetry = task_result.get("resource_telemetry", [])
        if not telemetry:
            return None

        # Correlation logic: Scan for CPU/MEM spikes
        for event in telemetry:
            cpu = event.get("cpu_percent", 0)
            mem = event.get("memory_percent", 0)

            if cpu > 90 or mem > 90:
                # Find the nearest turn before this spike
                for i, turn in enumerate(history):
                    # In a real environment, we would compare ISO timestamps
                    # Simulating with turn matching for Core baseline
                    if turn.get("event") == "tool_result" and turn.get("status") == "error":
                        return {
                            "index": i,
                            "confidence": Confidence.HIGH,
                            "category": FailureCategory.INFRA_RESOURCE_EXHAUSTED,
                            "reason": f"Resource Exhaustion (CPU: {cpu}%, MEM: {mem}%) detected.",
                            "rank": 2,
                        }
        return None

    @staticmethod
    def _check_explicit_violations(history: list[dict[str, Any]]) -> dict[str, Any] | None:
        for i, turn in enumerate(history):
            content = turn.get("content", {})
            status = content.get("status") if isinstance(content, dict) else turn.get("status")

            # Support Identity-First checks (PBAC)
            identity = turn.get("identity") or turn.get("identity_id")

            # Legacy Error Patterns (Signed Provider detection)
            if identity in ("system_id", "env_id", "environment_id"):
                msg = str(content.get("message") or content.get("error") or "").lower()
                if "connection" in msg:
                    return {
                        "index": i,
                        "confidence": Confidence.HIGH,
                        "category": FailureCategory.INFRA_CONNECTION_FAILED,
                        "reason": f"Connection Failure detected: {msg}",
                        "rank": 3,
                    }
                if status == "error" or "error" in msg:
                    return {
                        "index": i,
                        "confidence": Confidence.HIGH,
                        "category": FailureCategory.INFRA_SIMULATOR_EXCEPTION,
                        "reason": f"Tool/Environment Error: {msg}",
                        "rank": 2,
                    }

            if status == "policy_violation":
                return {
                    "index": i,
                    "confidence": Confidence.HIGH,
                    "category": FailureCategory.POLICY_VIOLATION,
                    "reason": "Explicit policy violation detected in trajectory metadata.",
                    "rank": 5,
                }
            if status == "safety_block":
                return {
                    "index": i,
                    "confidence": Confidence.CERTAIN,
                    "category": FailureCategory.SECURITY_PII_LEAK,
                    "reason": "Safety block triggered (PII/Harmful content).",
                    "rank": 5,
                }
        return None

    @staticmethod
    def _check_behavioral_patterns(
        task_result: dict[str, Any], history: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Baseline for loop and uncertainty detection."""
        cat = FailureTaxonomy.classify(task_result)

        if cat in (FailureCategory.LOGIC_PLANNING_ERROR, FailureCategory.LOGIC_STATE_STALL):
            # Locate the start of the loop
            agent_msgs = [m for m in history if m.get("role") == "agent"]
            if len(agent_msgs) >= 3:
                # Find the turn index of the first repeating message
                # This is a heuristic approximation
                for i, turn in enumerate(history):
                    if turn.get("role") == "agent":
                        return {
                            "index": i,
                            "confidence": Confidence.MEDIUM_HIGH,
                            "category": cat,
                            "reason": f"Behavioral loop detected: {cat}",
                            "evidence": "Repeated base actions",
                            "rank": 0,
                        }
        return None

    @staticmethod
    def _check_metric_failures(history: list[dict[str, Any]]) -> dict[str, Any] | None:
        for i, turn in enumerate(history):
            if turn.get("event") == "evaluation" and turn.get("success") is False:
                return {
                    "index": i,
                    "confidence": Confidence.MEDIUM_HIGH,
                    "category": FailureCategory.LOGIC_PLANNING_ERROR,
                    "reason": f"Baseline Metric Failure: {turn.get('metric', 'unspecified')}",
                    "rank": -1,
                }
        return None

    @staticmethod
    def _fallback_diagnosis(history: list[dict[str, Any]]) -> dict[str, Any]:
        """Final heuristic attempt for unformatted trajectories."""
        # Check for explicit failure markers in history
        has_failure = any(
            (turn.get("event") == "run_end" or turn.get("role") == "run_end")
            and turn.get("status") in ("failed", "failure")
            for turn in history
        )

        # Search backwards for the last agent action
        fallback_idx = len(history) - 1
        for i in range(len(history) - 1, -1, -1):
            if history[i].get("role") == "agent":
                fallback_idx = i
                break

        if has_failure:
            return {
                "index": fallback_idx,
                "confidence": Confidence.LOW,
                "category": FailureCategory.UNKNOWN_FAILURE,
                "reason": "Target Task Not Completed (Unexpected Termination).",
            }

        return {
            "index": fallback_idx,
            "confidence": Confidence.INCONCLUSIVE,
            "category": FailureCategory.UNKNOWN_FAILURE,
            "reason": "Inconclusive results; no clear deviation point found.",
        }
