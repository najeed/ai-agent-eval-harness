import os

from eval_runner.events import CoreEvents, Event
from eval_runner.flight_recorder import FlightRecorderPlugin as FlightRecorder


def test_flight_recorder_per_run_false(tmp_path):
    """Test line 107: per_run is False."""
    fr = FlightRecorder()
    fr.log_dir = tmp_path
    os.environ["RUN_LOG_PER_RUN"] = "false"
    fr.per_run = False
    fr.handle_event(Event(name=CoreEvents.RUN_START, data={"run_id": "r1"}))
    assert fr.per_run_log_path is None
    # ensure it wrote master
    assert fr.master_log_path.exists()


def test_flight_recorder_write_exception(tmp_path, monkeypatch, capsys):
    """Test lines 137-138: Write exception handling in handle_event."""
    fr = FlightRecorder()
    fr.log_dir = tmp_path

    # Simulate an error inside _write_buffered
    def mock_write(*args, **kwargs):
        raise OSError("Simulated Write Error")

    # We can inject it by mocking the open function or handles
    fr._handles["fake"] = type("MockFile", (), {"write": mock_write})()

    # Actually it's easier to just patch builtins.open
    import builtins

    def raise_open(*args, **kwargs):
        raise OSError("Simulated Access Denied")

    with monkeypatch.context() as m:
        m.setattr(builtins, "open", raise_open)
        fr.handle_event(Event(name=CoreEvents.RUN_START, data={"run_id": "r1"}))

    assert "File I/O Error" in capsys.readouterr().err


def test_flight_recorder_finalize_run_exceptions(tmp_path, capsys, monkeypatch):
    """Test lines 145-161: finalize_run with physical sync and exceptions."""
    fr = FlightRecorder()
    fr.log_dir = tmp_path
    fr.handle_event(Event(name=CoreEvents.RUN_START, data={"run_id": "r1"}))

    # Let's forcefully cause os.fsync to raise a generic Exception
    def mock_fsync_generic(fd):
        raise OSError("Disk Sync Failed")

    with monkeypatch.context() as m:
        m.setattr(os, "fsync", mock_fsync_generic)
        fr.finalize_run()
        out = capsys.readouterr()
        assert "Finalization error on" in out.err

    # Test Shutdown race exception (AttributeError)
    fr = FlightRecorder()
    fr.log_dir = tmp_path
    fr.handle_event(Event(name="other", data={"run_id": "r2"}))

    def mock_fsync_race(fd):
        raise AttributeError("Expected Race")

    with monkeypatch.context() as m:
        m.setattr(os, "fsync", mock_fsync_race)
        fr.finalize_run()
        out = capsys.readouterr()
        assert "Shutdown race in finalize" in out.err


def test_flight_recorder_after_evaluation(tmp_path):
    """Test line 170: after_evaluation hook."""
    fr = FlightRecorder()
    fr.log_dir = tmp_path
    fr.handle_event(Event(name=CoreEvents.RUN_START, data={"run_id": "r1"}))
    assert len(fr._handles) > 0
    fr.after_evaluation({}, [])
    assert len(fr._handles) == 0


def test_flight_recorder_rotation_exception(tmp_path, monkeypatch, capsys):
    """Test lines 198-200: Global rotation scan failure."""
    fr = FlightRecorder()
    fr.log_dir = tmp_path

    # Force iterdir to raise an exception
    class BadPath(type(tmp_path)):
        def iterdir(self):
            raise PermissionError("Access Denied to directory")

    bad_dir = BadPath(tmp_path)
    fr.log_dir = bad_dir
    fr.rotate_logs()

    assert "Scan failure during vault rotation" in capsys.readouterr().err


def test_flight_recorder_flush(tmp_path, monkeypatch, capsys):
    """Test lines 206-211: explicit flush method."""
    fr = FlightRecorder()
    fr.log_dir = tmp_path
    fr.handle_event(Event(name=CoreEvents.RUN_START, data={"run_id": "r1"}))

    # Test valid flush
    fr.flush()

    # Test flush exception
    def mock_fsync(fd):
        raise OSError("Flush Error")

    with monkeypatch.context() as m:
        m.setattr(os, "fsync", mock_fsync)
        fr.flush()

    assert "Flush error" in capsys.readouterr().err
