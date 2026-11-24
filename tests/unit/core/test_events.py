import pytest

from eval_runner.events import CoreEvents, EventEmitter


@pytest.mark.parametrize("corruption", [None, "drop", "content"])
def test_capture_closure_checks_exact_provider_events(tmp_path, corruption):
    from eval_runner.events import EvidenceDeliveryError
    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(tmp_path / "runs")
    run_id = "capture-check"
    store.create_run(run_id, "capture-scenario")
    bus = EventEmitter(run_id=run_id)

    def persist(event):
        if corruption == "drop":
            return
        row = event.to_dict()
        row["_seq"] = 1
        if corruption == "content":
            row["outcome"] = "forged"
        store.append_events(run_id, [row])

    bus.subscribe(persist, required=True)
    bus.emit("run_end", {"outcome": "success"})
    if corruption:
        with pytest.raises(EvidenceDeliveryError, match="closure failed"):
            bus.finalize_capture(run_id, store)
        assert store.get_run(run_id)["status_details"]["evidence_capture_failed"] is True
    else:
        receipt = bus.finalize_capture(run_id, store)
        assert receipt["complete"] is True
        assert receipt["event_count"] == 1
        assert store.get_run(run_id)["status_details"]["evidence_capture"] == receipt
        with pytest.raises(EvidenceDeliveryError, match="closed"):
            bus.emit("node_start", {})


def test_capture_resumption_binds_the_acknowledged_prefix(tmp_path):
    import json

    from eval_runner.events import EvidenceDeliveryError
    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(tmp_path / "runs")
    run_id = "capture-resume"
    store.create_run(run_id, "capture-scenario")

    def persist(event):
        raw = store.get_trace_bytes(run_id)
        rows = [json.loads(line) for line in raw.splitlines()] if raw is not None else []
        store.append_events(run_id, [{**event.to_dict(), "_seq": len(rows) + 1}])

    bus = EventEmitter(run_id=run_id)
    bus.subscribe(persist, required=True)
    bus.emit("approval_created", {})
    assert bus.finalize_capture(run_id, store, complete=False)["resumable"] is True
    resumed = EventEmitter(run_id=run_id)
    resumed.subscribe(persist, required=True)
    resumed.resume_capture(run_id, store)
    assert store.get_run(run_id)["status_details"]["evidence_capture"]["resumable"] is False
    with pytest.raises(EvidenceDeliveryError, match="acknowledged prefix"):
        EventEmitter().resume_capture(run_id, store)
    resumed.emit("run_end", {})
    assert resumed.finalize_capture(run_id, store)["event_count"] == 2


@pytest.mark.parametrize("async_mode", [False, True])
def test_mandatory_event_delivery_is_synchronous_and_fails_closed(async_mode):
    from eval_runner.events import EvidenceDeliveryError

    bus = EventEmitter(run_id="required-evidence", async_mode=async_mode)
    observed = []

    def persistence(event):
        observed.append(event.name)
        raise OSError("provider unavailable")

    bus.subscribe(persistence, required=True)
    with pytest.raises(EvidenceDeliveryError):
        bus.emit("node_end", {})
    assert observed == ["node_end"]
    with pytest.raises(EvidenceDeliveryError, match="already failed"):
        bus.emit("run_end", {})
    assert observed == ["node_end"]
    bus.reset()


def test_optional_event_observer_does_not_invalidate_durable_delivery():
    bus = EventEmitter(async_mode=False)
    persisted = []
    bus.subscribe(lambda event: persisted.append(event.name), required=True)

    def unavailable(event):
        raise OSError("observer unavailable")

    bus.subscribe(unavailable)
    bus.emit("node_end", {})
    assert persisted == ["node_end"]


def test_mandatory_coroutine_evidence_subscribers_are_rejected():
    bus = EventEmitter(async_mode=True)

    async def persistence(event):
        return None

    with pytest.raises(TypeError, match="synchronously"):
        bus.subscribe(persistence, required=True)
    assert persistence not in bus._subscribers


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

    # Wait for the coroutine to complete with a robust polling loop
    for _ in range(100):
        if len(received) == 1:
            break
        await asyncio.sleep(0.01)

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


