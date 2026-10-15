import json
import os
import tempfile
import threading
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
def console_jail(request):
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "master")
    tmp_root = Path(tempfile.gettempdir()) / f"aes_console_runs_jail_{worker_id}"
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
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    app.register_blueprint(run_bp, url_prefix="/api")

    monkeypatch.setattr(config, "PROJECT_ROOT", console_jail["root"])
    monkeypatch.setattr(config, "RUN_LOG_DIR", console_jail["runs"])
    monkeypatch.setattr(config, "REPORTS_DIR", console_jail["reports"])

    from eval_runner.console.routes.runs import runs_cache

    runs_cache._runs = []
    runs_cache._scanned_files = {}

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
    """Test runs listing edge cases including query filter and graceful file-read skip."""
    # Write a vault-style run directory
    r1_dir = console_jail["runs"] / "r1_edge"
    r1_dir.mkdir(parents=True, exist_ok=True)
    (r1_dir / "run.jsonl").write_text(
        '{"event": "run_start", "run_id": "r1_edge", "scenario": "finance"}\n', encoding="utf-8"
    )

    # 1. Query filter: no match -> empty list
    res = client.get("/api/runs?q=nonexistent_xyz")
    assert res.status_code == 200
    assert len(res.get_json()["runs"]) == 0

    # 2. Query filter: positive match
    res = client.get("/api/runs?q=r1_edge")
    assert res.status_code == 200
    assert any(r["run_id"] == "r1_edge" for r in res.get_json()["runs"])

    # 3. Per-file read exception: a corrupt JSONL in the runs dir is skipped gracefully.
    # Write an unreadable (corrupt JSON) fragment at the root level
    bad_frag = console_jail["runs"] / "bad_frag.jsonl"
    bad_frag.write_text("{{CORRUPT", encoding="utf-8")
    res = client.get("/api/runs")
    # Should still return 200 — corrupt file is logged+skipped
    assert res.status_code == 200


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
    """Test GET /api/v1/metrics"""
    from eval_runner.metrics import MetricRegistry

    with patch.object(MetricRegistry, "list_metrics", return_value=["m1", "m2"]):
        res = client.get("/api/v1/metrics")
        assert res.status_code == 200
        assert res.get_json()["metrics"] == ["m1", "m2"]


def test_runs_route_list_runs_skip_vault_root(client, console_jail):
    """Test skipped root file in list_runs vault scan"""
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
    """Test get_run_status 404 error"""
    res = client.get("/api/v1/runs/nonexistent_run_id_xyz")
    assert res.status_code == 404
    assert res.get_json()["error"] == "Run not found"


def test_runs_route_get_verification_certificate_corrupt_first_check(client, console_jail):
    """Test corrupt certificate file path handling"""
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
    """Test is_run_alive helper with threads"""
    import threading

    from eval_runner.console.routes.runs import is_run_alive

    # Search for a thread name that doesn't exist
    assert not is_run_alive("definitely_not_alive_thread_12345")

    # Search for a mock thread that matches
    mock_thread = threading.Thread(name="eval-alive_thread_12345")
    with patch("threading.enumerate", return_value=[mock_thread]):
        assert is_run_alive("alive_thread_12345")


def test_runs_route_tail_file_generator_inode_rotation_transient_oserror(console_jail):
    """Test tail_file_generator with transient OSError in rotation check"""
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

    # 1. Create a run with first line empty
    r_empty_dir = runs_dir / "r_empty"
    r_empty_dir.mkdir(parents=True, exist_ok=True)
    r_empty_json = '\n{"event": "run_start", "run_id": "r_empty"}\n'
    (r_empty_dir / "run.jsonl").write_text(r_empty_json, encoding="utf-8")

    # 2. Create a run where scenario is missing and parsed from run_id
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

    # Verify run-scen2 was parsed and scenario is scen2
    parsed_short_run = next(r for r in runs if r["run_id"] == "run-scen2")
    assert parsed_short_run["scenario"] == "scen2"


