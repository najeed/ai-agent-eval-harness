from __future__ import annotations

from eval_runner.events import CoreEvents, Event
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.reference.local_run_store import LocalFileRunStore


def test_recorder_does_not_reconfigure_storage_from_environment(tmp_path, monkeypatch):
    store = LocalFileRunStore(tmp_path / "provider")
    recorder = FlightRecorderPlugin(run_store=store)
    monkeypatch.setenv("RUN_LOG_DIR", str(tmp_path / "ignored"))
    monkeypatch.setenv("RUN_LOG_MASTER", "true")

    recorder.handle_event(Event(CoreEvents.RUN_START, {"run_id": "environment-isolation"}))

    assert store.get_events("environment-isolation", offset=0, limit=100)
    assert not (tmp_path / "ignored").exists()
