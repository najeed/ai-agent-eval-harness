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
