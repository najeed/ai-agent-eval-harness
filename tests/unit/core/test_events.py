import pytest

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


# --- Coverage booster for events.py ---


def test_event_executor_singleton_and_resubscribe():
    from eval_runner.events import EventEmitter

    # 1. Test get_executor reuse
    exec1 = EventEmitter.get_executor()
    exec2 = EventEmitter.get_executor()
    assert exec1 is exec2

    bus = EventEmitter()
    received = []

    def sub(e):
        received.append(e)

    # 2. Test duplicate subscribe protection
    bus.subscribe(sub)
    bus.subscribe(sub)  # should not add duplicate
    assert len(bus._subscribers) == 1

    # 3. Test unsubscribe callable
    bus.unsubscribe(sub)
    assert len(bus._subscribers) == 0

    # 4. Test unsubscribe key
    bus.subscribe(sub, key="test_key")
    assert "test_key" in bus._keyed_subscribers
    bus.unsubscribe("test_key")
    assert "test_key" not in bus._keyed_subscribers


def test_event_subscriber_cleanup_with_close_all():
    from eval_runner.events import EventEmitter

    class DummySub:
        def __init__(self, raise_err=False):
            self.cleaned = False
            self.raise_err = raise_err

        def __call__(self, event):
            pass

        def close_all(self):
            self.cleaned = True
            if self.raise_err:
                raise ValueError("Cleanup error")

    bus = EventEmitter()
    sub_ok = DummySub(raise_err=False)
    sub_fail = DummySub(raise_err=True)

    bus.subscribe(sub_ok.__call__)
    bus.subscribe(sub_fail.__call__, key="fail_key")

    bus.reset()
    assert sub_ok.cleaned
    assert sub_fail.cleaned
    assert len(bus._subscribers) == 0
    assert len(bus._keyed_subscribers) == 0


def test_event_opentelemetry_attach_detach_exceptions():
    from unittest.mock import patch

    from eval_runner.events import EventEmitter

    # Mock context attach and detach to raise exceptions
    with (
        patch("opentelemetry.context.attach", side_effect=Exception("Attach failed")),
        patch("opentelemetry.context.detach", side_effect=Exception("Detach failed")),
    ):
        bus = EventEmitter()
        bus.subscribe(lambda e: None)
        # Emit with dummy span context to trigger context code paths
        bus.emit(
            "test_event",
            {"val": 1},
            span_context={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
        )


def test_event_importerror_otel_get_current():
    from unittest.mock import patch

    from eval_runner.events import EventEmitter

    # Mock context get_current to raise ImportError
    with patch("opentelemetry.context.get_current", side_effect=ImportError("No otel")):
        bus = EventEmitter()
        bus.subscribe(lambda e: None)
        bus.emit("test_event", {"val": 1})


@pytest.mark.asyncio
async def test_event_async_coroutine_subscriber():
    import asyncio

    from eval_runner.events import EventEmitter

    bus = EventEmitter(async_mode=True)
    received = []

    async def async_sub(event):
        await asyncio.sleep(0.01)
        received.append(event)

    bus.subscribe(async_sub)
    bus.emit("async_coro_event", {"data": "test"})

    # Wait for the coroutine to complete
    await asyncio.sleep(0.05)
    bus.flush()
    assert len(received) == 1
    assert received[0].name == "async_coro_event"


@pytest.mark.asyncio
async def test_event_scheduling_exception():
    from unittest.mock import patch

    from eval_runner.events import EventEmitter

    bus = EventEmitter(async_mode=True)
    bus.subscribe(lambda e: None)

    # Mock loop.run_in_executor to raise an exception
    with patch("asyncio.get_running_loop") as mock_loop:
        mock_loop.return_value.run_in_executor.side_effect = Exception("Scheduling failed")
        # Should catch scheduling exception gracefully without crashing emit
        bus.emit("fail_schedule", {"val": 1})


def test_async_mode_sync_subscriber_otel_detach_exception():
    from unittest.mock import MagicMock, patch

    from eval_runner.events import EventEmitter

    bus = EventEmitter(async_mode=True)

    # Register a standard synchronous subscriber
    bus.subscribe(lambda e: None)

    # We patch attach to succeed (returning a token) and detach to fail.
    # We also run on a custom mock executor to run synchronously inside submit()
    # to control execution flow and catch exceptions.
    class SyncExecutor:
        def submit(self, fn, *args, **kwargs):
            # Execute synchronously now to run _execute_subscriber_with_context
            fn(*args, **kwargs)
            f = MagicMock()
            f.done.return_value = True
            return f

    with (
        patch.object(bus, "get_executor", return_value=SyncExecutor()),
        patch("opentelemetry.context.attach", return_value="my_token"),
        patch("opentelemetry.context.detach", side_effect=Exception("Detach failed")),
    ):
        # Emit with span_context to trigger the OTel block inside submit
        bus.emit("test_event", {"val": 1}, span_context={"traceparent": "00-1-2-01"})


def test_sync_mode_otel_detach_exception():
    from unittest.mock import patch

    from eval_runner.events import EventEmitter

    bus = EventEmitter(async_mode=False)
    bus.subscribe(lambda e: None)

    with (
        patch("opentelemetry.context.attach", return_value="sync_token"),
        patch("opentelemetry.context.detach", side_effect=Exception("Sync detach failed")),
    ):
        bus.emit("test_event", {"val": 1}, span_context={"traceparent": "00-1-2-01"})


@pytest.mark.asyncio
async def test_async_coro_otel_detach_exception():
    import asyncio
    from unittest.mock import patch

    from eval_runner.events import EventEmitter

    bus = EventEmitter(async_mode=True)

    async def dummy_coro(event):
        pass

    bus.subscribe(dummy_coro)

    with (
        patch("opentelemetry.context.attach", return_value="coro_token"),
        patch("opentelemetry.context.detach", side_effect=Exception("Coro detach failed")),
    ):
        bus.emit("test_event", {"val": 1}, span_context={"traceparent": "00-1-2-01"})
        # Allow loop tasks to run
        await asyncio.sleep(0.01)
        bus.flush()
