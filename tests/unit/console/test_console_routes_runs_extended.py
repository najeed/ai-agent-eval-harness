import os
import tempfile
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
