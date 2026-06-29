import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

from eval_runner import config

# SUT
from eval_runner.console.routes.runs import run_bp
from eval_runner.utils import rmtree_resilient


@pytest.fixture(scope="module")
def console_jail():
    tmp_root = Path(tempfile.gettempdir()) / "aes_console_runs_jail"
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


def test_explain_run_success(client, console_jail):
    run_id = "explain_me"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("trace", encoding="utf-8")

    with patch("eval_runner.console.routes.runs.explain_trace", return_value={"rca": "ok"}):
        res = client.get(f"/api/v1/explain/{run_id}")
        assert res.status_code == 200
        assert res.get_json()["analysis"]["rca"] == "ok"


def test_explain_run_404(client):
    res = client.get("/api/v1/explain/ghost")
    assert res.status_code == 404


def test_list_runs_fragment_vs_vault(client, console_jail):
    runs_dir = console_jail["runs"]
    # Clear runs_dir to avoid module-scope pollution from previous tests
    for item in list(runs_dir.iterdir()):
        if item.is_dir():
            rmtree_resilient(item)
        else:
            item.unlink()

    # 1. Fragment
    (runs_dir / "fragment.jsonl").write_text(
        '{"event": "run_start", "run_id": "f1", "scenario": "Scen1", "timestamp": "t1"}\n',
        encoding="utf-8",
    )
    # 2. Vault
    v1_dir = runs_dir / "v1"
    v1_dir.mkdir(parents=True, exist_ok=True)
    (v1_dir / "run.jsonl").write_text(
        '{"event": "run_start", "run_id": "v1", "scenario": "Scen2", "timestamp": "t2"}\n',
        encoding="utf-8",
    )

    res = client.get("/api/runs")
    data = res.get_json()["runs"]
    assert len(data) == 2
    ids = [r["run_id"] for r in data]
    assert "f1" in ids
    assert "v1" in ids


def test_list_runs_query_filter(client, console_jail):
    res = client.get("/api/runs?q=Scen2")
    data = res.get_json()["runs"]
    assert len(data) == 1
    assert data[0]["run_id"] == "v1"


def test_get_run_status_completed(client, console_jail):
    run_id = "done_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text(
        '{"event": "run_start"}\n{"event": "run_end", "status": "pass"}\n', encoding="utf-8"
    )

    res = client.get(f"/api/v1/runs/{run_id}")
    assert res.status_code == 200
    assert res.get_json()["status"] == "COMPLETED"


def test_get_run_status_running(client, console_jail):
    run_id = "active_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text('{"event": "run_start"}\n', encoding="utf-8")

    res = client.get(f"/api/v1/runs/{run_id}")
    assert res.status_code == 200
    assert res.get_json()["status"] == "RUNNING"


def test_get_verification_certificate_reports(client, console_jail):
    run_id = "cert_1"
    cert_path = console_jail["reports"] / "certificates" / "cert_1_vc.json"
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_text('{"cert": "ok"}', encoding="utf-8")

    res = client.get(f"/api/v1/certificates/{run_id}")
    assert res.status_code == 200
    assert res.get_json()["cert"] == "ok"


def test_get_verification_certificate_vault(client, console_jail):
    run_id = "cert_2"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_manifest.json").write_text('{"manifest": "ok"}', encoding="utf-8")

    res = client.get(f"/api/v1/certificates/{run_id}")
    assert res.status_code == 200
    assert res.get_json()["manifest"] == "ok"


def test_get_verification_certificate_404(client):
    res = client.get("/api/v1/certificates/none")
    assert res.status_code == 404


def test_list_runs_corrupt_json(client, console_jail):
    runs_dir = console_jail["runs"]
    # Corrupt fragment (invalid JSON)
    (runs_dir / "corrupt.jsonl").write_text("not json", encoding="utf-8")

    # Trigger scan
    res = client.get("/api/runs")
    assert res.status_code == 200
    # Should skip corrupt file. If it was the only one, list is empty.
    data = res.get_json()["runs"]
    ids = [r["run_id"] for r in data]
    assert "corrupt" not in ids


