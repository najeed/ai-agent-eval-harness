from __future__ import annotations

import pytest

from eval_runner.events import CoreEvents, Event
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.run_lifecycle import RunLifecycleState, get_run_lifecycle_state


def test_recorder_requires_explicit_provider_binding():
    from unittest.mock import patch

    with patch(
        "eval_runner.runtime_services.resolve_run_store",
        side_effect=RuntimeError("no default store"),
    ):
        recorder = FlightRecorderPlugin()

        with pytest.raises(RuntimeError, match="RunStorageProviderBindingRequired"):
            recorder.handle_event(Event(CoreEvents.RUN_START, {"run_id": "unbound"}))


def test_recorder_appends_only_to_bound_provider(tmp_path):
    store = LocalFileRunStore(tmp_path / "provider-a")
    recorder = FlightRecorderPlugin(run_store=store)

    recorder.handle_event(Event(CoreEvents.RUN_START, {"run_id": "provider-owned"}))
    recorder.handle_event(Event("step", {"run_id": "provider-owned", "value": 1}))

    events = store.get_events("provider-owned", offset=0, limit=100)
    assert [event["event"] for event in events] == ["run_start", "step"]
    assert [event["_seq"] for event in events] == [1, 2]
    assert store.get_trace_bytes("provider-owned")


def test_close_execution_writes_does_not_change_provider_lifecycle(tmp_path):
    store = LocalFileRunStore(tmp_path / "provider")
    recorder = FlightRecorderPlugin(run_store=store)
    run_id = "close-only"
    recorder.handle_event(Event(CoreEvents.RUN_START, {"run_id": run_id}))

    recorder.close_execution_writes(run_id)

    assert get_run_lifecycle_state(run_id, run_store=store) == RunLifecycleState.OPEN
