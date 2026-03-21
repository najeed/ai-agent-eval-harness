"""
taxonomy.py

Centralized failure classification engine for AI Agent Eval Harness.
Maps trajectory patterns to industry-standard failure categories.
"""

import re
from typing import Dict, Any, List

CATEGORIES = [
    "tool_call_error",
    "state_parity_mismatch",
    "hallucination",
    "timeout",
    "sandbox_breach",
    "partial_pass",
]


class FailureTaxonomy:
    """Classifies agent failures based on conversation history and tool results."""

    @staticmethod
    def classify(task_result: Dict[str, Any]) -> str:
        """Determines the specific failure category for a non-successful run."""
        metrics = task_result.get("metrics", [])
        history = task_result.get("conversation_history", [])

        # 1. Partial Pass Detection
        success_count = sum(1 for m in metrics if m.get("success", False))
        if 0 < success_count < len(metrics):
            return "partial_pass"

        # 2. Sandbox Breach / Policy Violation
        for turn in history:
            if turn.get("role") == "environment":
                content = turn.get("content", {})
                if isinstance(content, dict) and content.get("status") == "policy_violation":
                    return "sandbox_breach"

        # 3. Tool Call Errors
        for turn in history:
            if turn.get("role") == "environment":
                content = turn.get("content", {})
                if isinstance(content, dict) and content.get("status") == "error":
                    # Distinguish between tool error and parity error
                    error_msg = str(content.get("error", "")).lower()
                    if "parity" in error_msg or "mismatch" in error_msg:
                        return "state_parity_mismatch"
                    return "tool_call_error"

        # 4. Timeout / Max Turns
        if len(history) >= 10:  # Heuristic for now, should ideally check config
            return "timeout"

        # 5. Hallucination Detection (Simple Heuristic for now)
        # Agent refers to tools that don't exist or mentions data not in context
        agent_msgs = [m for m in history if m["role"] == "agent"]
        for msg in agent_msgs:
            content = str(msg.get("content", ""))
            if re.search(r"invalid tool|not found|i cannot find", content.lower()):
                return "hallucination"

        return "unknown_failure"
