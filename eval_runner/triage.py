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
    def identify_root_cause(history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Pinpoints the root cause with a confidence score and explanation.
        """
        if not history:
            return {"index": -1, "confidence": 0, "reason": "No history"}

        # 0. Check for failure signature (Include 'failure' and 'failed' and results)
        has_failure = any(
            turn.get("event") in ("run_end", "evaluation") or turn.get("role") == "run_end"
            for turn in history
        )
        
        # Explicit fail status check
        is_explicit_fail = any(
            (turn.get("event") == "run_end" or turn.get("role") == "run_end") and turn.get("status") in ("failed", "failure")
            for turn in history
        )

        # 1. High Confidence: Policy Violation or Marked Root Cause
        for i, turn in enumerate(history):
            content = turn.get("content") or {}
            # Check content for explicit violation status
            if isinstance(content, dict) and content.get("status") == "policy_violation":
                return {
                    "index": i,
                    "confidence": 1.0,
                    "reason": f"Explicit policy violation detected at turn {i}: {content.get('message', 'Unspecified violation')}"
                }
        # 1. High Confidence: Explicitly marked failures (policy, safety, validation)
        for i, turn in enumerate(history):
            ev = turn.get("event")
            status = turn.get("status")
            content = turn.get("content") or {}
            if ev == "policy_violation" or status == "policy_violation" or (isinstance(content, dict) and content.get("status") == "policy_violation"):
                return {
                    "index": i,
                    "confidence": 0.95,
                    "reason": "Policy violation detected at this turn.",
                    "suggestion": "Review the agent's safety filters or policy constraints."
                }
            if ev == "safety_block" or status == "safety_block" or (isinstance(content, dict) and content.get("status") == "safety_block"):
                return {
                    "index": i,
                    "confidence": 1.0,
                    "reason": "Safety block triggered (e.g., PII or toxic content).",
                    "suggestion": "Check the evaluation guardrails and input sanitization."
                }
            # Check evaluation events for policy compliance failure (common in tests)
            if ev == "evaluation" and turn.get("metric") == "policy_compliance" and turn.get("value") == 0.0:
                return {
                    "index": i,
                    "confidence": 1.0,
                    "reason": "Policy Violation (Safety/Privacy Guardrail) detected via evaluation metrics.",
                    "suggestion": "Review the agent's safety filters or policy constraints."
                }

        # 3. Explicitly marked root cause in a turn (if plugin added it)
        for i, turn in enumerate(history):
            if turn.get("is_root_cause") or turn.get("root_cause"):
                 return {
                    "index": i,
                    "confidence": 1.0,
                    "reason": turn.get("root_cause_reason") or "Explicitly marked as root cause by evaluation plugin.",
                    "suggestion": turn.get("root_cause_suggestion") or "Review the specific metric failure in the report."
                }

        # 2. Medium-High Confidence: Tool Error or Timeout
        for i, turn in enumerate(history):
            # Check tool results for error/timeout strings (explainer style)
            if turn.get("event") == "tool_result" or turn.get("role") == "environment":
                content = turn.get("content") or {}
                raw_result = str(turn.get("result") or (content.get("message") if isinstance(content, dict) else content))
                result_val = raw_result.lower()
                
                is_error = "error" in result_val or "exception" in result_val or (isinstance(content, dict) and content.get("status") == "error")
                
                if "timeout" in result_val:
                    return {
                        "index": i, 
                        "confidence": 0.85, 
                        "reason": f"Tool Timeout: {turn.get('tool') or 'unknown'}. Result: {raw_result}",
                        "suggestion": "Increase the tool sandbox timeout or optimize the backend service."
                    }
                if is_error:
                    # Trace back to agent if possible
                    inner_reason = f"Tool Error in {turn.get('tool') or 'executor'}: {raw_result}"
                    for j in range(i - 1, -1, -1):
                        if history[j].get("role") == "agent" or history[j].get("event") in ("agent_response", "tool_call"):
                             return {
                                 "index": j, 
                                 "confidence": 0.85, 
                                 "reason": f"{inner_reason} (triggered by agent decision at turn {j})",
                                 "suggestion": "Debug the tool implementation or check for missing environment variables."
                             }
                    return {"index": i, "confidence": 0.7, "reason": inner_reason, "suggestion": "Debug the tool implementation or check for missing environment variables."}

        # 4. Connection Error or System Failure
        for i, turn in enumerate(history):
            if turn.get("role") == "system" or turn.get("event") == "system_error":
                content = turn.get("content") or {}
                if (isinstance(content, dict) and content.get("status") == "error") or "error" in str(content).lower():
                    return {
                        "index": i,
                        "confidence": 0.9,
                        "reason": f"System/Connection Error: {content.get('message') or str(content) if isinstance(content, dict) else str(content)}",
                        "suggestion": "Check agent connectivity, API keys, or infrastructure logs."
                    }

        # 5. Stall Detection (Repeated Agent Actions)
        agent_actions = []
        for i, turn in enumerate(history):
            if turn.get("role") == "agent" and isinstance(turn.get("content"), dict):
                agent_actions.append((i, turn.get("content", {}).get("action")))
        
        if len(agent_actions) >= 3:
            for i in range(len(agent_actions) - 2):
                idx, act = agent_actions[i]
                if act == agent_actions[i+1][1] == agent_actions[i+2][1] and act is not None and act != "thought":
                    return {
                        "index": idx,
                        "confidence": 0.8,
                        "reason": f"Agent Stall Detected: Repeatedly calling '{act}' without progress.",
                        "suggestion": "Review the agent's tool-use logic or check if the tool is providing sufficient feedback."
                    }

        # 6. Infinite Loop Detection
        prompts = [e.get("content") for e in history if e.get("event") == "prompt" or e.get("role") == "user"]
        if len(prompts) > 10:
            unique_prompts = set([str(p) for p in prompts])
            if len(unique_prompts) < len(prompts) / 2:
                return {
                    "index": 0,
                    "confidence": 0.9,
                    "reason": "Infinite Loop Detected (Repetitive Interaction Pattern).",
                    "suggestion": "Review agent logic for circular reasoning or missing termination guards."
                }

        # 4. Final Fallback: If run_end says failure but nothing else found
        if is_explicit_fail:
            for i in range(len(history) - 1, -1, -1):
                if history[i].get("role") == "agent" or history[i].get("event") in ("agent_response", "tool_call"):
                    action = history[i].get("content", {}).get("action") if isinstance(history[i].get("content"), dict) else None
                    if action != "thought":
                        return {
                            "index": i,
                            "confidence": 0.5,
                            "reason": "Target Task Not Completed. Identified last substantive agent action before run failure.",
                            "suggestion": "Increase EVAL_MAX_TURNS or refine the agent's prompt to be more specific."
                        }
            # Catch-all for failed status even without agent actions in history
            return {
                "index": -1,
                "confidence": 0.3,
                "reason": "Target Task Not Completed (Unexpected Termination).",
                "suggestion": "Check for early run termination or missing agent response events."
            }

        # If it reached here and it's not an explicit fail, it might be a success or inconclusive
        if not is_explicit_fail and any(turn.get("event") == "run_end" and turn.get("status") == "success" for turn in history):
            return {"index": -1, "confidence": 1.0, "reason": "Execution succeeded"}

        return {"index": -1, "confidence": 0.1, "reason": "Inconclusive results; no clear deviation point found."}

    @staticmethod
    def identify_root_cause_index(history: List[Dict[str, Any]]) -> int:
        """Backwards compatible wrapper for the index only."""
        return TriageEngine.identify_root_cause(history)["index"]

    @classmethod
    def apply_triage(cls, all_results: List[Dict[str, Any]]):
        """Adds triage tags to all failed results."""
        for result in all_results:
            metrics = result.get("metrics", [])
            if not metrics or not all(m.get("success", False) for m in metrics):
                result["triage_tag"] = cls.categorize_failure(result)
            else:
                result["triage_tag"] = "SUCCESS"
