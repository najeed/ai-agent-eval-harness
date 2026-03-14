"""
taxonomy.py (Zero-Touch version)

Stand-alone failure classification for the Publication Suite.
Categorizes failures into tool_call_error, state_parity_mismatch, hallucination, timeout, sandbox_breach, and partial_pass.
"""

import re
from typing import Dict, Any, List

CATEGORIES = [
    "tool_call_error",
    "state_parity_mismatch", 
    "hallucination",
    "timeout",
    "sandbox_breach",
    "partial_pass"
]

class FailureTaxonomy:
    """Classifies agent failures based on conversation history and tool results found in run.jsonl."""

    @staticmethod
    def classify_from_events(events: List[Dict[str, Any]]) -> str:
        """Determines the specific failure category for a non-successful run sequence."""
        
        # 1. Partial Pass Detection
        eval_events = [e for e in events if e.get("event") == "evaluation"]
        if eval_events:
            success_flags = [e.get("success", False) for e in eval_events]
            if 0 < sum(success_flags) < len(success_flags):
                return "partial_pass"
            if all(success_flags):
                return "SUCCESS"

        # 2. Sandbox Breach / Policy Violation
        for e in events:
            if e.get("event") == "tool_result" and e.get("status") == "policy_violation":
                return "sandbox_breach"

        # 3. Tool Call Errors
        for e in events:
            if e.get("event") == "tool_result" and e.get("status") == "error":
                error_msg = str(e.get("result", "")).lower()
                if "parity" in error_msg or "mismatch" in error_msg:
                    return "state_parity_mismatch"
                return "tool_call_error"

        # 4. Timeout / Max Turns
        agent_turns = len([e for e in events if e.get("event") in ["prompt", "agent_response"]])
        if agent_turns >= 10:
            return "timeout"

        # 5. Hallucination Detection
        for e in events:
            if e.get("event") == "agent_response":
                content = str(e.get("content", ""))
                if re.search(r"invalid tool|not found|i cannot find", content.lower()):
                    return "hallucination"

        return "unknown_failure"