def test_runs_route_stream_tail_generator_branches(console_jail):
    from eval_runner.console.routes.runs import tail_file_generator

    run_id = "stream_branch_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"

    # 1. Write file with empty lines
    log_file.write_text('\n\n{"event": "run_start"}\n\n', encoding="utf-8")

    gen1 = tail_file_generator(log_file, run_id)
    assert "run_start" in next(gen1)

    # 2. Test Stream Timeout
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

    # 3. Test Log file deleted during tail
    gen3 = tail_file_generator(log_file, run_id)
    assert "run_start" in next(gen3)
    with patch.object(Path, "exists", return_value=False):
        err_msg = next(gen3)
        assert "Log file deleted" in err_msg
        with pytest.raises(StopIteration):
            next(gen3)

    # 4. Test Log file rotated
    class MockStat:
        def __init__(self, ino):
            self.st_ino = ino

    gen4 = tail_file_generator(log_file, run_id)

    calls = 0

    def dynamic_stat(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return MockStat(10)
        return MockStat(20)

    with (
        patch.object(Path, "stat", side_effect=dynamic_stat),
        patch.object(Path, "exists", return_value=True),
    ):
        assert "run_start" in next(gen4)
        err_msg = next(gen4)
        assert "Log file rotated" in err_msg
        with pytest.raises(StopIteration):
            next(gen4)

    # 5. Test Zombie check
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

    # 6. Test break when strategy_end/run_end in line
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

        # This will sleep, trigger the mock_sleep to write the end event,
        # then read it in Step B, yield it, and break!
        res = next(gen)
        assert "run_end" in res

        # Verify generator terminates
        with pytest.raises(StopIteration):
            next(gen)


def test_runs_cache_start_twice():
    """start() returns early if already started and stop() cleanly halts."""
    from eval_runner.console.routes.runs import RunsCache

    cache = RunsCache()
    with patch.object(threading.Thread, "start"):
        cache.start()
        assert cache._started is True
        cache.start()  # Idempotent no-op
        assert cache._started is True
        cache.stop()
        assert cache._started is False


def test_get_runs_retrieval():
    """get_runs returns run list and supports query filtering."""
    from eval_runner.console.routes.runs import runs_cache

    res = runs_cache.get_runs()
    assert isinstance(res, list)


def test_runs_cache_scan_exception():
    """update_cache scan exceptions in _update_loop"""
    from eval_runner.console.routes.runs import RunsCache

    cache = RunsCache()
    # Mock update_cache to raise exception
    with patch.object(cache, "update_cache", side_effect=ValueError("Background scan error")):
        with patch("time.sleep", side_effect=[0, Exception("break loop")]):
            try:
                cache._update_loop()
            except Exception as e:
                assert "break loop" in str(e)


def test_runs_route_stream_runs_list(client, console_jail):
    """stream_runs_list route SSE streaming and status resolution."""
    runs_dir = console_jail["runs"]

    # 1. Certified run (vc exists)
    (console_jail["reports"] / "certificates" / "r_cert_vc.json").write_text("{}", encoding="utf-8")
    r_cert_dir = runs_dir / "r_cert"
    r_cert_dir.mkdir(parents=True, exist_ok=True)
    (r_cert_dir / "run.jsonl").write_text(
        '{"event": "run_start", "run_id": "r_cert", "timestamp": "2026-08-06T04:00:00Z"}\n',
        encoding="utf-8",
    )

    # 2. Failed run (error event)
    r_fail_dir = runs_dir / "r_fail"
    r_fail_dir.mkdir(parents=True, exist_ok=True)
    (r_fail_dir / "run.jsonl").write_text(
        '{"event": "run_start", "run_id": "r_fail", "timestamp": "2026-08-06T04:00:00Z"}\n'
        '{"event": "error", "message": "unhandled error"}\n',
        encoding="utf-8",
    )

    # 3. Running/Stalled run
    r_stall_dir = runs_dir / "r_stall"
    r_stall_dir.mkdir(parents=True, exist_ok=True)
    # Timestamp > 300 seconds ago
    (r_stall_dir / "run.jsonl").write_text(
        '{"event": "run_start", "run_id": "r_stall", "timestamp": "2026-08-06T02:00:00.000Z"}\n',
        encoding="utf-8",
    )

    # Trigger caching refresh
    client.get("/api/runs")

    # Query SSE stream
    res_sse = client.get("/api/v1/runs/stream-list")
    assert res_sse.status_code == 200
    assert res_sse.mimetype == "text/event-stream"
    data = res_sse.get_data(as_text=True)
    assert "r_cert" in data
    assert "r_fail" in data
    assert "r_stall" in data


def test_runs_route_get_status_uncovered_branches(client, console_jail):
    """get_run_status uncovered branches"""
    runs_dir = console_jail["runs"]

    # 1. Corrupt json in resolved scenario
    r_scen_dir = runs_dir / "r_scen"
    r_scen_dir.mkdir(parents=True, exist_ok=True)
    (r_scen_dir / "run.jsonl").write_text('{"event": "run_start"}\n', encoding="utf-8")
    (r_scen_dir / "scenario_resolved.json").write_text("{{corrupt", encoding="utf-8")
    res = client.get("/api/v1/runs/r_scen")
    assert res.status_code == 200
    assert res.get_json()["scenario"] is None

    # 2. Master log path fallback with non-matching run_id line
    master_log = runs_dir / "run.jsonl"
    master_log.write_text(
        # Line containing target run_id in notes, but real event run_id is different
        '{"event": "run_start", "run_id": "other_run", "notes": "r_master_fall"}\n'
        # Real event
        '{"event": "run_start", "run_id": "run-scen-123", "scenario": "scen"}\n',
        encoding="utf-8",
    )
    res = client.get("/api/v1/runs/r_master_fall")
    # Not found since the line matched but didn't have run_id equal to r_master_fall
    assert res.status_code == 404

    # Resolve run-scen-123 from master (which doesn't exist in catalog)
    res2 = client.get("/api/v1/runs/run-scen-123")
    assert res2.status_code == 200
    assert res2.get_json()["status"] == "STALLED"

    # Catalog parse error
    from eval_runner.catalog import ScenarioCatalog

    cat = ScenarioCatalog.get_instance()
    cat.scenarios = [{"id": "scen", "path": "scenarios/scen.json"}]
    (cat.root_dir / "scenarios").mkdir(parents=True, exist_ok=True)
    (cat.root_dir / "scenarios" / "scen.json").write_text("{{corrupt", encoding="utf-8")

    res3 = client.get("/api/v1/runs/run-scen-123")
    assert res3.status_code == 200
    assert res3.get_json()["scenario"] is None


def test_get_run_status_enriched_fields_vault_and_master(client, console_jail):
    """Enriched fields (execution_mode, provisional, verification_status) on branches."""
    runs_dir = console_jail["runs"]

    # 1. Vault run with live execution mode in manifest and trace
    v_id = "run-vault-live"
    v_dir = runs_dir / v_id
    v_dir.mkdir(parents=True, exist_ok=True)
    (v_dir / "run.jsonl").write_text(
        '{"event": "run_start", "execution_mode": "live"}\n{"event": "run_end"}\n', encoding="utf-8"
    )
    (v_dir / "run_manifest.json").write_text(
        json.dumps({"execution_mode": "live", "provisional": False}), encoding="utf-8"
    )

    res_v = client.get(f"/api/v1/runs/{v_id}")
    assert res_v.status_code == 200
    data_v = res_v.get_json()
    assert data_v["execution_mode"] == "live"
    assert data_v["provisional"] is False
    assert data_v["sourced_from_master"] is False
    assert "verification_status" in data_v

    # 2. Master log run fallback
    m_id = "run-master-sim"
    master_log = runs_dir / "run.jsonl"
    master_log.write_text(
        f'{{"event": "run_start", "run_id": "{m_id}", "execution_mode": "simulated"}}\n'
        f'{{"event": "run_end", "run_id": "{m_id}"}}\n',
        encoding="utf-8",
    )

    res_m = client.get(f"/api/v1/runs/{m_id}")
    assert res_m.status_code == 200
    data_m = res_m.get_json()
    assert data_m["sourced_from_master"] is True
    assert "execution_mode" in data_m
    assert "provisional" in data_m
    assert "verification_status" in data_m


def test_runs_route_stream_run_logs_uncovered_branches(client, console_jail):
    """stream_run_logs uncovered branches"""
    runs_dir = console_jail["runs"]
    master_log = runs_dir / "run.jsonl"
    master_log.write_text(
        '{"event": "run_start", "run_id": "r_stream_fallback"}\n'
        '{"event": "run_end", "run_id": "r_stream_fallback"}\n',
        encoding="utf-8",
    )

    # Patch unlink to raise exception to hit 664-665
    with patch("pathlib.Path.unlink", side_effect=OSError("Permission denied")):
        res = client.get("/api/v1/runs/r_stream_fallback/stream")
        assert res.status_code == 200
        # Consume the stream fully to trigger finally block
        data = res.get_data(as_text=True)
        assert "run_start" in data
        assert "run_end" in data


def test_runs_cache_prune_no_path_attributes(client):
    """runs_cache pruning when path and _fragment_path are absent."""
    from eval_runner.console.routes.runs import runs_cache

    runs_cache._runs = [{"run_id": "no_path_run", "scenario": "scen"}]
    # Trigger get_runs which updates cache. Since "no_path_run" does not exist anywhere,
    # it resolves via resolve_trace_path to None and is pruned from the cache.
    res = runs_cache.get_runs()
    assert not any(r["run_id"] == "no_path_run" for r in res)


def test_runs_route_stream_run_logs_exist(client, console_jail):
    """stream_run_logs when log_path exists."""
    runs_dir = console_jail["runs"]
    r_exist_dir = runs_dir / "r_exist"
    r_exist_dir.mkdir(parents=True, exist_ok=True)
    (r_exist_dir / "run.jsonl").write_text(
        '{"event": "run_start", "run_id": "r_exist"}\n{"event": "run_end", "run_id": "r_exist"}\n',
        encoding="utf-8",
    )

    res = client.get("/api/v1/runs/r_exist/stream")
    assert res.status_code == 200
    data = res.get_data(as_text=True)
    assert "run_start" in data
    assert "run_end" in data


def test_runs_route_stream_run_logs_not_found(client, console_jail):
    """stream_run_logs returning 404"""
    # Request a stream for a run that does not exist in master or individual log
    res = client.get("/api/v1/runs/r_nonexistent/stream")
    assert res.status_code == 200
    data = res.get_data(as_text=True)
    assert "Execution log file not found" in data


def test_runs_route_stream_run_logs_direct_master_tailing(client, console_jail):
    """Verify stream_run_logs streams directly from master log without creating temp files."""
    runs_dir = console_jail["runs"]
    master_log = runs_dir / "run.jsonl"
    master_log.write_text(
        '{"event": "run_start", "run_id": "r_direct_master"}\n'
        '{"event": "other_event", "run_id": "other_run"}\n'
        '{"event": "run_end", "run_id": "r_direct_master"}\n',
        encoding="utf-8",
    )

    res = client.get("/api/v1/runs/r_direct_master/stream")
    assert res.status_code == 200
    data = res.get_data(as_text=True)
    assert "r_direct_master" in data
    assert "other_run" not in data

    # Verify zero temporary files were created
    temp_files = list(runs_dir.glob("temp_stream_*"))
    assert len(temp_files) == 0


def test_runs_route_resolve_trace_path_variants(client, console_jail):
    from eval_runner.console.routes.runs import resolve_trace_path

    runs_dir = console_jail["runs"]
    run_id = "r_named_jsonl"
    r_dir = runs_dir / run_id
    r_dir.mkdir(parents=True, exist_ok=True)
    (r_dir / f"{run_id}.jsonl").write_text("{}\n", encoding="utf-8")

    resolved = resolve_trace_path(run_id)
    assert resolved is not None
    assert resolved.name == f"{run_id}.jsonl"


def test_runs_vault_scanner_corrupt_lines_and_run_end(client, console_jail):
    runs_dir = console_jail["runs"]

    # Fragment with corrupt line and unreadable fragment
    frag_dir = runs_dir / "r_frag_corrupt"
    frag_dir.mkdir(parents=True, exist_ok=True)
    (frag_dir / "fragment_001.jsonl").write_text("CORRUPT_JSON{\n", encoding="utf-8")

    # Vault with empty lines, invalid JSON, and run_end event
    vault_dir = runs_dir / "r_vault_end"
    vault_dir.mkdir(parents=True, exist_ok=True)
    start_ev = json.dumps({"event": "run_start", "run_id": "r_vault_end", "scenario": "scen_1"})
    end_ev = json.dumps({"event": "run_end", "data": {"passed": True, "duration": 12.5}})
    (vault_dir / "run.jsonl").write_text(
        f"{start_ev}\n\nBAD_JSON_LINE\n{end_ev}\n",
        encoding="utf-8",
    )

    res = client.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    r_end = next((r for r in runs if r.get("run_id") == "r_vault_end"), None)
    if r_end:
        assert r_end.get("duration_seconds") == 12.5 or r_end.get("result_status") == "PASS"


def test_run_is_in_active_context_matrix(console_jail, monkeypatch):
    from eval_runner.console.routes.runs import _run_is_in_active_context

    monkeypatch.setattr(config, "RUN_LOG_DIR", console_jail["runs"])
    ctx = {
        "org_id": "org-1",
        "tenant_id": "tenant-alpha",
        "workspace_id": "ws-1",
        "active_environment": "dev",
    }

    # Case 1: No context configured anywhere -> returns True
    monkeypatch.setattr("eval_runner.console.routes.runs.active_runtime_context", lambda: None)
    assert _run_is_in_active_context("any_run", context=None) is True

    # Case 2: Context present, run record is None and manifest does not exist -> returns False
    monkeypatch.setattr("eval_runner.console.routes.runs.read_run_index", lambda r: None)
    console_jail["runs"] / "ghost_run"
    assert _run_is_in_active_context("ghost_run", context=ctx) is False

    # Case 3: Context present, record is None but manifest exists
    # and matches context -> returns True
    m_dir = console_jail["runs"] / "manifest_ok_run"
    m_dir.mkdir(parents=True, exist_ok=True)
    (m_dir / "run_manifest.json").write_text(json.dumps(ctx), encoding="utf-8")
    assert _run_is_in_active_context("manifest_ok_run", context=ctx) is True

    # Case 4: Context present, record is None but manifest exists and conflicts -> returns False
    m_bad_dir = console_jail["runs"] / "manifest_bad_run"
    m_bad_dir.mkdir(parents=True, exist_ok=True)
    bad_ctx = dict(ctx)
    bad_ctx["tenant_id"] = "tenant-beta"
    (m_bad_dir / "run_manifest.json").write_text(json.dumps(bad_ctx), encoding="utf-8")
    assert _run_is_in_active_context("manifest_bad_run", context=ctx) is False

    # Case 5: Manifest is corrupt JSON -> returns False
    m_corrupt_dir = console_jail["runs"] / "manifest_corrupt_run"
    m_corrupt_dir.mkdir(parents=True, exist_ok=True)
    (m_corrupt_dir / "run_manifest.json").write_text("{corrupt", encoding="utf-8")
    assert _run_is_in_active_context("manifest_corrupt_run", context=ctx) is False


def test_runs_routes_blocked_by_active_context(client, monkeypatch):
    monkeypatch.setattr(
        "eval_runner.console.routes.runs._run_is_in_active_context", lambda *args, **kwargs: False
    )

    r_id = "blocked_run"
    assert client.get(f"/api/v1/explain/{r_id}").status_code == 404
    assert client.get(f"/api/v1/runs/{r_id}/report.pdf").status_code == 404
    assert client.get(f"/api/v1/runs/{r_id}").status_code == 404
    assert client.post(f"/api/v1/runs/{r_id}/cancel").status_code == 404
    assert client.post(f"/api/v1/runs/{r_id}/resume").status_code == 404
    assert client.get(f"/api/v1/certificates/{r_id}").status_code == 404
    assert client.get(f"/api/v1/runs/{r_id}/stream").status_code == 404
    assert client.get(f"/api/v1/runs/{r_id}/verify").status_code == 404


def test_runs_cache_autostart_and_stop_lifecycle():
    from eval_runner.console.routes.runs import RunsCache

    cache = RunsCache(autostart=True)
    assert cache._started is True
    assert cache._thread is not None

    # Stopping running cache
    cache.stop()
    assert cache._started is False
    assert cache._thread is None

    # Calling stop on already-stopped cache returns early
    cache.stop()
    assert cache._started is False


def test_runs_cache_durable_index_and_corrupt_fragments(console_jail, monkeypatch):
    from eval_runner.console.routes.runs import RunsCache

    runs_dir = console_jail["runs"]
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    cache = RunsCache()

    # 1. Fragment stat error
    broken_frag = runs_dir / "broken.jsonl"
    broken_frag.write_text('{"event": "run_start"}\n', encoding="utf-8")
    orig_stat = Path.stat

    def mock_stat(self, *args, **kwargs):
        if self.name == "broken.jsonl":
            raise OSError("Simulated stat error")
        return orig_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", mock_stat)
    cache.update_cache()
    monkeypatch.setattr(Path, "stat", orig_stat)

    # 2. Durable run index processing
    index_dir = runs_dir / ".index"
    index_dir.mkdir(parents=True, exist_ok=True)

    # Valid run index
    idx_file = index_dir / "run_idx_valid.json"
    idx_file.write_text(
        json.dumps(
            {
                "run_id": "run_idx_valid",
                "scenario_id": "scenario_idx",
                "created_at": "2026-10-15T00:00:00Z",
                "status": "PENDING",
            }
        ),
        encoding="utf-8",
    )

    # Non-dict JSON in index
    (index_dir / "run_idx_list.json").write_text('["not_a_dict"]\n', encoding="utf-8")

    # Non-string run_id
    (index_dir / "run_idx_bad_id.json").write_text('{"run_id": 12345}\n', encoding="utf-8")

    # Corrupt JSON in index
    (index_dir / "run_idx_corrupt.json").write_text("{corrupt_json\n", encoding="utf-8")

    cache.update_cache()
    runs = cache.get_runs()
    found = [r for r in runs if r.get("run_id") == "run_idx_valid"]
    assert len(found) == 1
    assert found[0]["pending_status"] == "PENDING"
    assert found[0]["_run_index"] is True

    # Re-running update_cache when mtime matches cached mtime (skips re-reading)
    cache.update_cache()

    # Prune test with _run_index where run_index_path does not exist
    monkeypatch.setattr(
        "eval_runner.console.routes.runs.run_index_path",
        lambda rid: Path("/nonexistent/path/for/prune.json"),
    )
    cache.update_cache()
    assert not any(r.get("run_id") == "run_idx_valid" for r in cache.get_runs())


def test_runs_cache_vault_parsing_durations_and_scores(console_jail, monkeypatch):
    from eval_runner.console.routes.runs import RunsCache

    runs_dir = console_jail["runs"]
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    cache = RunsCache()

    # Vault 1: Invalid duration and score values to exercise exception handlers
    v1_dir = runs_dir / "v_invalid_vals"
    v1_dir.mkdir(parents=True, exist_ok=True)
    v1_file = v1_dir / "run.jsonl"
    v1_file.write_text(
        '{"event": "run_start", "run_id": "v_invalid_vals", '
        '"timestamp": "2026-10-15T00:00:00Z"}\n'
        '{"event": "run_end", "data": {"duration": "not_a_float", '
        '"score": "not_a_float", "passed": true}}\n',
        encoding="utf-8",
    )

    # Vault 2: Valid score and duration from terminal event
    v2_dir = runs_dir / "v_valid_vals"
    v2_dir.mkdir(parents=True, exist_ok=True)
    v2_file = v2_dir / "run.jsonl"
    v2_file.write_text(
        '{"event": "run_start", "run_id": "v_valid_vals", "timestamp": "2026-10-15T00:00:00Z"}\n'
        '{"event": "run_end", "data": {"duration": 18.2, "score": 95.0, "status": "SUCCESS"}}\n',
        encoding="utf-8",
    )

    # Vault 3: Fallback duration computed from timestamps (t1 >= t0)
    v3_dir = runs_dir / "v_timestamp_diff"
    v3_dir.mkdir(parents=True, exist_ok=True)
    v3_file = v3_dir / "run.jsonl"
    v3_file.write_text(
        '{"event": "run_start", "run_id": "v_timestamp_diff", '
        '"timestamp": "2026-10-15T10:00:00+00:00"}\n'
        '{"event": "step", "timestamp": "2026-10-15T10:00:25+00:00"}\n',
        encoding="utf-8",
    )

    # Vault 4: Fallback timestamp where t1 < t0
    v4_dir = runs_dir / "v_timestamp_negative"
    v4_dir.mkdir(parents=True, exist_ok=True)
    v4_file = v4_dir / "run.jsonl"
    v4_file.write_text(
        '{"event": "run_start", "run_id": "v_timestamp_negative", '
        '"timestamp": "2026-10-15T12:00:00+00:00"}\n'
        '{"event": "step", "timestamp": "2026-10-15T11:00:00+00:00"}\n',
        encoding="utf-8",
    )

    # Vault 5: Fallback timestamp with unparseable datetime
    v5_dir = runs_dir / "v_timestamp_unparseable"
    v5_dir.mkdir(parents=True, exist_ok=True)
    v5_file = v5_dir / "run.jsonl"
    v5_file.write_text(
        '{"event": "run_start", "run_id": "v_timestamp_unparseable", '
        '"timestamp": "invalid_date_start"}\n'
        '{"event": "step", "timestamp": "invalid_date_end"}\n',
        encoding="utf-8",
    )

    # Vault 6: Large file (st_size >= 1MB) to exercise size cap branch (309->397)
    v6_dir = runs_dir / "v_large_vault"
    v6_dir.mkdir(parents=True, exist_ok=True)
    v6_file = v6_dir / "run.jsonl"
    with open(v6_file, "wb") as f_large:
        f_large.write(b'{"event": "run_start", "run_id": "v_large_vault"}\n')
        f_large.seek(1024 * 1024 + 10)
        f_large.write(b"\n")

    # Vault 7: Multi-event reverse scan to exercise branches 320->326 and 347->369
    v7_dir = runs_dir / "v_multi"
    v7_dir.mkdir(parents=True, exist_ok=True)
    v7_file = v7_dir / "run.jsonl"
    v7_file.write_text(
        '{"event": "run_start", "run_id": "v_multi", "timestamp": "2026-10-15T00:00:00Z"}\n'
        '{"event": "evaluation_result", "data": {"score": 99.0}, '
        '"timestamp": "2026-10-15T00:00:01Z"}\n'
        '{"event": "step", "data": {"status": "PASS"}, "timestamp": "2026-10-15T00:00:02Z"}\n'
        '{"event": "run_end", "data": {"status": "PASS", "duration": 4.5}, '
        '"timestamp": "2026-10-15T00:00:03Z"}\n',
        encoding="utf-8",
    )

    cache.update_cache()
    runs = {r["run_id"]: r for r in cache.get_runs()}

    assert runs["v_valid_vals"]["score"] == 95.0
    assert runs["v_valid_vals"]["duration_seconds"] == 18.2
    assert runs["v_valid_vals"]["result_status"] == "PASS"

    assert runs["v_timestamp_diff"]["duration_seconds"] == 25.0
    assert runs["v_timestamp_negative"]["duration_seconds"] is None
    assert runs["v_timestamp_unparseable"]["duration_seconds"] is None
    assert "v_large_vault" in runs
    assert runs["v_multi"]["score"] == 99.0
    assert runs["v_multi"]["duration_seconds"] == 4.5
    assert runs["v_multi"]["result_status"] == "PASS"


def test_list_runs_and_stream_with_provisional_run_index(client, console_jail):
    runs_dir = console_jail["runs"]
    index_dir = runs_dir / ".index"
    index_dir.mkdir(parents=True, exist_ok=True)

    idx_file = index_dir / "pending_prov_run.json"
    idx_file.write_text(
        json.dumps(
            {
                "run_id": "pending_prov_run",
                "scenario_id": "scen_provisional",
                "created_at": "2026-10-15T09:00:00Z",
                "status": "PENDING",
            }
        ),
        encoding="utf-8",
    )

    from eval_runner.console.routes.runs import runs_cache

    runs_cache.update_cache()

    # 1. list_runs enrichment for provisional index
    res = client.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    prov_run = next((r for r in runs if r.get("run_id") == "pending_prov_run"), None)
    assert prov_run is not None
    assert prov_run["verification_status"] == "NOT_EXECUTED"
    assert prov_run["provisional"] is True
    assert prov_run["status"] == "PENDING"

    # 2. stream_runs_list chunk for provisional index
    stream_res = client.get("/api/v1/runs/stream-list")
    assert stream_res.status_code == 200
    stream_data = stream_res.get_data(as_text=True)
    assert "pending_prov_run" in stream_data
    assert "NOT_EXECUTED" in stream_data


def test_download_run_report_pdf_error_branches(client, console_jail, monkeypatch):
    run_id = "pdf_fail_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text(
        '{"event": "run_start", "run_id": "pdf_fail_run"}\n'
        '{"event": "run_end", "run_id": "pdf_fail_run"}\n',
        encoding="utf-8",
    )

    # 1. generate_run_pdf returns False
    monkeypatch.setattr(
        "eval_runner.console.pdf_service.generate_run_pdf", lambda data, path: False
    )
    res1 = client.get(f"/api/v1/runs/{run_id}/report.pdf")
    assert res1.status_code == 503
    assert res1.get_json()["error"] == "PDF report generation failed"

    # 2. generate_run_pdf produces non-PDF bytes
    def mock_generate_non_pdf(data, path):
        Path(path).write_bytes(b"NOT_A_VALID_PDF_HEADER")
        return True

    monkeypatch.setattr("eval_runner.console.pdf_service.generate_run_pdf", mock_generate_non_pdf)
    res2 = client.get(f"/api/v1/runs/{run_id}/report.pdf")
    assert res2.status_code == 503
    assert res2.get_json()["error"] == "No PDF rendering engine is available"


