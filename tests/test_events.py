"""
tests/test_events.py

Verifies that the EventEmitter correctly broadcasts core events and that
subscribers receive them properly.
"""

import pytest
from eval_runner.events import EventEmitter, CoreEvents


def test_event_subscription():
    """Verify that subscribers receive emitted events."""
    events_received = []

    def subscriber(event):
        events_received.append(event)

    EventEmitter.subscribe(subscriber)

    # Emit a test event
    EventEmitter.emit(CoreEvents.RUN_START, {"run_id": "test-123"})

    assert len(events_received) == 1
    assert events_received[0].name == CoreEvents.RUN_START
    assert events_received[0].data["run_id"] == "test-123"

    # Emit another event
    EventEmitter.emit(CoreEvents.TURN_START, {"turn": 1})
    assert len(events_received) == 2
    assert events_received[1].name == CoreEvents.TURN_START


def test_event_multiple_subscribers():
    """Verify that multiple subscribers all receive the events."""
    results_a = []
    results_b = []

    EventEmitter.subscribe(lambda e: results_a.append(e))
    EventEmitter.subscribe(lambda e: results_b.append(e))

    EventEmitter.emit(CoreEvents.TASK_START, {"task": "t1"})

    assert len(results_a) > 0
    assert len(results_b) > 0
    # Search for the event in case there's noise from other tests
    assert any(e.name == CoreEvents.TASK_START for e in results_a)
    assert any(e.name == CoreEvents.TASK_START for e in results_b)


def test_emit_string_event():
    """Verify that string-based event names also work for flexibility."""
    received = []
    EventEmitter.subscribe(lambda e: received.append(e))

    EventEmitter.emit("custom_event", {"foo": "bar"})

    assert any(e.name == "custom_event" and e.data["foo"] == "bar" for e in received)
