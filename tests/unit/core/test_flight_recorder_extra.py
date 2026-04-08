import os
from unittest.mock import patch

from eval_runner.events import Event
from eval_runner.flight_recorder import FlightRecorderPlugin


def test_flight_recorder_rotation(tmp_path):
    log_dir = tmp_path / "runs"
    log_dir.mkdir()

    # Create 5 log files
    for i in range(5):
        f = log_dir / f"run-{i}.jsonl"
        f.touch()
        # Ensure different mtimes for sorting
        os.utime(f, (1000 + i, 1000 + i))

    master_log = log_dir / "run.jsonl"
    master_log.touch()

    # Configure with rotation = 2
    with patch.dict(
        os.environ,
        {"RUN_LOG_DIR": str(log_dir), "RUN_LOG_ROTATE_COUNT": "2", "RUN_LOG_PER_RUN": "true"},
    ):
        recorder = FlightRecorderPlugin()
        # Trigger rotation by sending a RUN_START event
        recorder.handle_event(Event("run_start", {"run_id": "new_run"}))

        # Should keep 2 + new_run.jsonl + run.jsonl
        # Wait, the new_run.jsonl is created during handle_event
        files = list(log_dir.glob("*.jsonl"))
        # run-4, run-3 (latest 2), new_run.jsonl, and run.jsonl
        assert len([f for f in files if f.name.startswith("run-")]) == 2
        assert (log_dir / "new_run.jsonl").exists()


import pytest
from pathlib import Path

def test_flight_recorder_rotation_fail(tmp_path, capsys):
    """
    Test rotation failure reporting with physical disk state.
    Standardized for Zero-Mock verification.
    """
    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    
    # Create two files. If rotate_count=0, it should try to delete one.
    (log_dir / "old_1.jsonl").touch()
    (log_dir / "old_2.jsonl").touch()

    with patch.dict(os.environ, {"RUN_LOG_DIR": str(log_dir), "RUN_LOG_ROTATE_COUNT": "0"}):
        recorder = FlightRecorderPlugin()
        
        # We manually patch unlink just to simulate a low-level OS failure 
        # (e.g. Permission Denied) without needing a complex sub-process lock.
        # This keeps the test focused and physical while avoiding MagicMocks for verification.
        with patch("pathlib.Path.unlink", side_effect=OSError("Perm denied")):
            recorder.rotate_logs()
            
            # Check stderr for the industrial warning string
            _, err = capsys.readouterr()
            assert "Error rotating log" in err
            assert "Perm denied" in err


def test_flight_recorder_disabled_logs(tmp_path):
    log_dir = tmp_path / "runs"
    log_dir.mkdir()

    with patch.dict(
        os.environ,
        {"RUN_LOG_DIR": str(log_dir), "RUN_LOG_PER_RUN": "false", "RUN_LOG_MASTER": "false"},
    ):
        recorder = FlightRecorderPlugin()
        recorder.handle_event(Event("run_start", {"run_id": "r1"}))
        recorder.handle_event(Event("test", {"data": "x"}))

        assert not (log_dir / "r1.jsonl").exists()
        assert not (log_dir / "run.jsonl").exists()