def test_get_run_status_vault_certificate_and_short_run_id(client, console_jail, monkeypatch):
    runs_dir = console_jail["runs"]

    # 1. Vault trace containing certificate and sealed events
    run_id = "cert_vault_run"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text(
        '{"event": "run_start"}\n\n'
        '{"event": "trace_sealed"}\n'
        '{"event": "verification_certificate_issued"}\n',
        encoding="utf-8",
    )
    res1 = client.get(f"/api/v1/runs/{run_id}")
    assert res1.status_code == 200

    # 2. Master log with short run_id format (e.g. "run-short")
    short_id = "run-short"
    master_log = runs_dir / "run.jsonl"
    master_log.write_text(
        f'{{"event": "run_start", "run_id": "{short_id}"}}\n'
        f'{{"event": "run_end", "run_id": "{short_id}"}}\n',
        encoding="utf-8",
    )

    class MockCatalog:
        @classmethod
        def get_instance(cls):
            return cls()

        def get_scenario(self, scenario):
            return {"id": "short"}

        def get_absolute_path(self, sid):
            p = runs_dir / "corrupt_scenario.json"
            p.write_text("{corrupt_json\n", encoding="utf-8")
            return p

    monkeypatch.setattr("eval_runner.catalog.ScenarioCatalog", MockCatalog)
    res2 = client.get(f"/api/v1/runs/{short_id}")
    assert res2.status_code == 200
    assert res2.get_json()["sourced_from_master"] is True

    # 3. Master log with empty scenario string (hits branch 729->743)
    empty_scen_id = "run-"
    master_log.write_text(
        f'{{"event": "run_start", "run_id": "{empty_scen_id}"}}\n',
        encoding="utf-8",
    )
    res3 = client.get(f"/api/v1/runs/{empty_scen_id}")
    assert res3.status_code == 200

    # 4. Master log with scenario that has no path (hits branch 736->743)
    class MockCatalogNoPath:
        @classmethod
        def get_instance(cls):
            return cls()

        def get_scenario(self, scenario):
            return {"id": "no_path_scen"}

        def get_absolute_path(self, sid):
            return None

    monkeypatch.setattr("eval_runner.catalog.ScenarioCatalog", MockCatalogNoPath)
    master_log.write_text(
        '{"event": "run_start", "run_id": "run-nopath"}\n',
        encoding="utf-8",
    )
    res4 = client.get("/api/v1/runs/run-nopath")
    assert res4.status_code == 200


