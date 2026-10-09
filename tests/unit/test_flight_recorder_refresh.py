from eval_runner.events import CoreEvents, Event, unsubscribe
from eval_runner.flight_recorder import FlightRecorderPlugin


def test_flight_recorder_refresh_on_run_start(tmp_path, monkeypatch):
    """Test that FlightRecorderPlugin refreshes its config when a RUN_START event occurs."""
    initial_dir = tmp_path / "initial_dir"
    new_dir = tmp_path / "new_dir"
    default_dir = tmp_path / "default_dir"

    initial_dir.mkdir(parents=True, exist_ok=True)
    new_dir.mkdir(parents=True, exist_ok=True)
    default_dir.mkdir(parents=True, exist_ok=True)

    plugin = None
    try:
        monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", default_dir)
        monkeypatch.setenv("RUN_LOG_DIR", str(initial_dir))
        monkeypatch.setenv("RUN_LOG_ROTATE_COUNT", "0")
        monkeypatch.setenv("RUN_LOG_PER_RUN", "true")
        monkeypatch.setenv("RUN_LOG_MASTER", "true")

        plugin = FlightRecorderPlugin()
        assert str(plugin.log_dir) == str(initial_dir)

        monkeypatch.setenv("RUN_LOG_DIR", str(new_dir))
        event = Event(name=CoreEvents.RUN_START, data={"run_id": "test_refresh_run"})
        plugin.handle_event(event)

        assert str(plugin.log_dir) == str(new_dir)
        assert str(plugin.master_log_path) == str(new_dir / "run.jsonl")
    finally:
        if plugin:
            unsubscribe(plugin.handle_event)
            plugin.close_execution_writes("test_refresh_run")
            plugin.close_execution_writes(None)
