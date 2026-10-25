from __future__ import annotations

import pytest

from eval_runner.events import CoreEvents, Event
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.reference.local_run_store import LocalFileRunStore


def test_recorder_rejects_provider_affinity_change(tmp_path):
    recorder = FlightRecorderPlugin()
    provider_a = LocalFileRunStore(tmp_path / "a")
    provider_b = LocalFileRunStore(tmp_path / "b")
    recorder.bind_run_provider("run", provider_a, {"tenant_id": "a"})

    with pytest.raises(RuntimeError, match="RunStorageProviderAffinityViolation"):
        recorder.bind_run_provider("run", provider_b, {"tenant_id": "b"})


def test_run_binding_carries_context_to_provider(tmp_path):
    class ContextCapturingStore(LocalFileRunStore):
        def __init__(self, root):
            super().__init__(root)
            self.contexts: list[dict | None] = []

        def append_events(self, run_id, events, context=None):
            self.contexts.append(context)
            return super().append_events(run_id, events, context=context)

    store = ContextCapturingStore(tmp_path / "provider")
    recorder = FlightRecorderPlugin()
    recorder.bind_run_provider("scoped", store, {"tenant_id": "tenant-a"})
    recorder.handle_event(Event(CoreEvents.RUN_START, {"run_id": "scoped"}))

    assert store.contexts == [{"tenant_id": "tenant-a"}]