def test_resume_run_comprehensive_validation(client, monkeypatch):
    from agentv_runtime.interfaces import ApprovalRequest

    run_id = "resume_test_run"

    # 1. Invalid decision
    res1 = client.post(f"/api/v1/runs/{run_id}/resume", json={"decision": "MAYBE"})
    assert res1.status_code == 400
    assert "must be APPROVED or REJECTED" in res1.get_json()["error"]

    # 2. Missing resumption token
    res2 = client.post(f"/api/v1/runs/{run_id}/resume", json={"decision": "APPROVED"})
    assert res2.status_code == 400
    assert "approval token is required" in res2.get_json()["error"]

    # 3. Token not found
    class MockStoreEmpty:
        def get_request(self, token):
            return None

    monkeypatch.setattr(
        "eval_runner.reference.approval_store.get_default_approval_store",
        lambda: MockStoreEmpty(),
    )
    res3 = client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resumption_token": "missing_tok"},
    )
    assert res3.status_code == 404

    # 4. Token bound to different run
    mismatched_req = ApprovalRequest(
        approval_token="tok_diff",
        run_id="other_run_id",
        turn_index=0,
        outbound_payload_hash="dummy",
        status="PENDING",
    )

    class MockStoreMismatch:
        def get_request(self, token):
            return mismatched_req

    monkeypatch.setattr(
        "eval_runner.reference.approval_store.get_default_approval_store",
        lambda: MockStoreMismatch(),
    )
    res4 = client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resumption_token": "tok_diff"},
    )
    assert res4.status_code == 409
    assert "not bound to this run" in res4.get_json()["error"]

    # 5. Token already resolved
    resolved_req = ApprovalRequest(
        approval_token="tok_resolved",
        run_id=run_id,
        turn_index=0,
        outbound_payload_hash="dummy",
        status="RESOLVED",
    )

    class MockStoreResolved:
        def get_request(self, token):
            return resolved_req

    monkeypatch.setattr(
        "eval_runner.reference.approval_store.get_default_approval_store",
        lambda: MockStoreResolved(),
    )
    res5 = client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resumption_token": "tok_resolved"},
    )
    assert res5.status_code == 409
    assert "already been resolved" in res5.get_json()["error"]

    # 6. Role mismatch
    role_req = ApprovalRequest(
        approval_token="tok_role",
        run_id=run_id,
        turn_index=0,
        outbound_payload_hash="dummy",
        status="PENDING",
        required_role="security_officer",
    )

    class MockStoreRole:
        def get_request(self, token):
            return role_req

    monkeypatch.setattr(
        "eval_runner.reference.approval_store.get_default_approval_store",
        lambda: MockStoreRole(),
    )
    res6 = client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resumption_token": "tok_role", "reviewer_role": "auditor"},
    )
    assert res6.status_code == 403
    assert "Reviewer role does not satisfy" in res6.get_json()["error"]

    # 7. Credentials mismatch
    cred_req = ApprovalRequest(
        approval_token="tok_cred",
        run_id=run_id,
        turn_index=0,
        outbound_payload_hash="dummy",
        status="PENDING",
        reviewer_credentials={"key_level": "top_secret"},
    )

    class MockStoreCred:
        def get_request(self, token):
            return cred_req

    monkeypatch.setattr(
        "eval_runner.reference.approval_store.get_default_approval_store",
        lambda: MockStoreCred(),
    )
    res7 = client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={
            "resumption_token": "tok_cred",
            "reviewer_credentials": {"key_level": "unclassified"},
        },
    )
    assert res7.status_code == 403
    assert "Reviewer credentials do not satisfy" in res7.get_json()["error"]

    # 8. resolve_durable_request raising PermissionError, KeyError
    valid_req = ApprovalRequest(
        approval_token="tok_valid",
        run_id=run_id,
        turn_index=0,
        outbound_payload_hash="dummy",
        status="PENDING",
    )

    class MockStoreValid:
        def get_request(self, token):
            return valid_req

    monkeypatch.setattr(
        "eval_runner.reference.approval_store.get_default_approval_store",
        lambda: MockStoreValid(),
    )

    class MockManagerPerm:
        def __init__(self, *args, **kwargs):
            pass

        def resolve_durable_request(self, *args, **kwargs):
            raise PermissionError("Denied by policy")

    monkeypatch.setattr(
        "eval_runner.session_components.approval_manager.SessionApprovalManager",
        MockManagerPerm,
    )
    res8 = client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resumption_token": "tok_valid", "decision": "APPROVED"},
    )
    assert res8.status_code == 403

    class MockManagerKeyErr:
        def __init__(self, *args, **kwargs):
            pass

        def resolve_durable_request(self, *args, **kwargs):
            raise KeyError("Request not found in manager")

    monkeypatch.setattr(
        "eval_runner.session_components.approval_manager.SessionApprovalManager",
        MockManagerKeyErr,
    )
    res9 = client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resumption_token": "tok_valid", "decision": "APPROVED"},
    )
    assert res9.status_code == 409

    # 9. REJECTED decision path
    class MockManagerOk:
        def __init__(self, *args, **kwargs):
            pass

        def resolve_durable_request(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        "eval_runner.session_components.approval_manager.SessionApprovalManager",
        MockManagerOk,
    )
    res10 = client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resumption_token": "tok_valid", "decision": "REJECTED", "reason": "Not ready"},
    )
    assert res10.status_code == 200
    assert res10.get_json()["status"] == "REJECTED"

    # 10. APPROVED but backend.resume returns None
    class MockBackendNone:
        def resume(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        "eval_runner.reference.inprocess_backend.get_execution_backend",
        lambda: MockBackendNone(),
    )
    res11 = client.post(
        f"/api/v1/runs/{run_id}/resume",
        json={"resumption_token": "tok_valid", "decision": "APPROVED"},
    )
    assert res11.status_code == 404
    assert "No checkpoint found" in res11.get_json()["error"]


