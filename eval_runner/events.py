from __future__ import annotations

"""
events.py

Centralized event system for OpenCore.
Enables "Flight Recorder" patterns where plugins can subscribe to 
state transitions without modifying the main engine loop.
"""

import re  # noqa: E402
from collections.abc import Callable  # noqa: E402
from datetime import datetime  # noqa: E402
from typing import Any  # noqa: E402


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
        elif obj is None or isinstance(obj, (int, float, bool)):
            return obj
        else:
            # Handle non-serializable objects (e.g. functions, custom classes)
            return str(obj)

    return recursive_sanitize(data)


class Event:
    """Base event structure."""

    def __init__(self, name: str, data: dict[str, Any], span_context: dict[str, Any] | None = None):
        self.name = name
        self.data = data
        self.span_context = span_context
        self.timestamp = datetime.now().astimezone().isoformat()

    def to_dict(self) -> dict[str, Any]:
        base = {"event": self.name, "timestamp": self.timestamp, **self.data}
        if self.span_context:
            base["span_context"] = self.span_context
        return base


class EventEmitter:
    """
    Centralized event bus.
    Now supports instantiation for session-scoped isolation.
    """

    def __init__(self, run_id: str | None = None):
        self.run_id = run_id
        self._subscribers: list[Callable[[Event], None]] = []
        self._keyed_subscribers: dict[str, Callable[[Event], None]] = {}

    def subscribe(self, subscriber: Callable[[Event], None], key: str | None = None):
        """Register a new subscriber (e.g., a logging plugin)."""
        if key:
            self._keyed_subscribers[key] = subscriber
        elif subscriber not in self._subscribers:
            self._subscribers.append(subscriber)

    def unsubscribe(self, subscriber: Callable[[Event], None] | str):
        """Unregister an existing subscriber or key."""
        if isinstance(subscriber, str):
            if subscriber in self._keyed_subscribers:
                del self._keyed_subscribers[subscriber]
        elif subscriber in self._subscribers:
            self._subscribers.remove(subscriber)

    def reset(self):
        """Clear all subscribers and notify them to cleanup if possible."""
        all_subs = self._subscribers + list(self._keyed_subscribers.values())
        for sub in all_subs:
            try:
                # If subscriber is a bound method of a class with cleanup logic
                if hasattr(sub, "__self__") and hasattr(sub.__self__, "close_all"):
                    sub.__self__.close_all()
            except Exception as e:
                # Forensic Transparency: Log cleanup failures for auditing
                print(f"   [Events] Warning: Subscriber cleanup failure: {e}")
        self._subscribers = []
        self._keyed_subscribers = {}

    def emit(self, name: str, data: dict[str, Any], span_context: dict[str, Any] | None = None):
        """Emit an event to all subscribers with optional tracing context."""
        sanitized_data = sanitize_payload(data)

        # Inversion of Control: Auto-inject run_id if available in the bus
        if self.run_id and "run_id" not in sanitized_data:
            sanitized_data["run_id"] = self.run_id

        event = Event(name, sanitized_data, span_context=span_context)
        all_subs = self._subscribers + list(self._keyed_subscribers.values())
        for sub in all_subs:
            try:
                sub(event)
            except Exception as e:
                # Core stays stable even if subscribers fail
                print(f"   [Events] Error in subscriber for {name}: {e}")

    # --- Lifecycle Management ---
    _global_instance = None

    @classmethod
    def get_global(cls):
        """Authoritative singleton resolver for the global event bus."""
        if cls._global_instance is None:
            cls._global_instance = cls()
        return cls._global_instance


# Standard Global interface (Module Level Aliases)
def subscribe(subscriber: Callable[[Event], None], key: str | None = None):
    """Register a subscriber to the global event bus."""
    EventEmitter.get_global().subscribe(subscriber, key=key)


def unsubscribe(subscriber: Callable[[Event], None] | str):
    """Unregister a subscriber from the global event bus."""
    EventEmitter.get_global().unsubscribe(subscriber)


def emit(name: str, data: dict[str, Any], span_context: dict[str, Any] | None = None):
    """Broadcast an event via the global bus (Strict Redaction Enforced)."""
    EventEmitter.get_global().emit(name, data, span_context=span_context)


def reset():
    """Reset the global event bus state."""
    EventEmitter.get_global().reset()


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

    # Behavioral DNA & OTEL Nesting (v1.1.0)
    STRATEGY_START = "strategy_start"
    STRATEGY_END = "strategy_end"
    MANEUVER_START = "maneuver_start"
    MANEUVER_END = "maneuver_end"
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    SUBTASK_START = "subtask_start"
    SUBTASK_END = "subtask_end"
    ACTION_START = "action_start"
    ACTION_END = "action_end"
    STEP_START = "step_start"
    STEP_END = "step_end"

    # Infrastructure & Target Abstraction (v1.3.0)
    ROUTING_RESOLVED = "routing_resolved"
    ADAPTER_DEBUG = "adapter_debug"