def test_get_run_status_tail_seek_error(client, console_jail):
    run_id = "tail_fail"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("data")

    with patch("os.path.getsize", side_effect=Exception("Seek Error")):
        res = client.get(f"/api/v1/runs/{run_id}")
        assert res.status_code == 200
        assert res.get_json()["status"] == "RUNNING"
    # mtime is also used, but getsize is first


def test_stream_run_logs_success(client, console_jail):
    run_id = "stream_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"
    log_file.write_text('{"event": "run_start"}\n{"event": "run_end"}\n', encoding="utf-8")

    res = client.get(f"/api/v1/runs/{run_id}/stream")
    assert res.status_code == 200
    assert res.mimetype == "text/event-stream"
    # Read the streamed lines
    data = res.get_data(as_text=True)
    assert 'data: {"event": "run_start"}' in data
    assert 'data: {"event": "run_end"}' in data


def test_stream_run_logs_timeout(client):
    res = client.get("/api/v1/runs/missing_run/stream")
    assert res.status_code == 200
    assert res.mimetype == "text/event-stream"
    data = res.get_data(as_text=True)
    assert "Execution log file not found" in data


def test_runs_route_explain_exception(client, console_jail):
    """Test explain_run endpoint exception handling."""
    run_id = "explain_fail"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("trace", encoding="utf-8")

    with patch(
        "eval_runner.console.routes.runs.explain_trace", side_effect=Exception("Explainer crash")
    ):
        res = client.get(f"/api/v1/explain/{run_id}")
        assert res.status_code == 500
        assert "Explainer crash" in res.get_json()["error"]


def test_runs_route_list_runs_edge_cases(client, console_jail):
    """Test runs listing edge cases including root run.jsonl skip and exceptions."""
    # Write a root run.jsonl that should be skipped
    (console_jail["runs"] / "run.jsonl").write_text(
        '{"event": "run_start", "run_id": "root", "scenario": "s"}\n', encoding="utf-8"
    )
    # Write a normal run
    r1_dir = console_jail["runs"] / "r1"
    r1_dir.mkdir(parents=True, exist_ok=True)
    (r1_dir / "run.jsonl").write_text(
        '{"event": "run_start", "run_id": "r1", "scenario": "s"}\n', encoding="utf-8"
    )

    # Test query filter mismatch
    res = client.get("/api/runs?q=nonexistent")
    assert res.status_code == 200
    assert len(res.get_json()["runs"]) == 0

    # Test read exception in list_runs
    with patch("builtins.open", side_effect=OSError("Read error")):
        res = client.get("/api/runs")
        assert res.status_code == 200
        # Should gracefully skip
        assert len(res.get_json()["runs"]) == 0


def test_runs_route_get_status_large_file(client, console_jail):
    """Test get_run_status with a log file larger than 128KB."""
    run_id = "large_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    large_data = "a" * (129 * 1024)
    (run_dir / "run.jsonl").write_text(large_data + '{"event": "run_end"}\n', encoding="utf-8")

    res = client.get(f"/api/v1/runs/{run_id}")
    assert res.status_code == 200
    assert res.get_json()["status"] == "COMPLETED"


def test_runs_route_get_status_stalled(client, console_jail):
    """Test get_run_status where the run has stalled (no activity for 5 mins)."""

    run_id = "stalled_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text('{"event": "run_start"}\n', encoding="utf-8")

    fake_mtime = time.time() - 400
    with (
        patch("os.path.getmtime", return_value=fake_mtime),
        patch("time.time", return_value=time.time()),
    ):
        res = client.get(f"/api/v1/runs/{run_id}")
        assert res.status_code == 200
        assert res.get_json()["status"] == "STALLED"


def test_runs_route_get_verification_certificate_corrupt(client, console_jail):
    """Test get_verification_certificate with a corrupt json file."""
    run_id = "corrupt_cert"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_manifest.json").write_text("invalid json", encoding="utf-8")

    res = client.get(f"/api/v1/certificates/{run_id}")
    assert res.status_code == 500
    assert "Corrupt manifest found" in res.get_json()["error"]