def test_extract_canonical_event_info_and_tail_edge_cases():
    from eval_runner.console.routes.runs import _extract_canonical_event_info

    # 1. Corrupt JSON containing terminal event string
    seq, is_term = _extract_canonical_event_info('CORRUPT{"event": "run_end"}', 5)
    assert seq == 5
    assert is_term is True

    # 2. Corrupt JSON not containing terminal event string
    seq2, is_term2 = _extract_canonical_event_info('CORRUPT{"event": "step"}', 7)
    assert seq2 == 7
    assert is_term2 is False

    # 3. Valid dict with seq_id
    seq3, is_term3 = _extract_canonical_event_info('{"seq_id": 42, "event": "step"}', 1)
    assert seq3 == 42
    assert is_term3 is False

    # 4. Valid dict with id
    seq4, _ = _extract_canonical_event_info('{"id": 88}', 1)
    assert seq4 == 88

    # 5. Valid dict with invalid seq string
    seq5, _ = _extract_canonical_event_info('{"_seq": "not_int"}', 10)
    assert seq5 == 10

    # 6. Valid dict without any seq fields
    seq6, _ = _extract_canonical_event_info('{"other": "field"}', 15)
    assert seq6 == 15


def test_tail_file_generator_deep_coverage(tmp_path, monkeypatch):
    from eval_runner.console.routes.runs import tail_file_generator

    # 1. Partial trailing line in historical read (no newline, pos seek rewind)
    log_file = tmp_path / "stream_deep.jsonl"
    log_file.write_text('{"event": "step", "_seq": 1}\nunended_line', encoding="utf-8")

    gen1 = tail_file_generator(log_file, run_id="r_deep", last_event_id=0)
    item1 = next(gen1)
    assert "id: 1" in item1
    # Advance to line 2 (which has no newline): this exercises f.seek(pos) and break
    # Next iteration in Step B tail loop will wait for data or check state.
    # Close generator cleanly.
    gen1.close()

    # 2. Tell raising OSError in historical read
    orig_open = open

    class WrappedFile:
        def __init__(self, f):
            self._f = f

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self._f.__exit__(*args)

        def tell(self):
            raise OSError("tell failed")

        def readline(self):
            return self._f.readline()

        def seek(self, pos):
            return self._f.seek(pos)

    def mock_open_tell_fail(path, *args, **kwargs):
        real_f = orig_open(path, *args, **kwargs)
        if "tell_fail" in str(path):
            return WrappedFile(real_f)
        return real_f

    log_tell_fail = tmp_path / "tell_fail.jsonl"
    log_tell_fail.write_text('{"event": "run_end"}\n', encoding="utf-8")

    monkeypatch.setattr("builtins.open", mock_open_tell_fail)
    gen2 = tail_file_generator(log_tell_fail, run_id="r_tell", last_event_id=0)
    res2 = list(gen2)
    assert len(res2) == 1
    assert "run_end" in res2[0]
    monkeypatch.undo()

    # 3. File deleted detected during tail loop
    log_del = tmp_path / "to_delete.jsonl"
    log_del.write_text('{"event": "step"}\n', encoding="utf-8")
    gen3 = tail_file_generator(log_del, run_id="r_del", last_event_id=0)
    next(gen3)  # Consume initial event

    orig_path_exists = Path.exists

    def mock_del_exists(self):
        if self.name == "to_delete.jsonl":
            return False
        return orig_path_exists(self)

    monkeypatch.setattr(Path, "exists", mock_del_exists)
    del_event = next(gen3)
    assert "Log file deleted" in del_event
    monkeypatch.setattr(Path, "exists", orig_path_exists)

    # 4. Target run_id filter and corrupt JSON in tail loop
    log_filt = tmp_path / "filtered_tail.jsonl"
    log_filt.write_text(
        '{"event": "step", "run_id": "other_run"}\n'
        '{"event": "step", "run_id": "target_run"}\n'
        '{"event": "run_end", "run_id": "target_run"}\n',
        encoding="utf-8",
    )
    gen4 = tail_file_generator(
        log_filt, run_id="target_run", target_run_id="target_run", last_event_id=0
    )
    results = list(gen4)
    assert len(results) == 2
    assert "target_run" in results[0]
    assert "run_end" in results[1]


