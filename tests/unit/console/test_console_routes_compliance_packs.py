"""
tests/unit/console/test_console_routes_compliance_packs.py

Unit tests for eval_runner.console.routes.compliance_packs.
Covers: _load_standards, list_packs, get_pack, save_pack, publish_pack, test_pack.
"""

import json
from unittest.mock import patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.compliance_packs import compliance_packs_bp


@pytest.fixture
def packs_jail(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    runs = root / "runs"
    runs.mkdir()
    reports = root / "reports"
    reports.mkdir()
    (reports / "certificates").mkdir()
    packs_dir = root / "results" / "compliance_packs"
    packs_dir.mkdir(parents=True)

    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs)
    monkeypatch.setattr(config, "REPORTS_DIR", reports)

    # Patch module-level PACKS_DIR to use tmp dir
    monkeypatch.setattr("eval_runner.console.routes.compliance_packs.PACKS_DIR", packs_dir)

    return {"root": root, "runs": runs, "reports": reports, "packs_dir": packs_dir}


@pytest.fixture
def packs_client(packs_jail):
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(compliance_packs_bp, url_prefix="/api")

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


# ---------------------------------------------------------------------------
# _load_standards
# ---------------------------------------------------------------------------


def test_compliance_packs_load_standards_missing_file(packs_jail):
    from eval_runner.console.routes.compliance_packs import _load_standards

    result = _load_standards()
    assert result == []


