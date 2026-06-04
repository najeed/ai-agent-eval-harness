import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.runs import run_bp
from eval_runner.utils import rmtree_resilient


@pytest.fixture(scope="module")
def console_jail():
    tmp_root = Path(tempfile.gettempdir()) / "aes_console_runs_jail_extra"
    root = tmp_root / "root"
    runs = root / "runs"
    reports = root / "reports"

    if tmp_root.exists():
        rmtree_resilient(tmp_root)

    os.makedirs(runs, exist_ok=True)
    os.makedirs(reports / "certificates", exist_ok=True)
    yield {"root": root, "runs": runs, "reports": reports}

    if tmp_root.exists():
        rmtree_resilient(tmp_root)


@pytest.fixture
def client(console_jail, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(run_bp, url_prefix="/api")

    monkeypatch.setattr(config, "PROJECT_ROOT", console_jail["root"])
    monkeypatch.setattr(config, "RUN_LOG_DIR", console_jail["runs"])
    monkeypatch.setattr(config, "REPORTS_DIR", console_jail["reports"])

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


def test_runs_route_list_metrics(client):
    """Test GET /api/v1/metrics (Line 25)"""
    from eval_runner.metrics import MetricRegistry

    with patch.object(MetricRegistry, "list_metrics", return_value=["m1", "m2"]):
        res = client.get("/api/v1/metrics")
        assert res.status_code == 200
        assert res.get_json()["metrics"] == ["m1", "m2"]


def test_runs_route_list_runs_skip_vault_root(client, console_jail):
    """Test skipped root file in list_runs vault scan (Line 86)"""
    # Create run.jsonl directly in RUN_LOG_DIR
    log_file = console_jail["runs"] / "run.jsonl"
    log_file.write_text(
        '{"event": "run_start", "run_id": "root_run", "scenario": "s"}\n', encoding="utf-8"
    )

    # Since master log glob *.jsonl reads log files in RUN_LOG_DIR, list_runs
    # WILL find root_run via Master Log scan. But it should NOT process it in
    # vault scan. The way to check if vault scan ignored it is that it does
    # NOT have a "path" key.
    res = client.get("/api/runs")
    assert res.status_code == 200
    data = res.get_json()["runs"]
    # If it was processed by vault scan, it would have 'path' key.
    # Check that no run has 'path' of run.jsonl
    for run in data:
        if run["run_id"] == "root_run":
            assert "path" not in run

    # Cleanup
    log_file.unlink()


def test_runs_route_get_run_status_not_found(client):
    """Test get_run_status 404 error (Line 162)"""
    res = client.get("/api/v1/runs/nonexistent_run_id_xyz")
    assert res.status_code == 404
    assert res.get_json()["error"] == "Run not found"


def test_runs_route_get_verification_certificate_corrupt_first_check(client, console_jail):
    """Test corrupt certificate file path handling (Lines 173-175)"""
    run_id = "corrupt_cert_direct"
    cert_path = console_jail["reports"] / "certificates" / f"{run_id}_vc.json"
    cert_path.write_text("invalid json direct", encoding="utf-8")

    res = client.get(f"/api/v1/certificates/{run_id}")
    assert res.status_code == 500
    assert res.get_json()["error"] == "Corrupt certificate found"

    # Cleanup
    cert_path.unlink()


def test_runs_route_is_run_alive_helper():
    """Test is_run_alive helper with threads (Line 190)"""
    import threading

    from eval_runner.console.routes.runs import is_run_alive

    # Search for a thread name that doesn't exist
    assert not is_run_alive("definitely_not_alive_thread_12345")

    # Search for a mock thread that matches
    mock_thread = threading.Thread(name="eval-alive_thread_12345")
    with patch("threading.enumerate", return_value=[mock_thread]):
        assert is_run_alive("alive_thread_12345")


def test_runs_route_tail_file_generator_inode_rotation_transient_oserror(console_jail):
    """Test tail_file_generator with transient OSError in rotation check (Line 243)"""
    from eval_runner.console.routes.runs import tail_file_generator

    run_id = "transient_oserror_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"
    log_file.write_text('{"event": "run_start"}\n', encoding="utf-8")

    gen = tail_file_generator(log_file, run_id)
    assert '{"event": "run_start"}' in next(gen)

    # Mock Path.stat to raise OSError when checked for rotation, but path still exists

    def mock_stat(self, *args, **kwargs):
        raise OSError("Transient file access error")

    # In Python 3.12+, raising StopIteration in a generator results in RuntimeError.
    # Let's raise custom ValueError so we can catch it.
    with (
        patch.object(Path, "stat", mock_stat),
        patch("time.sleep", side_effect=ValueError("Stop loop")),
    ):
        with pytest.raises(ValueError, match="Stop loop"):
            next(gen)


def test_runs_route_tail_file_generator_error_rotated_branch(console_jail):
    """Test tail_file_generator rotation branch when inode differs (Line 242-243)"""
    from eval_runner.console.routes.runs import tail_file_generator

    run_id = "rotation_branch_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"
    log_file.write_text('{"event": "run_start"}\n', encoding="utf-8")

    gen = tail_file_generator(log_file, run_id)
    assert '{"event": "run_start"}' in next(gen)

    # Mock st_ino difference
    class MockStat:
        def __init__(self):
            self.st_ino = 99999
            self.st_mode = 0

    with patch.object(Path, "stat", return_value=MockStat()):
        res = next(gen)
        assert "Log file rotated" in res


def test_runs_route_tail_file_generator_immediate_termination(console_jail):
    """Test immediate termination on run_end / strategy_end in catch-up stream (Line 219-220)"""
    from eval_runner.console.routes.runs import tail_file_generator

    run_id = "term_immediate_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"
    # Immediately ended in historical
    log_file.write_text('{"event": "run_start"}\n{"event": "run_end"}\n', encoding="utf-8")

    gen = tail_file_generator(log_file, run_id)
    # The first yield:
    assert '{"event": "run_start"}' in next(gen)
    # The second yield:
    assert '{"event": "run_end"}' in next(gen)
    # The third next() should raise StopIteration because generator returned
    # on run_end detection in line 220
    with pytest.raises(StopIteration):
        next(gen)


def test_runs_route_tail_file_generator_loop_new_line_yields(console_jail):
    """Test tail_file_generator loops, reads a new line from readline, and yields (Lines 267-271)"""
    from eval_runner.console.routes.runs import tail_file_generator

    run_id = "loop_new_line_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"
    log_file.write_text('{"event": "run_start"}\n', encoding="utf-8")

    gen = tail_file_generator(log_file, run_id)
    assert '{"event": "run_start"}' in next(gen)

    # Now let's append a new line to the file
    with open(log_file, "a", encoding="utf-8") as f:
        f.write('{"event": "run_end"}\n')

    # Fetch next from generator; it should read the new line, reset
    # idle_cycles (line 267), yield the line (line 268) and then break
    # the loop because it has run_end (line 270-271)
    res = next(gen)
    assert '{"event": "run_end"}' in res

    with pytest.raises(StopIteration):
        next(gen)
