"""
tests/test_events.py

Verifies that the EventEmitter correctly broadcasts core events and that
subscribers receive them properly.
"""

from eval_runner.events import CoreEvents, EventEmitter


def test_event_subscription():
    """Verify that subscribers receive emitted events through a scoped bus."""
    bus = EventEmitter(run_id="test-123")
    events_received = []

    def subscriber(event):
        events_received.append(event)

    bus.subscribe(subscriber)
    bus.emit(CoreEvents.RUN_START, {"run_id": "test-123"})
    assert len(events_received) == 1
    assert events_received[0].name == CoreEvents.RUN_START
    assert events_received[0].data["run_id"] == "test-123"


def test_global_event_bus():
    """Verify that the module-level aliases work correctly for the global bus."""
    from eval_runner import events

    events_received = []
    events.subscribe(lambda e: events_received.append(e))
    events.emit(CoreEvents.PHASE_START, {"phase": "testing"})
    assert any(e.name == CoreEvents.PHASE_START for e in events_received)


def test_event_multiple_subscribers():
    """Verify that multiple subscribers all receive the events on an instance."""
    bus = EventEmitter(run_id="test-multi")
    results_a = []
    results_b = []
    bus.subscribe(lambda e: results_a.append(e))
    bus.subscribe(lambda e: results_b.append(e))
    bus.emit(CoreEvents.TASK_START, {"task_description": "t1"})
    assert len(results_a) == 1
    assert len(results_b) == 1
    assert results_a[0].name == CoreEvents.TASK_START


def test_async_event_subscription():
    """Verify that asynchronous event mode offloads execution and completes on flush."""
    import time

    bus = EventEmitter(run_id="test-async", async_mode=True)
    events_received = []

    def slow_subscriber(event):
        time.sleep(0.1)
        events_received.append(event)

    bus.subscribe(slow_subscriber)
    bus.emit(CoreEvents.RUN_START, {"run_id": "test-async"})

    # In async mode, the subscriber should not have completed immediately
    assert len(events_received) == 0

    # Wait for all background tasks to finish
    bus.flush()

    assert len(events_received) == 1
    assert events_received[0].name == CoreEvents.RUN_START