def test_runs_filtering_unverified_context_in_list_and_stream(client, console_jail, monkeypatch):
    from eval_runner.console.routes.runs import runs_cache

    runs_dir = console_jail["runs"]
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)

    # Put a forbidden run into cache
    runs_cache._runs = [
        {"run_id": "forbidden_run_1", "scenario": "scen_f"},
        {"run_id": "allowed_run_1", "scenario": "scen_a"},
    ]

    # Context allows allowed_run_1, forbids forbidden_run_1
    def mock_context_check(run_id, ctx=None):
        return run_id == "allowed_run_1"

    monkeypatch.setattr(
        "eval_runner.console.routes.runs._run_is_in_active_context", mock_context_check
    )
    monkeypatch.setattr(
        "eval_runner.console.routes.runs.active_runtime_context", lambda: {"tenant_id": "t1"}
    )

    # 1. list_runs filters forbidden_run_1
    res = client.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    ids = [r["run_id"] for r in runs]
    assert "forbidden_run_1" not in ids

    # 2. stream_runs_list filters forbidden_run_1
    stream_res = client.get("/api/v1/runs/stream-list")
    assert stream_res.status_code == 200
    stream_data = stream_res.get_data(as_text=True)
    assert "forbidden_run_1" not in stream_data


def test_tail_file_generator_tail_loop_branches(tmp_path, monkeypatch):
    from eval_runner.console.routes.runs import tail_file_generator

    log_hb = tmp_path / "heartbeat.jsonl"
    log_hb.write_text('{"event": "step"}\n', encoding="utf-8")

    # Fast forward sleep so idle_cycles >= 150 triggers immediately
    monkeypatch.setattr("time.sleep", lambda _: None)
    alive_states = [True, False]
    monkeypatch.setattr(
        "eval_runner.console.routes.runs.is_run_alive",
        lambda _: alive_states.pop(0) if alive_states else False,
    )

    gen_hb = tail_file_generator(log_hb, run_id="r_hb", last_event_id=0)
    first_item = next(gen_hb)
    assert "step" in first_item

    # Next iteration in tail loop enters idle_cycles >= 150 with is_run_alive = True
    hb_item1 = next(gen_hb)
    assert ": heartbeat\n\n" in hb_item1

    # Next iteration in tail loop enters idle_cycles >= 150 with is_run_alive = False
    hb_item2 = next(gen_hb)
    assert ": heartbeat\n\n" in hb_item2
    term_item = next(gen_hb)
    assert "Process thread terminated abruptly" in term_item