def test_runs_route_tail_file_generator_oserror_init(console_jail):
    """Test tail_file_generator OSError handling on initial stat check."""
    from eval_runner.console.routes.runs import tail_file_generator

    run_id = "oserror_init_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"
    log_file.write_text('{"event": "run_start"}\n', encoding="utf-8")

    # Mock stat to throw OSError specifically on target log_file stat check
    orig_stat = Path.stat
    import inspect

    def mock_stat(self, *args, **kwargs):
        # Lexical matching on target filename and scenario folder name to avoid
        # stat calls and RecursionErrors
        if self.name == "run.jsonl" and "oserror_init_run" in self.parts:
            # Only fail if not called during existence check (like log_path.exists())
            caller_names = [frame.function for frame in inspect.stack()]
            if "exists" not in caller_names:
                raise OSError("stat failed")
        return orig_stat(self, *args, **kwargs)

    with patch.object(Path, "stat", mock_stat):
        gen = tail_file_generator(log_file, run_id)
        # It should stream history first
        first_val = next(gen)
        assert '{"event": "run_start"}' in first_val


def test_runs_route_tail_file_generator_max_lifetime(console_jail):
    """Test tail_file_generator when connection max lifetime is exceeded."""

    from eval_runner.console.routes.runs import tail_file_generator

    run_id = "max_lifetime_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"
    log_file.write_text('{"event": "run_start"}\n', encoding="utf-8")

    gen = tail_file_generator(log_file, run_id)
    assert '{"event": "run_start"}' in next(gen)

    # Advance time mock past 1 hour to trigger lifetime check
    with patch("time.time", return_value=time.time() + 4000):
        res = next(gen)
        assert "Stream exceeded max connection lifetime" in res


def test_runs_route_tail_file_generator_file_deleted(console_jail):
    """Test tail_file_generator when the log file is deleted mid-stream."""
    from eval_runner.console.routes.runs import tail_file_generator

    run_id = "deleted_log_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"
    log_file.write_text('{"event": "run_start"}\n', encoding="utf-8")

    gen = tail_file_generator(log_file, run_id)
    assert '{"event": "run_start"}' in next(gen)

    # Mock log_file.exists returning False to simulate deletion without Windows lock errors
    with patch.object(Path, "exists", return_value=False):
        res = next(gen)
        assert "Log file deleted" in res


def test_runs_route_tail_file_generator_file_rotated(console_jail):
    """Test tail_file_generator when the log file is rotated mid-stream."""
    from eval_runner.console.routes.runs import tail_file_generator

    run_id = "rotated_log_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"
    log_file.write_text('{"event": "run_start"}\n', encoding="utf-8")

    gen = tail_file_generator(log_file, run_id)
    assert '{"event": "run_start"}' in next(gen)

    # Change inode value
    original_stat = Path.stat

    def mock_stat(self, *args, **kwargs):
        st = original_stat(self, *args, **kwargs)

        # Mock st_ino to return a different value to trigger rotation
        class MockStat:
            def __init__(self, old_st):
                self.st_ino = old_st.st_ino + 1
                self.st_mode = old_st.st_mode

        return MockStat(st)

    with patch.object(Path, "stat", mock_stat):
        res = next(gen)
        assert "Log file rotated" in res


def test_runs_route_tail_file_generator_zombie_and_heartbeat(console_jail):
    """Test tail_file_generator heartbeat and zombie process abortion."""
    from eval_runner.console.routes.runs import tail_file_generator

    run_id = "zombie_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"
    log_file.write_text('{"event": "run_start"}\n', encoding="utf-8")

    gen = tail_file_generator(log_file, run_id)
    assert '{"event": "run_start"}' in next(gen)

    # Mock time.sleep to not block
    # Ensure is_run_alive returns False
    with (
        patch("time.sleep"),
        patch("eval_runner.console.routes.runs.is_run_alive", return_value=False),
    ):
        # We manually drive the loop by fetching from generator.
        # It should send a heartbeat and zombie termination message
        # when idle_cycles reaches 150.
        # Let's check: first result should be heartbeat
        res1 = next(gen)
        assert "heartbeat" in res1
        # next result should be run_end aborted
        res2 = next(gen)
        assert "aborted" in res2
        assert "Process thread terminated abruptly" in res2


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