@pytest.mark.asyncio
async def test_events_subscriber_context_and_capture_failure_branches():
    import asyncio
    import json
    from unittest.mock import MagicMock, patch

    from eval_runner.events import (
        Event,
        EventEmitter,
        EvidenceDeliveryError,
        _execute_subscriber_with_context,
    )

    # 1. _execute_subscriber_with_context with otel_ctx=None and failing async sub
    async def failing_async_sub(_ev):
        raise RuntimeError("async sub boom")

    def run_in_thread():
        _execute_subscriber_with_context(failing_async_sub, Event("e", {}), None)

    await asyncio.to_thread(run_in_thread)

    # 2. _execute_subscriber_with_context when attach fails
    with patch("opentelemetry.context.attach", side_effect=RuntimeError("attach err")):
        _execute_subscriber_with_context(lambda _e: None, Event("e", {}), object())

    # 3. unsubscribe missing key & mandatory async subscriber rejection
    bus = EventEmitter(async_mode=False, run_id="r-ev")
    bus.unsubscribe("missing-key")

    async def mandatory_async(_ev):
        pass

    bus.subscribe(lambda ev: mandatory_async(ev), required=True)
    with pytest.raises(EvidenceDeliveryError, match="Evidence capture failed"):
        bus.emit("ev", {}, require_acknowledgement=True)

    # 4. finalize_capture failure branches (232, 238, 252, 267, 279-280)
    bus2 = EventEmitter(async_mode=False, run_id="r-fin")
    bus2.subscribe(lambda _e: None, required=True)
    bus2.emit("step", {"a": 1}, require_acknowledgement=True)

    store_bad_seq = MagicMock()
    store_bad_seq.get_trace_bytes.return_value = b'{"event": "step", "_seq": 99}\n'
    with pytest.raises(EvidenceDeliveryError):
        bus2.finalize_capture("r-fin", store_bad_seq)

    bus2._delivery_failures.clear()
    bus2._baseline_counts["r-fin"] = 1
    store_bad_commit = MagicMock()
    store_bad_commit.get_trace_bytes.return_value = b'{"event": "step", "_seq": 1}\n'
    with pytest.raises(EvidenceDeliveryError):
        bus2.finalize_capture("r-fin", store_bad_commit)

    # Non-terminal event when complete=True (252)
    bus3 = EventEmitter(async_mode=False, run_id="r-term")
    bus3.subscribe(lambda _e: None, required=True)
    bus3.emit("step", {"a": 1}, require_acknowledgement=True)
    # Build matching record bytes
    from agentv_runtime.canonical import canonical_json_encode

    bus3_keys, _ = bus3._emission_commitments["r-term"][0]
    row = {
        k: ("step" if k == "event" else "r-term" if k == "run_id" else 1 if k == "a" else "t")
        for k in bus3_keys
    }
    # Recompute exact commitment to pass commitment check and hit terminal check
    import hashlib

    bus3._emission_commitments["r-term"][0] = (
        tuple(row),
        hashlib.sha3_256(canonical_json_encode(row)).hexdigest(),
    )
    row_with_seq = {**row, "_seq": 1}
    store_non_term = MagicMock()
    store_non_term.get_trace_bytes.return_value = (json.dumps(row_with_seq) + "\n").encode("utf-8")
    with pytest.raises(EvidenceDeliveryError):
        bus3.finalize_capture("r-term", store_non_term, complete=True)

    # update_run_status returns False and capture-failure persistence also fails (267, 279-280)
    bus3._delivery_failures.clear()
    store_ack_fail = MagicMock()
    store_ack_fail.get_trace_bytes.return_value = (json.dumps(row_with_seq) + "\n").encode("utf-8")
    store_ack_fail.update_run_status.side_effect = [False, RuntimeError("persist fail")]
    with pytest.raises(EvidenceDeliveryError):
        bus3.finalize_capture("r-term", store_ack_fail, complete=False)

    # 5. resume_capture failure branches (290, 318, 321)
    with pytest.raises(EvidenceDeliveryError, match="active or failed"):
        bus3.resume_capture("r-term", store_ack_fail)

    bus4 = EventEmitter(async_mode=False, run_id="r-res")
    store_res_fail = MagicMock()
    store_res_fail.get_run.return_value = {
        "status_details": {
            "evidence_capture": {"complete": False, "resumable": True, "event_count": 0}
        }
    }
    store_res_fail.get_trace_bytes.return_value = b""
    store_res_fail.update_run_status.return_value = False
    with patch("eval_runner.certification_truth.capture_receipt_failures", return_value=[]):
        with pytest.raises(EvidenceDeliveryError, match="resumption"):
            bus4.resume_capture("r-res", store_res_fail)

    store_res_inflight = MagicMock()
    store_res_inflight.get_run.return_value = {
        "status_details": {
            "evidence_capture": {"complete": False, "resumable": True, "event_count": 0}
        }
    }
    store_res_inflight.get_trace_bytes.return_value = b""

    def set_inflight(*_a, **_k):
        bus4._inflight_counts["r-res"] = 1
        return True

    store_res_inflight.update_run_status.side_effect = set_inflight
    with patch("eval_runner.certification_truth.capture_receipt_failures", return_value=[]):
        with pytest.raises(EvidenceDeliveryError, match="active evidence stream"):
            bus4.resume_capture("r-res", store_res_inflight)

    # 6. async_mode=True inside running loop: sync subscriber + OTel branches
    bus_async = EventEmitter(async_mode=True)
    called = []
    bus_async.subscribe(lambda ev: called.append(ev.name))

    async def noop_async(_ev):
        pass

    bus_async.subscribe(noop_async)
    with patch("opentelemetry.context.attach", side_effect=RuntimeError("attach err")):
        bus_async.emit("async_ev", {}, span_context={"traceparent": "00-1-2-01"})
        await asyncio.sleep(0.02)

    with patch.dict("sys.modules", {"opentelemetry.context": None}):
        bus_async.emit("async_ev_no_otel", {})
        await asyncio.sleep(0.02)
    assert "async_ev" in called

    # 7. Unsubscribe unknown callable, non-coroutine awaitable, and async without otel_ctx
    bus_async.unsubscribe(lambda _ev: None)

    class _Awaitable:
        def __await__(self):
            return iter([])

    bus_await = EventEmitter(async_mode=False, run_id="r-await")
    bus_await.subscribe(lambda _ev: _Awaitable(), required=True)
    with pytest.raises(EvidenceDeliveryError):
        bus_await.emit("ev_await", {})

    bus_async_no_ctx = EventEmitter(async_mode=True)
    async_hits = []

    async def hit_async(ev):
        async_hits.append(ev.name)

    bus_async_no_ctx.subscribe(hit_async)
    with patch("opentelemetry.context.get_current", return_value=None):
        bus_async_no_ctx.emit("ev_plain", {})
        await asyncio.sleep(0.02)
    assert "ev_plain" in async_hits

    bus_empty = EventEmitter(async_mode=False, run_id="r-empty-fin")
    with pytest.raises(EvidenceDeliveryError, match="IncompleteEvidenceCapture"):
        bus_empty.finalize_capture("r-empty-fin", MagicMock())
