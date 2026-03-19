from __future__ import annotations
"""
triage.py

Categorizes and explains evaluation failures based on trajectory patterns.
"""

from typing import List, Dict, Any

class TriageEngine:
    """Analyzes evaluation results to categorize failures."""

    @staticmethod
    def categorize_failure(task_result: Dict[str, Any]) -> str:
        """
        Heuristic-based categorization of a failed task.
        """
        metrics = task_result.get("metrics", [])
        if metrics and all(m.get("success", False) for m in metrics):
            return "SUCCESS"

        history = task_result.get("conversation_history", [])
        if not history:
            return "NO_HISTORY"

        # Check for policy violations
        for turn in history:
            if turn.get("role") == "environment":
                content = turn.get("content", {})
                if isinstance(content, dict) and content.get("status") == "policy_violation":
                    return "POLICY_VIOLATION"

        # Check for stalls (repeated actions)
        agent_actions = [
            turn.get("content", {}).get("action") 
            for turn in history if turn.get("role") == "agent" and isinstance(turn.get("content"), dict)
        ]
        if len(agent_actions) >= 3:
            for i in range(len(agent_actions) - 2):
                if agent_actions[i] == agent_actions[i+1] == agent_actions[i+2] and agent_actions[i] is not None:
                    return "STALL"

        # Check for Tool Errors (Environment status 'error')
        for turn in history:
            if turn.get("role") == "environment":
                content = turn.get("content", {})
                if isinstance(content, dict) and content.get("status") == "error":
                    return "TOOL_ERROR"
            if turn.get("role") == "system":
                content = turn.get("content", {})
                if isinstance(content, dict) and content.get("status") == "error":
                    return "CONNECTION_ERROR"

        # Check for MAX_TURNS reach
        # Since we don't have the explicit 'max_turns' here, we infer it from length
        # if the last turn wasn't a success but history is long.
        if len(history) >= 10: # Heuristic for 'Too many turns'
            return "TIMEOUT"

    @staticmethod
    @staticmethod
    def identify_root_cause(history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Pinpoints the root cause with a confidence score and explanation.
        """
        if not history:
            return {"index": -1, "confidence": 0, "reason": "No history"}

        # 0. Check for failure signature
        has_failure = any(
            turn.get("event") == "run_end" and turn.get("status") == "failed"
            or (isinstance(turn.get("content"), dict) and turn.get("content", {}).get("status") in ("error", "policy_violation"))
            for turn in history
        )
        if not has_failure:
            return {"index": -1, "confidence": 1.0, "reason": "Execution succeeded"}

        # 1. High Confidence: Policy Violation
        for i, turn in enumerate(history):
            content = turn.get("content") or {}
            if isinstance(content, dict) and content.get("status") == "policy_violation":
                return {
                    "index": i,
                    "confidence": 1.0,
                    "reason": f"Explicit policy violation detected at turn {i}: {content.get('message', 'Unspecified violation')}"
                }
            if turn.get("is_root_cause"):
                 return {
                    "index": i,
                    "confidence": 1.0,
                    "reason": "Explicitly marked as root cause by evaluation plugin."
                }

        # 2. Medium-High Confidence: Tool Error (caused by agent decision)
        for i, turn in enumerate(history):
            if turn.get("role") in ("environment", "system"):
                content = turn.get("content") or {}
                if isinstance(content, dict) and content.get("status") == "error":
                    for j in range(i - 1, -1, -1):
                        if history[j].get("role") == "agent":
                            return {
                                "index": j,
                                "confidence": 0.85,
                                "reason": f"System error at turn {i} likely triggered by agent decision at turn {j}."
                            }
                    return {"index": i, "confidence": 0.7, "reason": "System error with no clear preceding agent action."}

        # 3. Medium Confidence: Connection failure
        if len(history) > 0 and history[0].get("event") == "connection_error":
            return {"index": 0, "confidence": 0.9, "reason": "Run failed due to initial connection error."}

        # 4. Low-Medium Confidence: Heuristic Fallback (Last substantive action)
        for i in range(len(history) - 1, -1, -1):
            if history[i].get("role") == "agent":
                action = history[i].get("content", {}).get("action")
                if action and action != "thought":
                    return {
                        "index": i,
                        "confidence": 0.5,
                        "reason": "Identified last substantive agent action before run failure (heuristic fallback)."
                    }
        
        return {"index": -1, "confidence": 0.1, "reason": "Inconclusive results; no clear deviation point found."}

    @staticmethod
    def identify_root_cause_index(history: List[Dict[str, Any]]) -> int:
        """Backwards compatible wrapper for the index only."""
        return TriageEngine.identify_root_cause(history)["index"]

        return "UNKNOWN_FAILURE"

    @classmethod
    def apply_triage(cls, all_results: List[Dict[str, Any]]):
        """Adds triage tags to all failed results."""
        for result in all_results:
            metrics = result.get("metrics", [])
            if not metrics or not all(m.get("success", False) for m in metrics):
                result["triage_tag"] = cls.categorize_failure(result)
            else:
                result["triage_tag"] = "SUCCESS"
