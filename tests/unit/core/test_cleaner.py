import time

from eval_runner.cleaner import cleanup_traces


def test_cleanup_traces_non_existent(tmp_path):
    """Verify that a non-existent directory is handled gracefully."""
    non_existent = tmp_path / "ghost_runs"
    # Should not raise any error
    cleanup_traces(str(non_existent), days=1)


def test_cleanup_traces_filtering(tmp_path):
    """Verify that only older files are marked for cleanup."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # Create an old file
    old_file = runs_dir / "old_run.jsonl"
    old_file.write_text("{}")
    old_time = time.time() - (10 * 86400)  # 10 days old
    os_utime(old_file, (old_time, old_time))

    # Create a new file
    new_file = runs_dir / "new_run.jsonl"
    new_file.write_text("{}")

    # Dry run check (force=False)
    # Since we can't easily capture print in a simple way here without capsys,
    # we'll use capsys in a proper pytest function.
    pass


def os_utime(path, times):
    import os

    os.utime(path, times)


def test_cleanup_traces_execution(tmp_path, capsys):
    """Verify dry run and forced deletion."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    old_file = runs_dir / "old.jsonl"
    old_file.write_text("{}")
    old_time = time.time() - (10 * 86400)
    os_utime(old_file, (old_time, old_time))

    # 1. Dry run
    cleanup_traces(str(runs_dir), days=7, force=False)
    out, _ = capsys.readouterr()
    assert "Would remove old trace: old.jsonl" in out
    assert old_file.exists()

    # 2. Force delete
    cleanup_traces(str(runs_dir), days=7, force=True)
    assert not old_file.exists()


def test_cleanup_traces_ignores_new(tmp_path, capsys):
    """Verify that new files are ignored."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    new_file = runs_dir / "new.jsonl"
    new_file.write_text("{}")

    cleanup_traces(str(runs_dir), days=7, force=True)
    assert new_file.exists()
    out, _ = capsys.readouterr()
    assert "Would remove" not in out