def test_compliance_packs_load_standards_success(packs_jail):
    spec_dir = packs_jail["root"] / "spec" / "aes"
    spec_dir.mkdir(parents=True)
    standards_file = spec_dir / "standards.json"
    standards_file.write_text(
        json.dumps(
            {
                "categories": {
                    "Finance": {
                        "standards": [
                            {
                                "id": "FFIEC-01",
                                "name": "FFIEC AI",
                                "description": "Banking AI standards",
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with patch(
        "eval_runner.console.routes.compliance_packs.config.PROJECT_ROOT", packs_jail["root"]
    ):
        from eval_runner.console.routes.compliance_packs import _load_standards

        result = _load_standards()

    assert len(result) == 1
    assert result[0]["id"] == "FFIEC-01"
    assert result[0]["category"] == "Finance"


# ---------------------------------------------------------------------------
# GET /v1/compliance-packs (list)
# ---------------------------------------------------------------------------


def test_compliance_packs_list_empty_standards(packs_client):
    with patch("eval_runner.console.routes.compliance_packs._load_standards", return_value=[]):
        res = packs_client.get("/api/v1/compliance-packs")
    assert res.status_code == 200
    assert res.get_json()["packs"] == []


def test_compliance_packs_list_with_configured_and_unconfigured(packs_client, packs_jail):
    standards = [
        {"id": "STD-A", "name": "Standard A", "description": "Desc A", "category": "AI"},
        {"id": "STD-B", "name": "Standard B", "description": "Desc B", "category": "Fin"},
    ]
    # Write a pack config for STD-A
    pack_a = packs_jail["packs_dir"] / "STD-A.json"
    pack_a.write_text(
        json.dumps({"id": "STD-A", "checks": [{"type": "pqc_required"}], "version": 2}),
        encoding="utf-8",
    )

    with patch(
        "eval_runner.console.routes.compliance_packs._load_standards", return_value=standards
    ):
        res = packs_client.get("/api/v1/compliance-packs")

    assert res.status_code == 200
    packs = {p["id"]: p for p in res.get_json()["packs"]}
    assert packs["STD-A"]["configured"] is True
    assert packs["STD-A"]["version"] == 2
    assert len(packs["STD-A"]["checks"]) == 1
    assert packs["STD-B"]["configured"] is False


def test_compliance_packs_list_corrupt_pack_file(packs_client, packs_jail):
    standards = [{"id": "STD-C", "name": "Std C", "description": "D", "category": "X"}]
    (packs_jail["packs_dir"] / "STD-C.json").write_text("{{invalid", encoding="utf-8")

    with patch(
        "eval_runner.console.routes.compliance_packs._load_standards", return_value=standards
    ):
        res = packs_client.get("/api/v1/compliance-packs")

    assert res.status_code == 200
    packs = res.get_json()["packs"]
    assert packs[0]["configured"] is False  # corrupt file → treat as unconfigured


# ---------------------------------------------------------------------------
# GET /v1/compliance-packs/<id>
# ---------------------------------------------------------------------------


def test_compliance_packs_get_not_configured(packs_client):
    res = packs_client.get("/api/v1/compliance-packs/STD-MISSING")
    assert res.status_code == 200
    data = res.get_json()
    assert data["configured"] is False
    assert data["checks"] == []


def test_compliance_packs_get_success(packs_client, packs_jail):
    pack = {"id": "STD-D", "checks": [{"type": "wsm_threshold"}], "version": 3}
    (packs_jail["packs_dir"] / "STD-D.json").write_text(json.dumps(pack), encoding="utf-8")

    res = packs_client.get("/api/v1/compliance-packs/STD-D")
    assert res.status_code == 200
    data = res.get_json()
    assert data["configured"] is True
    assert data["version"] == 3


def test_compliance_packs_get_corrupt(packs_client, packs_jail):
    (packs_jail["packs_dir"] / "STD-E.json").write_text("{{bad", encoding="utf-8")
    res = packs_client.get("/api/v1/compliance-packs/STD-E")
    assert res.status_code == 500


# ---------------------------------------------------------------------------
# POST /v1/compliance-packs (save)
# ---------------------------------------------------------------------------


def test_compliance_packs_save_missing_fields(packs_client):
    res = packs_client.post("/api/v1/compliance-packs", json={"id": "STD-F"})
    assert res.status_code == 400
    assert "Missing required" in res.get_json()["error"]


def test_compliance_packs_save_new(packs_client, packs_jail):
    res = packs_client.post(
        "/api/v1/compliance-packs",
        json={"id": "STD-G", "name": "Standard G", "checks": [{"type": "pqc_required"}]},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["id"] == "STD-G"
    assert data["version"] == 1
    assert (packs_jail["packs_dir"] / "STD-G.json").exists()


def test_compliance_packs_save_version_bump(packs_client, packs_jail):
    existing = {"id": "STD-H", "name": "Std H", "version": 4, "checks": []}
    (packs_jail["packs_dir"] / "STD-H.json").write_text(json.dumps(existing), encoding="utf-8")

    res = packs_client.post(
        "/api/v1/compliance-packs",
        json={"id": "STD-H", "name": "Standard H updated"},
    )
    assert res.status_code == 200
    assert res.get_json()["version"] == 5


def test_compliance_packs_save_version_bump_corrupt(packs_client, packs_jail):
    """Corrupt existing pack → version defaults to 1 without crashing."""
    (packs_jail["packs_dir"] / "STD-I.json").write_text("{{bad", encoding="utf-8")
    res = packs_client.post("/api/v1/compliance-packs", json={"id": "STD-I", "name": "Std I"})
    assert res.status_code == 200
    assert res.get_json()["version"] == 1


# ---------------------------------------------------------------------------
# POST /v1/compliance-packs/<id>/publish
# ---------------------------------------------------------------------------


def test_compliance_packs_publish_not_found(packs_client):
    res = packs_client.post("/api/v1/compliance-packs/NOT-EXIST/publish")
    assert res.status_code == 404


def test_compliance_packs_publish_success(packs_client, packs_jail):
    pack = {"id": "STD-J", "name": "J", "checks": [], "version": 1}
    (packs_jail["packs_dir"] / "STD-J.json").write_text(json.dumps(pack), encoding="utf-8")

    res = packs_client.post("/api/v1/compliance-packs/STD-J/publish")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert "STD-J" in data["message"]


# ---------------------------------------------------------------------------
# POST /v1/compliance-packs/<id>/test
# ---------------------------------------------------------------------------


def test_compliance_packs_test_missing_run_id(packs_client):
    res = packs_client.post("/api/v1/compliance-packs/STD-K/test")
    assert res.status_code == 400
    assert "run_id" in res.get_json()["error"]


def test_compliance_packs_test_run_not_found(packs_client, packs_jail):
    res = packs_client.post("/api/v1/compliance-packs/STD-K/test?run_id=missing-run")
    assert res.status_code == 404


def test_compliance_packs_test_success_all_pass(packs_client, packs_jail):
    run_id = "test_run_k"
    run_dir = packs_jail["runs"] / run_id
    run_dir.mkdir()
    trace = run_dir / "run.jsonl"
    trace.write_text(json.dumps({"run_id": run_id, "status": "COMPLETED"}) + "\n", encoding="utf-8")

    pack = {
        "id": "STD-K",
        "name": "K",
        "checks": [
            {"type": "pqc_required", "params": {"min_algorithm": "ML-DSA-65"}},
            {"type": "wsm_threshold", "params": {"dimension": "security", "min_score": 0.1}},
            {"type": "rubric_required", "params": {"rubric": "fiduciary", "min_score": 0.8}},
            {"type": "ija_threshold", "params": {"min_value": 0.75}},
        ],
        "version": 1,
    }
    (packs_jail["packs_dir"] / "STD-K.json").write_text(json.dumps(pack), encoding="utf-8")

    certs_dir = packs_jail["reports"] / "certificates"
    certs_dir.mkdir(parents=True, exist_ok=True)
    vc_file = certs_dir / f"{run_id}_vc.json"
    vc_file.write_text(
        json.dumps(
            {
                "rubrics": {"fiduciary": 0.95},
                "ija_score": 0.90,
                "metrics": {"wsm_security": 0.92},
            }
        ),
        encoding="utf-8",
    )

    with patch(
        "eval_runner.console.routes.compliance_packs.explain_trace",
        return_value={"confidence": 0.9, "root_cause": "ok", "wsm_score": 0.92},
    ):
        with patch(
            "eval_runner.console.routes.compliance_packs.resolve_trace_path",
            return_value=trace,
        ):
            res = packs_client.post(f"/api/v1/compliance-packs/STD-K/test?run_id={run_id}")

    assert res.status_code == 200
    data = res.get_json()
    assert data["overall_pass"] is True
    assert len(data["checks"]) == 4


def test_compliance_packs_test_unknown_type_fail_closed(packs_client, packs_jail):
    run_id = "test_run_unknown"
    run_dir = packs_jail["runs"] / run_id
    run_dir.mkdir()
    trace = run_dir / "run.jsonl"
    trace.write_text(json.dumps({"run_id": run_id, "status": "COMPLETED"}) + "\n", encoding="utf-8")

    pack = {
        "id": "STD-UNKNOWN",
        "name": "Unknown",
        "checks": [{"type": "unknown_future_check", "params": {}}],
        "version": 1,
    }
    (packs_jail["packs_dir"] / "STD-UNKNOWN.json").write_text(json.dumps(pack), encoding="utf-8")

    with patch(
        "eval_runner.console.routes.compliance_packs.resolve_trace_path",
        return_value=trace,
    ):
        res = packs_client.post(f"/api/v1/compliance-packs/STD-UNKNOWN/test?run_id={run_id}")

    assert res.status_code == 200
    data = res.get_json()
    assert data["overall_pass"] is False
    assert data["checks"][0]["status"] == "FAIL"
    assert "Unsupported" in data["checks"][0]["details"]


def test_compliance_packs_test_pqc_fail(packs_client, packs_jail):
    run_id = "test_run_l"
    run_dir = packs_jail["runs"] / run_id
    run_dir.mkdir()
    trace = run_dir / "run.jsonl"
    trace.write_text(json.dumps({"run_id": run_id, "status": "FAILED"}) + "\n", encoding="utf-8")

    pack = {
        "id": "STD-L",
        "name": "L",
        "checks": [{"type": "pqc_required", "params": {}}],
        "version": 1,
    }
    (packs_jail["packs_dir"] / "STD-L.json").write_text(json.dumps(pack), encoding="utf-8")

    with patch(
        "eval_runner.console.routes.compliance_packs.explain_trace",
        return_value={"confidence": 0.3},
    ):
        with patch(
            "eval_runner.console.routes.compliance_packs.resolve_trace_path",
            return_value=trace,
        ):
            res = packs_client.post(f"/api/v1/compliance-packs/STD-L/test?run_id={run_id}")

    assert res.status_code == 200
    data = res.get_json()
    assert data["overall_pass"] is False
    assert data["checks"][0]["status"] == "FAIL"


def test_compliance_packs_test_wsm_threshold_fail(packs_client, packs_jail):
    run_id = "test_run_m"
    run_dir = packs_jail["runs"] / run_id
    run_dir.mkdir()
    trace = run_dir / "run.jsonl"
    trace.write_text(json.dumps({"run_id": run_id, "status": "COMPLETED"}) + "\n", encoding="utf-8")

    pack = {
        "id": "STD-M",
        "name": "M",
        "checks": [
            {"type": "wsm_threshold", "params": {"dimension": "security", "min_score": 0.99}}
        ],
        "version": 1,
    }
    (packs_jail["packs_dir"] / "STD-M.json").write_text(json.dumps(pack), encoding="utf-8")

    with patch(
        "eval_runner.console.routes.compliance_packs.explain_trace",
        return_value={"confidence": 0.1},
    ):
        with patch(
            "eval_runner.console.routes.compliance_packs.resolve_trace_path",
            return_value=trace,
        ):
            res = packs_client.post(f"/api/v1/compliance-packs/STD-M/test?run_id={run_id}")

    data = res.get_json()
    assert data["overall_pass"] is False
    assert data["checks"][0]["status"] == "FAIL"


def test_compliance_packs_test_explain_trace_exception(packs_client, packs_jail):
    run_id = "test_run_n"
    run_dir = packs_jail["runs"] / run_id
    run_dir.mkdir()
    trace = run_dir / "run.jsonl"
    trace.write_text(json.dumps({"run_id": run_id}) + "\n", encoding="utf-8")

    pack = {"id": "STD-N", "name": "N", "checks": [], "version": 1}
    (packs_jail["packs_dir"] / "STD-N.json").write_text(json.dumps(pack), encoding="utf-8")

    with patch(
        "eval_runner.console.routes.compliance_packs.explain_trace",
        side_effect=RuntimeError("explain crash"),
    ):
        with patch(
            "eval_runner.console.routes.compliance_packs.resolve_trace_path",
            return_value=trace,
        ):
            res = packs_client.post(f"/api/v1/compliance-packs/STD-N/test?run_id={run_id}")

    assert res.status_code == 200
    assert res.get_json()["overall_pass"] is True


def test_compliance_packs_test_no_pack_file(packs_client, packs_jail):
    """When pack file doesn't exist, checks list is empty → overall_pass True."""
    run_id = "test_run_o"
    run_dir = packs_jail["runs"] / run_id
    run_dir.mkdir()
    trace = run_dir / "run.jsonl"
    trace.write_text(json.dumps({"run_id": run_id}) + "\n", encoding="utf-8")

    with patch(
        "eval_runner.console.routes.compliance_packs.explain_trace",
        return_value={"confidence": 0.9},
    ):
        with patch(
            "eval_runner.console.routes.compliance_packs.resolve_trace_path",
            return_value=trace,
        ):
            res = packs_client.post("/api/v1/compliance-packs/STD-NOFILE/test?run_id=test_run_o")

    assert res.status_code == 200
    assert res.get_json()["checks"] == []


def test_compliance_packs_load_standards_failure(packs_client, packs_jail):
    """Verify standards load failure path is covered."""
    std_path = packs_jail["root"] / "spec" / "aes" / "standards.json"
    std_path.parent.mkdir(parents=True, exist_ok=True)
    std_path.write_text("{}", encoding="utf-8")

    with patch("builtins.open", side_effect=OSError("Read error")):
        res = packs_client.get("/api/v1/compliance-packs")
    assert res.status_code == 200
    assert res.get_json()["packs"] == []


def test_compliance_packs_save_pack_failure(packs_client):
    """Verify save compliance pack file write exception is handled."""
    with patch("builtins.open", side_effect=OSError("Write error")):
        res = packs_client.post(
            "/api/v1/compliance-packs",
            json={"id": "STD-FAIL", "name": "Standard Fail", "checks": []},
        )
    assert res.status_code == 500
    assert "Write error" in res.get_json()["error"]


def test_compliance_packs_test_pack_read_error(packs_client, packs_jail):
    """Verify pack read config file open exception is handled."""
    run_id = "run_read_err"
    run_dir = packs_jail["runs"] / run_id
    run_dir.mkdir()
    (run_dir / "run.jsonl").write_text("{}", encoding="utf-8")

    # Write a pack file
    (packs_jail["packs_dir"] / "STD-READ-ERR.json").write_text("{}", encoding="utf-8")

    orig_open = open

    def mock_open(file, *args, **kwargs):
        if str(file).endswith("STD-READ-ERR.json"):
            raise OSError("Read failure")
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open):
        with patch(
            "eval_runner.console.routes.compliance_packs.resolve_trace_path",
            return_value=run_dir / "run.jsonl",
        ):
            res = packs_client.post(f"/api/v1/compliance-packs/STD-READ-ERR/test?run_id={run_id}")

    assert res.status_code == 200
    # Checks list is empty because config read failed
    assert res.get_json()["checks"] == []


def test_compliance_packs_test_master_log_scanner(packs_client, packs_jail):
    """Verify scanner for master log handles various paths."""
    run_id = "master_scan_1"
    master_log = packs_jail["runs"] / "run.jsonl"

    # JSON decode error in loop, correct line, and normal line
    line_correct = json.dumps({"run_id": run_id, "status": "COMPLETED"})
    line_corrupt = f'{{"run_id": "{run_id}", "status": corrupt}}'
    line_other = json.dumps({"run_id": "other_run"})
    line_partial = json.dumps({"run_id": "other_run", "tags": [run_id]})
    master_log.write_text(
        f"{line_other}\n{line_corrupt}\n{line_partial}\n{line_correct}\n", encoding="utf-8"
    )

    # Mock resolve_trace_path to return None to force master log fallback
    with patch("eval_runner.console.routes.compliance_packs.resolve_trace_path", return_value=None):
        res = packs_client.post(f"/api/v1/compliance-packs/STD-G/test?run_id={run_id}")
    assert res.status_code == 200


def test_compliance_packs_test_master_log_scanner_read_error(packs_client, packs_jail):
    """Verify master log read failure is handled gracefully."""
    run_id = "master_scan_err"
    master_log = packs_jail["runs"] / "run.jsonl"
    master_log.write_text("{}", encoding="utf-8")

    orig_open = open

    def mock_open(file, *args, **kwargs):
        if str(file).endswith("run.jsonl"):
            raise OSError("Master log read error")
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open):
        with patch(
            "eval_runner.console.routes.compliance_packs.resolve_trace_path", return_value=None
        ):
            res = packs_client.post(f"/api/v1/compliance-packs/STD-G/test?run_id={run_id}")
    assert res.status_code == 404


def test_compliance_packs_first_trace_line_read_failure(packs_client, packs_jail):
    """Verify trace first line read exception is handled."""
    run_id = "trace_first_fail"
    run_dir = packs_jail["runs"] / run_id
    run_dir.mkdir()
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text("{}", encoding="utf-8")

    orig_open = open

    def mock_open(file, *args, **kwargs):
        if str(file).endswith("run.jsonl") and "runs" in str(file):
            raise OSError("First line read error")
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open):
        with patch(
            "eval_runner.console.routes.compliance_packs.resolve_trace_path",
            return_value=trace_path,
        ):
            res = packs_client.post(f"/api/v1/compliance-packs/STD-G/test?run_id={run_id}")

    assert res.status_code == 200


def test_compliance_packs_test_empty_trace_file(packs_client, packs_jail):
    """Verify empty trace file handles first line read."""
    run_id = "trace_empty"
    run_dir = packs_jail["runs"] / run_id
    run_dir.mkdir()
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text("", encoding="utf-8")

    with patch(
        "eval_runner.console.routes.compliance_packs.resolve_trace_path", return_value=trace_path
    ):
        res = packs_client.post(f"/api/v1/compliance-packs/STD-G/test?run_id={run_id}")
    assert res.status_code == 200


def test_compliance_packs_list_custom_success(packs_client, packs_jail):
    """Cover discovery of custom user-defined compliance pack JSON files."""
    custom_pack = {
        "name": "My Custom Compliance Pack",
        "description": "Custom requirements",
        "version": 2,
        "checks": [{"type": "wsm_threshold"}],
    }
    (packs_jail["packs_dir"] / "custom_pack_123.json").write_text(
        json.dumps(custom_pack), encoding="utf-8"
    )

    res = packs_client.get("/api/v1/compliance-packs")
    assert res.status_code == 200
    data = res.get_json()
    # Predefined standards plus one custom pack
    custom = next((p for p in data["packs"] if p["id"] == "custom_pack_123"), None)
    assert custom is not None
    assert custom["name"] == "My Custom Compliance Pack"
    assert custom["version"] == 2
    assert custom["configured"] is True


def test_compliance_packs_list_custom_corrupt(packs_client, packs_jail):
    """Cover loader exception logging when loading a malformed custom pack."""
    (packs_jail["packs_dir"] / "custom_corrupt.json").write_text("{{corrupt", encoding="utf-8")

    res = packs_client.get("/api/v1/compliance-packs")
    assert res.status_code == 200
    # Should not crash, bad JSON skipped and logged
    data = res.get_json()
    assert not any(p["id"] == "custom_corrupt" for p in data["packs"])


def test_compliance_packs_publish_auto_create(packs_client, packs_jail):
    """Cover auto-creation of predefined compliance packs on publish."""
    # Ensure ISO27001 is a predefined standard but the file does not exist yet
    pack_file = packs_jail["packs_dir"] / "ISO27001.json"
    if pack_file.exists():
        pack_file.unlink()

    with patch(
        "eval_runner.console.routes.compliance_packs._load_standards",
        return_value=[{"id": "ISO27001", "name": "ISO 27001 Standard", "description": "desc"}],
    ):
        res = packs_client.post("/api/v1/compliance-packs/ISO27001/publish")
        assert res.status_code == 200
        assert pack_file.exists()

        # Load and check it was auto-created with the standard details
        data = json.loads(pack_file.read_text(encoding="utf-8"))
        assert data["id"] == "ISO27001"
        assert "ISO 27001" in data["name"]


def test_compliance_packs_publish_auto_create_write_error(packs_client, packs_jail):
    """Cover write exception handling during auto-creation on publish."""
    pack_file = packs_jail["packs_dir"] / "ISO27001.json"
    if pack_file.exists():
        pack_file.unlink()

    with patch(
        "eval_runner.console.routes.compliance_packs._load_standards",
        return_value=[{"id": "ISO27001", "name": "ISO 27001 Standard", "description": "desc"}],
    ):
        with patch("builtins.open", side_effect=PermissionError("File locked")):
            res = packs_client.post("/api/v1/compliance-packs/ISO27001/publish")
            assert res.status_code == 500
            assert "File locked" in res.get_json()["error"]


def test_compliance_packs_test_rubric_required_pass_and_fail(packs_client, packs_jail):
    """
    Verify that rubric_required performs real evaluation and fails
    when threshold is unmet or missing.
    """
    run_id = "test_run_rubric"
    run_dir = packs_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace = run_dir / "run.jsonl"
    trace.write_text(json.dumps({"run_id": run_id, "status": "COMPLETED"}) + "\n", encoding="utf-8")

    # 1. Test missing rubric score -> FAIL
    pack_fail = {
        "id": "STD-RUBRIC-FAIL",
        "name": "Rubric Test Pack Fail",
        "checks": [
            {
                "type": "rubric_required",
                "params": {"rubric": "fiduciary_accuracy", "min_score": 0.85},
            }
        ],
        "version": 1,
    }
    (packs_jail["packs_dir"] / "STD-RUBRIC-FAIL.json").write_text(
        json.dumps(pack_fail), encoding="utf-8"
    )

    with patch(
        "eval_runner.console.routes.compliance_packs.resolve_trace_path",
        return_value=trace,
    ):
        res = packs_client.post(f"/api/v1/compliance-packs/STD-RUBRIC-FAIL/test?run_id={run_id}")

    data = res.get_json()
    assert res.status_code == 200
    assert data["overall_pass"] is False
    assert data["checks"][0]["status"] == "FAIL"
    assert "not evaluated" in data["checks"][0]["details"]

    # 2. Test passing rubric score in certificate -> PASS
    certs_dir = packs_jail["reports"] / "certificates"
    certs_dir.mkdir(parents=True, exist_ok=True)
    vc_file = certs_dir / f"{run_id}_vc.json"
    vc_file.write_text(
        json.dumps({"rubrics": {"fiduciary_accuracy": 0.95}}),
        encoding="utf-8",
    )

    pack_pass = {
        "id": "STD-RUBRIC-PASS",
        "name": "Rubric Test Pack Pass",
        "checks": [
            {
                "type": "rubric_required",
                "params": {"rubric": "fiduciary_accuracy", "min_score": 0.85},
            }
        ],
        "version": 1,
    }
    (packs_jail["packs_dir"] / "STD-RUBRIC-PASS.json").write_text(
        json.dumps(pack_pass), encoding="utf-8"
    )

    with patch(
        "eval_runner.console.routes.compliance_packs.resolve_trace_path",
        return_value=trace,
    ):
        res_pass = packs_client.post(
            f"/api/v1/compliance-packs/STD-RUBRIC-PASS/test?run_id={run_id}"
        )

    data_pass = res_pass.get_json()
    assert res_pass.status_code == 200
    assert data_pass["overall_pass"] is True
    assert data_pass["checks"][0]["status"] == "PASS"


def test_compliance_packs_test_ija_threshold_pass_and_fail(packs_client, packs_jail):
    """
    Verify that ija_threshold performs real evaluation and fails
    when threshold is unmet or missing.
    """
    run_id = "test_run_ija"
    run_dir = packs_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace = run_dir / "run.jsonl"
    trace.write_text(json.dumps({"run_id": run_id, "status": "COMPLETED"}) + "\n", encoding="utf-8")

    # 1. Test missing IJA -> FAIL
    pack_ija_fail = {
        "id": "STD-IJA-FAIL",
        "name": "IJA Test Pack Fail",
        "checks": [{"type": "ija_threshold", "params": {"min_value": 0.80}}],
        "version": 1,
    }
    (packs_jail["packs_dir"] / "STD-IJA-FAIL.json").write_text(
        json.dumps(pack_ija_fail), encoding="utf-8"
    )

    with patch(
        "eval_runner.console.routes.compliance_packs.resolve_trace_path",
        return_value=trace,
    ):
        res = packs_client.post(f"/api/v1/compliance-packs/STD-IJA-FAIL/test?run_id={run_id}")

    data = res.get_json()
    assert res.status_code == 200
    assert data["overall_pass"] is False
    assert data["checks"][0]["status"] == "FAIL"
    assert "missing" in data["checks"][0]["details"].lower()

    # 2. Test below threshold -> FAIL
    certs_dir = packs_jail["reports"] / "certificates"
    certs_dir.mkdir(parents=True, exist_ok=True)
    vc_file = certs_dir / f"{run_id}_vc.json"
    vc_file.write_text(json.dumps({"ija_score": 0.65}), encoding="utf-8")

    with patch(
        "eval_runner.console.routes.compliance_packs.resolve_trace_path",
        return_value=trace,
    ):
        res_below = packs_client.post(f"/api/v1/compliance-packs/STD-IJA-FAIL/test?run_id={run_id}")

    data_below = res_below.get_json()
    assert data_below["overall_pass"] is False
    assert data_below["checks"][0]["status"] == "FAIL"
    assert "below" in data_below["checks"][0]["details"].lower()

    # 3. Test above threshold -> PASS
    vc_file.write_text(json.dumps({"ija_score": 0.92}), encoding="utf-8")
    pack_ija_pass = {
        "id": "STD-IJA-PASS",
        "name": "IJA Test Pack Pass",
        "checks": [{"type": "ija_threshold", "params": {"min_value": 0.80}}],
        "version": 1,
    }
    (packs_jail["packs_dir"] / "STD-IJA-PASS.json").write_text(
        json.dumps(pack_ija_pass), encoding="utf-8"
    )

    with patch(
        "eval_runner.console.routes.compliance_packs.resolve_trace_path",
        return_value=trace,
    ):
        res_pass = packs_client.post(f"/api/v1/compliance-packs/STD-IJA-PASS/test?run_id={run_id}")

    data_pass = res_pass.get_json()
    assert data_pass["overall_pass"] is True
    assert data_pass["checks"][0]["status"] == "PASS"