def test_runs_route_get_run_status_not_found_extra(client):
    """Test get_run_status 404 error (Line 162)"""
    res = client.get("/api/v1/runs/nonexistent_run_id_xyz")
    assert res.status_code == 404
    assert res.get_json()["error"] == "Run not found"


def test_runs_route_get_verification_certificate_corrupt_first_check(client, console_jail):
    """Test corrupt certificate file path handling (Lines 173-175)"""
    run_id = "corrupt_cert_direct"
    cert_path = console_jail["reports"] / "certificates" / f"{run_id}_vc.json"
    cert_path.parent.mkdir(parents=True, exist_ok=True)
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
    orig_stat = Path.stat
    import inspect

    def mock_stat(self, *args, **kwargs):
        # Lexical matching on target filename and scenario folder name to avoid
        # stat calls and RecursionErrors
        if self.name == "run.jsonl" and "transient_oserror_run" in self.parts:
            # Only fail if not called during existence check (like log_path.exists())
            caller_names = [frame.function for frame in inspect.stack()]
            if "exists" not in caller_names:
                raise OSError("Transient file access error")
        return orig_stat(self, *args, **kwargs)

    # In Python 3.12+, raising StopIteration in a generator results in RuntimeError.
    # Let's raise custom ValueError so we can catch it.
    with (
        patch.object(Path, "stat", mock_stat),
        patch("time.sleep", side_effect=ValueError("Stop loop")),
    ):
        with pytest.raises(ValueError, match="Stop loop"):
            next(gen)


# --- Coverage booster for runs.py ---


def test_runs_route_list_runs_first_line_empty_and_rid_parsing(client, console_jail):
    runs_dir = console_jail["runs"]

    # 1. Create a run with first line empty (Line 89 branch)
    r_empty_dir = runs_dir / "r_empty"
    r_empty_dir.mkdir(parents=True, exist_ok=True)
    r_empty_json = '\n{"event": "run_start", "run_id": "r_empty"}\n'
    (r_empty_dir / "run.jsonl").write_text(r_empty_json, encoding="utf-8")

    # 2. Create a run where scenario is missing and parsed from run_id (Lines 96-100)
    # Format: run-scenario_name-timestamp
    r_parse_dir = runs_dir / "run-scen1-12345"
    r_parse_dir.mkdir(parents=True, exist_ok=True)
    r_parse_json = '{"event": "run_start", "run_id": "run-scen1-12345"}\n'
    (r_parse_dir / "run.jsonl").write_text(r_parse_json, encoding="utf-8")

    # Format with length 2: run-scenario
    r_parse_short_dir = runs_dir / "run-scen2"
    r_parse_short_dir.mkdir(parents=True, exist_ok=True)
    r_parse_short_json = '{"event": "run_start", "run_id": "run-scen2"}\n'
    (r_parse_short_dir / "run.jsonl").write_text(r_parse_short_json, encoding="utf-8")

    res = client.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]

    # Verify r_empty was skipped (since first line was empty)
    assert not any(r["run_id"] == "r_empty" for r in runs)

    # Verify run-scen1-12345 was parsed and scenario is scen1
    parsed_run = next(r for r in runs if r["run_id"] == "run-scen1-12345")
    assert parsed_run["scenario"] == "scen1"

    # Verify run-scen2 was parsed and scenario is scen2 (Line 100)
    parsed_short_run = next(r for r in runs if r["run_id"] == "run-scen2")
    assert parsed_short_run["scenario"] == "scen2"


