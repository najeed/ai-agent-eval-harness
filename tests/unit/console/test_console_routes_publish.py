"""
tests/unit/console/test_console_routes_publish.py

Unit tests for eval_runner.console.routes.publish.
Covers: background job worker, POST /publish, GET /publish/<id>,
        GET /publish/<id>/bundle, POST /ci/generate,
        GET /registry, POST /registry.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.publish import JOBS, _run_publication_job, publish_bp


@pytest.fixture(autouse=True)
def clear_jobs():
    """Reset the global JOBS dict between tests."""
    JOBS.clear()
    yield
    JOBS.clear()


@pytest.fixture
def publish_jail(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    results = tmp_path / "results"
    results.mkdir()
    reports = tmp_path / "reports"
    reports.mkdir()
    return {"root": tmp_path, "runs": runs, "results": results, "reports": reports}


@pytest.fixture
def publish_client(publish_jail, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(publish_bp, url_prefix="/api")

    monkeypatch.setattr(config, "PROJECT_ROOT", publish_jail["root"])
    monkeypatch.setattr(config, "RUN_LOG_DIR", publish_jail["runs"])
    monkeypatch.setattr(config, "REPORTS_DIR", publish_jail["reports"])

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


# ---------------------------------------------------------------------------
# _run_publication_job (background worker)
# ---------------------------------------------------------------------------


def test_run_publication_job_success(publish_jail):
    job_id = "job_test_success"
    JOBS[job_id] = {"status": "queued", "progress": "", "results": None, "error": None}

    batch_dir = publish_jail["results"] / "batch_20260701"
    batch_dir.mkdir(parents=True, exist_ok=True)
    manifest = batch_dir / "manifest.json"
    manifest.write_text(json.dumps({"runs": 3}), encoding="utf-8")
    zip_file = batch_dir / "publication_artifact_bundle.zip"
    zip_file.write_bytes(b"PK")

    mock_proc = MagicMock()
    mock_proc.stdout = iter(["Phase 1\n", "Phase 2\n", "Other line\n", "Phase 3\n", "Phase 4\n"])
    mock_proc.returncode = 0
    mock_proc.wait.return_value = None

    log_path = publish_jail["results"] / "test_job.log"

    with patch("subprocess.Popen", return_value=mock_proc):
        with patch.object(config, "PROJECT_ROOT", publish_jail["root"]):
            _run_publication_job(job_id, ["dummy"], log_path)

    assert JOBS[job_id]["status"] == "completed"
    assert JOBS[job_id]["results"]["batch_id"] == "batch_20260701"


def test_run_publication_job_no_batch_dir(publish_jail):
    job_id = "job_no_batch"
    JOBS[job_id] = {"status": "queued", "progress": "", "results": None, "error": None}

    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = 0
    mock_proc.wait.return_value = None

    log_path = publish_jail["results"] / "no_batch.log"

    with patch("subprocess.Popen", return_value=mock_proc):
        with patch.object(config, "PROJECT_ROOT", publish_jail["root"]):
            _run_publication_job(job_id, ["dummy"], log_path)

    assert JOBS[job_id]["status"] == "failed"
    assert "batch folder" in JOBS[job_id]["error"]


def test_run_publication_job_nonzero_exit(publish_jail):
    job_id = "job_fail_exit"
    JOBS[job_id] = {"status": "queued", "progress": "", "results": None, "error": None}

    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = 1
    mock_proc.wait.return_value = None

    log_path = publish_jail["results"] / "fail_exit.log"

    with patch("subprocess.Popen", return_value=mock_proc):
        _run_publication_job(job_id, ["dummy"], log_path)

    assert JOBS[job_id]["status"] == "failed"
    assert "exit code: 1" in JOBS[job_id]["error"]


def test_run_publication_job_exception(publish_jail):
    job_id = "job_exception"
    JOBS[job_id] = {"status": "queued", "progress": "", "results": None, "error": None}

    log_path = publish_jail["results"] / "exception.log"

    with patch("subprocess.Popen", side_effect=OSError("no binary")):
        _run_publication_job(job_id, ["dummy"], log_path)

    assert JOBS[job_id]["status"] == "failed"
    assert "no binary" in JOBS[job_id]["error"]


def test_run_publication_job_pilot_mode(publish_jail):
    """Verify pilot_ leaderboard path is used when 'pilot' appears in cmd."""
    job_id = "job_pilot"
    JOBS[job_id] = {"status": "queued", "progress": "", "results": None, "error": None}

    batch_dir = publish_jail["results"] / "batch_pilot"
    batch_dir.mkdir(parents=True, exist_ok=True)
    pilot_html = batch_dir / "pilot_preview.html"
    pilot_html.write_text("<html/>", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = 0
    mock_proc.wait.return_value = None

    log_path = publish_jail["results"] / "pilot.log"

    with patch("subprocess.Popen", return_value=mock_proc):
        with patch.object(config, "PROJECT_ROOT", publish_jail["root"]):
            _run_publication_job(job_id, ["pilot", "run"], log_path)

    assert JOBS[job_id]["status"] == "completed"
    assert "pilot_preview.html" in (JOBS[job_id]["results"]["leaderboard_html"] or "")


def test_run_publication_job_manifest_read_error(publish_jail):
    """Manifest read failure logs warning but still marks completed."""
    job_id = "job_manifest_err"
    JOBS[job_id] = {"status": "queued", "progress": "", "results": None, "error": None}

    batch_dir = publish_jail["results"] / "batch_mfail"
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "manifest.json").write_text("{{invalid", encoding="utf-8")

    mock_proc = MagicMock()
    mock_proc.stdout = iter([])
    mock_proc.returncode = 0
    mock_proc.wait.return_value = None

    log_path = publish_jail["results"] / "mfail.log"

    with patch("subprocess.Popen", return_value=mock_proc):
        with patch.object(config, "PROJECT_ROOT", publish_jail["root"]):
            _run_publication_job(job_id, ["dummy"], log_path)

    assert JOBS[job_id]["status"] == "completed"


# ---------------------------------------------------------------------------
# POST /publish
# ---------------------------------------------------------------------------


def test_publish_start_default(publish_client):
    with patch("threading.Thread") as mock_thread:
        mock_thread.return_value = MagicMock()
        res = publish_client.post("/api/publish", json={})

    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "queued"
    assert data["job_id"].startswith("pub_job_")


def test_publish_start_custom_params(publish_client):
    with patch("threading.Thread") as mock_thread:
        mock_thread.return_value = MagicMock()
        res = publish_client.post(
            "/api/publish",
            json={
                "mode": "pilot",
                "path": "scenarios/finance",
                "agent_name": "GPT-4-Turbo",
                "protocol": "grpc",
                "agent": "http://localhost:9001",
                "parallel": 8,
            },
        )

    assert res.status_code == 200
    job_id = res.get_json()["job_id"]
    assert JOBS[job_id]["params"]["mode"] == "pilot"
    assert JOBS[job_id]["params"]["parallel"] == 8


# ---------------------------------------------------------------------------
# GET /publish/<job_id>
# ---------------------------------------------------------------------------


def test_publish_get_job_not_found(publish_client):
    res = publish_client.get("/api/publish/nonexistent-job")
    assert res.status_code == 404


def test_publish_get_job_status(publish_client):
    JOBS["job-status-1"] = {
        "job_id": "job-status-1",
        "status": "running",
        "progress": "Phase 2",
        "params": {},
        "results": None,
        "error": None,
    }
    res = publish_client.get("/api/publish/job-status-1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "running"
    assert data["logs"] == ""  # no log file on disk


def test_publish_get_job_reads_log_file(publish_client, publish_jail):
    JOBS["job-with-log"] = {
        "job_id": "job-with-log",
        "status": "completed",
        "progress": "done",
        "params": {},
        "results": None,
        "error": None,
    }
    log_dir = publish_jail["root"] / "results" / "jobs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "job-with-log.log").write_text("Phase 1 output\n", encoding="utf-8")

    res = publish_client.get("/api/publish/job-with-log")
    assert res.status_code == 200
    assert "Phase 1 output" in res.get_json()["logs"]


def test_publish_get_job_log_read_error(publish_client, publish_jail):
    JOBS["job-log-err"] = {
        "job_id": "job-log-err",
        "status": "completed",
        "progress": "done",
        "params": {},
        "results": None,
        "error": None,
    }
    log_dir = publish_jail["root"] / "results" / "jobs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "job-log-err.log"
    log_file.write_text("content", encoding="utf-8")

    # Mock open when reading this specific file to raise an Exception
    orig_open = open

    def mock_open(file, *args, **kwargs):
        if str(file).endswith("job-log-err.log"):
            raise OSError("Mock read error")
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open):
        res = publish_client.get("/api/publish/job-log-err")

    assert res.status_code == 200
    assert res.get_json()["logs"] == ""  # Defaults to empty string on read failure


# ---------------------------------------------------------------------------
# GET /publish/<job_id>/bundle
# ---------------------------------------------------------------------------


def test_publish_bundle_not_found(publish_client):
    res = publish_client.get("/api/publish/no-job/bundle")
    assert res.status_code == 404


def test_publish_bundle_job_not_completed(publish_client):
    JOBS["job-running"] = {"status": "running", "results": None, "error": None}
    res = publish_client.get("/api/publish/job-running/bundle")
    assert res.status_code == 400


def test_publish_bundle_zip_missing(publish_client, publish_jail):
    JOBS["job-nozip"] = {
        "status": "completed",
        "results": {"zip_file": "results/missing.zip", "batch_id": "b1"},
        "error": None,
    }
    res = publish_client.get("/api/publish/job-nozip/bundle")
    assert res.status_code == 404


def test_publish_bundle_download_success(publish_client, publish_jail):
    zip_path = publish_jail["root"] / "results" / "bundle.zip"
    zip_path.write_bytes(b"PK")
    JOBS["job-zip-ok"] = {
        "status": "completed",
        "results": {"zip_file": "results/bundle.zip", "batch_id": "batch-q"},
        "error": None,
    }
    with patch("eval_runner.console.routes.publish.send_file") as mock_sf:
        mock_sf.return_value = ("data", 200, {"Content-Type": "application/zip"})
        res = publish_client.get("/api/publish/job-zip-ok/bundle")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# POST /ci/generate
# ---------------------------------------------------------------------------


def test_publish_ci_generate_success(publish_client, publish_jail):
    workflow_path = publish_jail["root"] / ".github" / "workflows" / "eval_harness_ci.yml"
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text("name: CI\n", encoding="utf-8")

    with patch("eval_runner.console.routes.publish.scaffold.generate_github_action"):
        with patch("eval_runner.console.routes.publish.config.PROJECT_ROOT", publish_jail["root"]):
            res = publish_client.post("/api/ci/generate")

    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "CI" in data["yaml"]


def test_publish_ci_generate_file_missing(publish_client, publish_jail):
    with patch("eval_runner.console.routes.publish.scaffold.generate_github_action"):
        with patch("eval_runner.console.routes.publish.config.PROJECT_ROOT", publish_jail["root"]):
            res = publish_client.post("/api/ci/generate")

    assert res.status_code == 500
    assert "failed" in res.get_json()["error"].lower()


def test_publish_ci_generate_exception(publish_client):
    with patch(
        "eval_runner.console.routes.publish.scaffold.generate_github_action",
        side_effect=RuntimeError("scaffold exploded"),
    ):
        res = publish_client.post("/api/ci/generate")

    assert res.status_code == 500
    assert "scaffold exploded" in res.get_json()["error"]


# ---------------------------------------------------------------------------
# GET /registry
# ---------------------------------------------------------------------------


def test_publish_get_registry_success(publish_client):
    mock_registry = {"categories": {"AI": {"standards": []}}}
    with patch("eval_runner.console.routes.publish.load_registry", return_value=mock_registry):
        res = publish_client.get("/api/registry")

    assert res.status_code == 200
    assert "categories" in res.get_json()


def test_publish_get_registry_exception(publish_client):
    with patch(
        "eval_runner.console.routes.publish.load_registry", side_effect=RuntimeError("io fail")
    ):
        res = publish_client.get("/api/registry")

    assert res.status_code == 500


# ---------------------------------------------------------------------------
# POST /registry
# ---------------------------------------------------------------------------


def test_publish_add_standard_missing_fields(publish_client):
    res = publish_client.post("/api/registry", json={"id": "STD-1", "name": "Test"})
    assert res.status_code == 400


def test_publish_add_standard_success(publish_client):
    with patch("eval_runner.console.routes.publish.add_standard_to_registry", return_value=True):
        res = publish_client.post(
            "/api/registry",
            json={
                "id": "STD-AI-01",
                "name": "AI Safety Baseline",
                "industry": "AI",
                "description": "Mandatory eval coverage",
                "category": "Safety",
            },
        )
    assert res.status_code == 200
    assert "success" in res.get_json()["status"]


def test_publish_add_standard_already_exists(publish_client):
    with patch("eval_runner.console.routes.publish.add_standard_to_registry", return_value=False):
        res = publish_client.post(
            "/api/registry",
            json={
                "id": "STD-AI-01",
                "name": "AI Safety Baseline",
                "industry": "AI",
                "description": "Duplicate",
            },
        )
    assert res.status_code == 400
    assert "already exists" in res.get_json()["error"]


def test_publish_add_standard_exception(publish_client):
    with patch(
        "eval_runner.console.routes.publish.add_standard_to_registry",
        side_effect=RuntimeError("registry corrupt"),
    ):
        res = publish_client.post(
            "/api/registry",
            json={
                "id": "STD-X",
                "name": "X",
                "industry": "fin",
                "description": "x",
            },
        )
    assert res.status_code == 500


def test_publish_stop_job_branches(publish_client):
    """Verify POST /publish/<job_id>/stop handles not found, finished, and active jobs."""
    # 1. Not found
    res = publish_client.post("/api/publish/nonexistent_job/stop")
    assert res.status_code == 404

    # 2. Already finished
    JOBS["job_finished"] = {"status": "completed", "job_id": "job_finished"}
    res = publish_client.post("/api/publish/job_finished/stop")
    assert res.status_code == 200
    assert "already finished" in res.get_json()["message"]

    # 3. Active running job with process termination
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    mock_proc.kill = MagicMock()
    JOBS["job_active"] = {"status": "running", "job_id": "job_active", "_proc": mock_proc}

    mock_child = MagicMock()
    mock_child.kill = MagicMock()
    mock_parent = MagicMock()
    mock_parent.children.return_value = [mock_child]
    mock_parent.kill = MagicMock()

    with patch("psutil.Process", return_value=mock_parent):
        with patch("psutil.wait_procs"):
            res = publish_client.post("/api/publish/job_active/stop")
            assert res.status_code == 200
            assert res.get_json()["status"] == "stopped"
            assert JOBS["job_active"]["status"] == "failed"


def test_durable_job_store_branches(tmp_path, monkeypatch):
    """Verify DurableJobStore error handling on save, load, and list_active."""
    from eval_runner.console.routes.publish import DurableJobStore

    jobs_dir = tmp_path / "durable_jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(DurableJobStore, "_jobs_dir", lambda: jobs_dir)

    # 1. Save and load success
    DurableJobStore.save("job_durable_1", {"job_id": "job_durable_1", "status": "running"})
    loaded = DurableJobStore.load("job_durable_1")
    assert loaded["job_id"] == "job_durable_1"

    # 2. Load non-existent
    assert DurableJobStore.load("non_existent_durable") is None

    # 3. List active with corrupt JSON file
    (jobs_dir / "corrupt.json").write_text("INVALID_JSON", encoding="utf-8")
    active = DurableJobStore.list_active()
    assert "job_durable_1" in active


def test_run_publication_job_progress_line_parsing(publish_jail):
    """Verify _run_publication_job parses [1/3] Running run and phase lines."""
    job_id = "job_parsing_test"
    JOBS[job_id] = {"status": "queued", "progress": "", "results": None, "error": None}

    mock_proc = MagicMock()
    mock_proc.stdout = iter(
        [
            "[1/3] Running run scen_01\n",
            "[2/3] Completed run scen_01\n",
            "[3/3] runs complete\n",
        ]
    )
    mock_proc.returncode = 1
    mock_proc.wait.return_value = None

    log_path = publish_jail["results"] / "parsing_test.log"

    with patch("subprocess.Popen", return_value=mock_proc):
        _run_publication_job(job_id, ["dummy"], log_path)

    assert JOBS[job_id]["status"] == "failed"


def test_get_job_logs_root_path_normalization(publish_client, publish_jail):
    """Verify GET /publish/<job_id> normalizes project root paths in logs."""
    job_id = "job_log_norm"
    jobs_dir = publish_jail["results"] / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    log_file = jobs_dir / f"{job_id}.log"
    root_str = str(config.PROJECT_ROOT)
    log_file.write_text(f"Executed at {root_str}/scenarios/test.json\n", encoding="utf-8")

    JOBS[job_id] = {
        "job_id": job_id,
        "status": "completed",
    }

    res = publish_client.get(f"/api/publish/{job_id}")
    assert res.status_code == 200
    data = res.get_json()
    assert "./scenarios/test.json" in data["logs"]