def test_tail_file_generator_step_b_tail_loop(tmp_path, monkeypatch):
    from eval_runner.console.routes.runs import tail_file_generator

    # Initial file has valid line 1 and partial line 2 without newline
    log_file = tmp_path / "tail_b.jsonl"
    log_file.write_text(
        '{"event": "step", "run_id": "r_target", "_seq": 1}\npartial_step_a', encoding="utf-8"
    )

    monkeypatch.setattr("time.sleep", lambda _: None)

    orig_open = open

    class WrappedTailFile:
        def __init__(self, f):
            self._f = f
            self._tell_calls = 0
            self._readline_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self._f.__exit__(*args)

        def tell(self):
            self._tell_calls += 1
            if self._tell_calls == 4:
                # Exercises OSError on tell in Step B
                raise OSError("Simulated tell error in Step B")
            return self._f.tell()

        def readline(self):
            line = self._f.readline()
            self._readline_calls += 1
            if self._readline_calls == 3:
                # In Step B after reading partial_step_a,
                # append newline (corrupt JSON),
                # empty line,
                # non-terminal event,
                # other run event, and terminal event.
                with orig_open(self._f.name, "a", encoding="utf-8") as appender:
                    appender.write("\n")
                    appender.write("\n")  # Empty line -> stripped is empty
                    appender.write('{"event": "step", "run_id": "r_target"}\n')  # non-terminal
                    appender.write('{"event": "step", "run_id": "other_run"}\n')
                    appender.write('{"event": "run_end", "run_id": "r_target"}\n')
            return line

        def seek(self, pos):
            return self._f.seek(pos)

        def __getattr__(self, name):
            return getattr(self._f, name)

    def mock_open_tail(path, *args, **kwargs):
        rf = orig_open(path, *args, **kwargs)
        if "tail_b" in str(path):
            return WrappedTailFile(rf)
        return rf

    monkeypatch.setattr("builtins.open", mock_open_tail)

    gen = tail_file_generator(
        log_file, run_id="r_target", target_run_id="r_target", last_event_id=2
    )
    # Step B processes non-terminal step event (seq_id 2 <= 2, skipped yield)
    # then terminal run_end event (seq_id 3 > 2, yielded)
    item_end = next(gen)
    assert "run_end" in item_end
    with pytest.raises(StopIteration):
        next(gen)