def test_runs_route_stream_tail_generator_branches(console_jail):
    from eval_runner.console.routes.runs import tail_file_generator

    run_id = "stream_branch_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"

    # 1. Write file with empty lines (Line 231->230 branch)
    log_file.write_text('\n\n{"event": "run_start"}\n\n', encoding="utf-8")

    gen1 = tail_file_generator(log_file, run_id)
    assert "run_start" in next(gen1)

    # 2. Test Stream Timeout (Line 245)
    # We patch time.time with 4 values: start_time (0), stream_start (0),
    # and then the loop checks (4000)
    with patch("time.time", side_effect=[0, 0, 4000, 4000, 4000]):
        gen2 = tail_file_generator(log_file, run_id)
        # First read yields run_start, next loop iteration will see timeout since
        # time.time() >= 4000
        assert "run_start" in next(gen2)
        err_msg = next(gen2)
        assert "Stream exceeded max connection lifetime" in err_msg
        with pytest.raises(StopIteration):
            next(gen2)

    # 3. Test Log file deleted during tail (Line 250)
    gen3 = tail_file_generator(log_file, run_id)
    assert "run_start" in next(gen3)
    with patch.object(Path, "exists", return_value=False):
        err_msg = next(gen3)
        assert "Log file deleted" in err_msg
        with pytest.raises(StopIteration):
            next(gen3)

    # 4. Test Log file rotated (Line 257)
    class MockStat:
        def __init__(self, ino):
            self.st_ino = ino

    gen4 = tail_file_generator(log_file, run_id)
    # Patch stat to return first inode, then return a different inode on second call
    with (
        patch.object(
            Path,
            "stat",
            side_effect=[MockStat(10), MockStat(10), MockStat(20), MockStat(20)],
        ),
        patch.object(Path, "exists", return_value=True),
    ):
        assert "run_start" in next(gen4)
        err_msg = next(gen4)
        assert "Log file rotated" in err_msg
        with pytest.raises(StopIteration):
            next(gen4)

    # 5. Test Zombie check (Line 278)
    gen5 = tail_file_generator(log_file, run_id)
    assert "run_start" in next(gen5)

    # We patch is_run_alive to return False
    # To hit line 278, we mock time.sleep to do nothing so the loop runs 150 cycles quickly
    with (
        patch("eval_runner.console.routes.runs.is_run_alive", return_value=False),
        patch("time.sleep", return_value=None),
        patch.object(Path, "exists", return_value=True),
    ):
        # Consume the generator fully
        results = list(gen5)
        assert any("Process thread terminated abruptly" in r for r in results)

    # 6. Test break when strategy_end/run_end in line (Line 284)
    log_file_end = run_dir / "run_end.jsonl"
    log_file_end_content = '{"event": "run_start"}\n{"event": "run_end"}\n'
    log_file_end.write_text(log_file_end_content, encoding="utf-8")
    gen6 = tail_file_generator(log_file_end, "run_end")
    assert "run_start" in next(gen6)
    # The next read should yield run_end and terminate the generator (not raise any error or wait)
    assert "run_end" in next(gen6)
    with pytest.raises(StopIteration):
        next(gen6)


def test_runs_route_stream_tail_generator_step_b_read(console_jail):
    from eval_runner.console.routes.runs import tail_file_generator

    run_id = "step_b_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"

    # Start with empty file
    log_file.write_text("", encoding="utf-8")

    gen = tail_file_generator(log_file, run_id)

    # First read (nothing in file, starts tailing loop). We mock time.sleep to write to the file!
    # This simulates a background process writing to the log file during the sleep cycle.
    written = False

    def mock_sleep(seconds):
        nonlocal written
        if not written:
            log_file.write_text('{"event": "run_end"}\n', encoding="utf-8")
            written = True

    with (
        patch("time.sleep", side_effect=mock_sleep),
        patch.object(Path, "exists", return_value=True),
    ):
        # This will sleep, trigger the mock_sleep to write the end event,
        # then read it in Step B, yield it, and break!
        res = next(gen)
        assert "run_end" in res

        # Verify generator terminates
        with pytest.raises(StopIteration):
            next(gen)
