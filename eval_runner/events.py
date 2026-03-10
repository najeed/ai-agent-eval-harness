from __future__ import annotations
"""
events.py

Centralized event system for OpenCore.
Enables "Flight Recorder" patterns where plugins can subscribe to 
state transitions without modifying the main engine loop.
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Callable
from abc import ABC, abstractmethod

class Event:
    """Base event structure."""
    def __init__(self, name: str, data: Dict[str, Any]):
        self.name = name
        self.data = data
        self.timestamp = datetime.now().isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.name,
            "timestamp": self.timestamp,
            **self.data
        }

class EventEmitter:
    """Centralized event bus."""
    _subscribers: List[Callable[[Event], None]] = []

    @classmethod
    def subscribe(cls, subscriber: Callable[[Event], None]):
        """Register a new subscriber (e.g., a logging plugin)."""
        if subscriber not in cls._subscribers:
            cls._subscribers.append(subscriber)

    @classmethod
    def emit(cls, name: str, data: Dict[str, Any]):
        """Emit an event to all subscribers."""
        event = Event(name, data)
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
    ERROR = "error"