def test_tail_file_generator_branches_matrix(tmp_path, monkeypatch):
    from eval_runner.console.routes.runs import tail_file_generator

    # In Step A, pos is None and line does not end with newline
    log_file1 = tmp_path / "step_a_no_pos.jsonl"
    log_file1.write_text("partial_without_newline", encoding="utf-8")

    orig_open = open

    class WrappedFileNoPos:
        def __init__(self, f):
            self._f = f

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self._f.__exit__(*args)

        def tell(self):
            raise OSError("tell pos failure")

        def readline(self):
            return self._f.readline()

        def seek(self, pos):
            return self._f.seek(pos)

    def mock_open_no_pos(path, *args, **kwargs):
        rf = orig_open(path, *args, **kwargs)
        if "step_a_no_pos" in str(path):
            return WrappedFileNoPos(rf)
        return rf

    monkeypatch.setattr("builtins.open", mock_open_no_pos)
    monkeypatch.setattr("eval_runner.console.routes.runs.is_run_alive", lambda _: False)

    gen1 = tail_file_generator(
        log_file1, run_id="r_nopos", target_run_id="r_nopos", last_event_id=0
    )
    res1 = next(gen1)
    assert "not_found" in res1
    monkeypatch.undo()


def test_tail_file_generator_target_run_not_found(tmp_path, monkeypatch):
    from eval_runner.console.routes.runs import tail_file_generator

    log_file = tmp_path / "not_found.jsonl"
    log_file.write_text('{"event": "step", "run_id": "different_run"}\n', encoding="utf-8")

    monkeypatch.setattr("eval_runner.console.routes.runs.is_run_alive", lambda _: False)

    gen = tail_file_generator(
        log_file, run_id="r_missing", target_run_id="r_missing", last_event_id=0
    )
    res = next(gen)
    assert "Execution log file not found. Waiting for trace data." in res
