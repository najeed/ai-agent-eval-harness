from __future__ import annotations

"""
events.py

Centralized event system for OpenCore.
Enables "Flight Recorder" patterns where plugins can subscribe to 
state transitions without modifying the main engine loop.
"""

import json
import re
from datetime import datetime
from typing import Dict, Any, List, Callable
from abc import ABC, abstractmethod


def sanitize_payload(data: dict) -> dict:
    """Redacts PII and Secrets from event payload before broadcast.

    Security: Intercepts all outgoing bus payloads with regex-based
    redaction for common secret patterns (Audit Point #2).
    """

    def redact_string(s: str) -> str:
        # JWT tokens
        s = re.sub(r"ey[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", "[REDACTED_JWT]", s)
        # OpenAI / Stripe style keys
        s = re.sub(r"sk-[a-zA-Z0-9]{32,}", "[REDACTED_KEY]", s)
        # AWS Access Key IDs
        s = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]", s)
        # GitHub Personal Access Tokens & OAuth tokens
        s = re.sub(r"gh[po]_[a-zA-Z0-9]{36,}", "[REDACTED_GITHUB_TOKEN]", s)
        # Bearer authorization headers
        s = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", s)
        # Format-string injection prevention
        s = s.replace("{", "{{").replace("}", "}}")
        return s

    def recursive_sanitize(obj):
        if isinstance(obj, str):
            return redact_string(obj)
        elif isinstance(obj, dict):
            return {k: recursive_sanitize(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [recursive_sanitize(v) for v in obj]
        return obj

    return recursive_sanitize(data)


class Event:
    """Base event structure."""

    def __init__(self, name: str, data: Dict[str, Any]):
        self.name = name
        self.data = data
        self.timestamp = datetime.now().astimezone().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {"event": self.name, "timestamp": self.timestamp, **self.data}


class EventEmitter:
    """Centralized event bus."""

    _subscribers: List[Callable[[Event], None]] = []

    @classmethod
    def subscribe(cls, subscriber: Callable[[Event], None]):
        """Register a new subscriber (e.g., a logging plugin)."""
        if subscriber not in cls._subscribers:
            cls._subscribers.append(subscriber)

    @classmethod
    def reset(cls):
        """Clear all subscribers (used for testing stabilization)."""
        cls._subscribers = []

    @classmethod
    def emit(cls, name: str, data: Dict[str, Any]):
        """Emit an event to all subscribers."""
        sanitized_data = sanitize_payload(data)
        event = Event(name, sanitized_data)
        for sub in cls._subscribers:
            try:
                sub(event)
            except Exception as e:
                # Core stays stable even if subscribers fail
                print(f"   [Events] Error in subscriber for {name}: {e}")


# Pre-defined event names for consistency
class CoreEvents:
    RUN_START = "run_start"
    RUN_END = "run_end"
    TASK_START = "task_start"
    TASK_END = "task_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    AGENT_REQUEST = "agent_request"
    AGENT_RESPONSE = "agent_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    EVALUATION = "evaluation"
    HITL_PAUSE = "hitl_pause"
    HITL_RESUME = "hitl_resume"
    ERROR = "error"

    # Core Telemetry Extensions (v1.2.4)
    CHAIN_START = "chain_start"
    CHAIN_END = "chain_end"
    NODE_START = "node_start"
    NODE_END = "node_end"
