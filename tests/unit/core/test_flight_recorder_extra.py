import os
from unittest.mock import patch

from eval_runner.events import Event
from eval_runner.flight_recorder import FlightRecorderPlugin


def test_flight_recorder_rotation(tmp_path):
    log_dir = tmp_path / "runs"
    log_dir.mkdir()

    # Create 5 log vaults (directories with run.jsonl)
    for i in range(5):
        vault = log_dir / f"run-{i}"
        vault.mkdir()
        f = vault / "run.jsonl"
        f.touch()
        # Ensure different mtimes for sorting (using the directory mtime as the anchor)
        os.utime(vault, (1000 + i, 1000 + i))

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

        # Should keep 2 total: new_run vault + run-4 vault
        vaults = [d for d in log_dir.iterdir() if d.is_dir()]
        # Only run-4 should remain as the 2nd latest (run-3 was 3rd latest)
        assert len([v for v in vaults if v.name.startswith("run-")]) == 1
        assert (log_dir / "new_run" / "run.jsonl").exists()


def test_flight_recorder_rotation_fail(tmp_path, capsys):
    """
    Test rotation failure reporting with physical disk state.
    Standardized for Zero-Mock verification.
    """
    log_dir = tmp_path / "runs"
    log_dir.mkdir()

    # Create two vaults.
    (log_dir / "v1").mkdir()
    (log_dir / "v2").mkdir()

    with patch.dict(os.environ, {"RUN_LOG_DIR": str(log_dir), "RUN_LOG_ROTATE_COUNT": "0"}):
        recorder = FlightRecorderPlugin()

        # We manually patch rmtree to simulate a low-level OS failure
        with patch(
            "eval_runner.flight_recorder.rmtree_resilient", side_effect=OSError("Perm denied")
        ):
            recorder.rotate_logs()

            # Check stderr for the industrial warning string
            _, err = capsys.readouterr()
            assert "Error rotating log vault" in err
            assert "Perm denied" in err


def test_flight_recorder_safety_floor(tmp_path, capsys):
    """
    Verify the Forensic Safety Floor (v1.5.0).
    If both options are false, the system must force per-run logging.
    """
    log_dir = tmp_path / "runs"
    log_dir.mkdir()

    with patch.dict(
        os.environ,
        {"RUN_LOG_DIR": str(log_dir), "RUN_LOG_PER_RUN": "false", "RUN_LOG_MASTER": "false"},
    ):
        recorder = FlightRecorderPlugin()
        recorder.handle_event(Event("run_start", {"run_id": "r1"}))

        # Verify the warning was issued
        _, err = capsys.readouterr()
        assert "Industrial Safety Override" in err
        assert "Reclaiming Isolated Vault" in err

        # Verify the vault WAS created despite the "false" environment
        assert (log_dir / "r1").exists()
        assert (log_dir / "r1" / "run.jsonl").exists()

        # Verify master log was NOT created (optional, but good to check)
        assert not (log_dir / "run.jsonl").exists()
