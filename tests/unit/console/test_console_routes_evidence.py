"""
tests/unit/console/test_console_routes_evidence.py
Comprehensive unit test suite achieving 100% coverage on the
Evidence & Verification Package API routes with dynamic timestamps.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from eval_runner import config
from eval_runner.console.app import create_app
from eval_runner.console.routes.evidence import (
    compute_sha3_digest,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUN_LOG_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(config, "REPORTS_DIR", str(tmp_path / "reports"))
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"id": "test-admin", "name": "Admin", "permissions": ["*"]}
        yield c


def test_compute_sha3_digest():
    digest_bytes = compute_sha3_digest(b"test content")
    digest_str = compute_sha3_digest("test content")
    assert digest_bytes == digest_str
    assert digest_bytes.startswith("sha3_256:")


def test_get_verification_package_not_found(client):
    res = client.get("/api/v1/evidence/packages/run-nonexistent")
    assert res.status_code == 404
    data = res.get_json()
    assert "error" in data


def test_get_verification_package_success_with_cert_and_provenance(client, tmp_path):
    runs_dir = tmp_path / "runs"
    reports_dir = tmp_path / "reports"
    run_id = f"run-test-{int(datetime.now(UTC).timestamp())}"
    run_vault = runs_dir / run_id
    run_vault.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)

    # Write trace events with empty/corrupt line handling and dynamic timestamps
    trace_file = run_vault / f"{run_id}.jsonl"
    events = [
        {
            "event": "run_start",
            "timestamp": now.isoformat(),
            "data": {"scenario": "sec_eval"},
        },
        {
            "event": "assertion_evaluated",
            "timestamp": (now + timedelta(seconds=5)).isoformat(),
            "data": {"name": "check1", "passed": True},
        },
        {
            "event": "run_end",
            "timestamp": (now + timedelta(seconds=10)).isoformat(),
            "data": {"status": "EXECUTION_COMPLETED", "passed": True, "score": 1.0},
        },
    ]
    raw_lines = "\n".join(json.dumps(e) for e in events) + "\n\n{invalid json line\n"
    trace_file.write_text(raw_lines, encoding="utf-8")

    # Write scenario_resolved and manifest
    (run_vault / "scenario_resolved.json").write_text(
        json.dumps({"id": "sec_eval", "title": "Security Eval"}), encoding="utf-8"
    )
    (run_vault / "run_manifest.json").write_text(
        json.dumps({"tenant_id": "t-acme", "workspace_id": "ws-sec"}), encoding="utf-8"
    )

    # Write certificate in reports_dir
    cert_dir = reports_dir / "certificates"
    cert_dir.mkdir(parents=True, exist_ok=True)
    (cert_dir / f"{run_id}_certificate.json").write_text(
        json.dumps({"signatures": ["sig_ed25519_test"], "provenance_chain": ["p1", "p2"]}),
        encoding="utf-8",
    )

    # Query API
    res = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()
    assert pkg["format"] == "agentv_verification_package"
    assert pkg["package_version"] == "2.0.0"
    assert pkg["tenant_id"] == "t-acme"

    assert pkg["verdict"]["verified_outcome"] == "VERIFIED"
    assert pkg["signatures"] == ["sig_ed25519_test"]
    assert "package_hash" in pkg
    assert pkg["package_hash"].startswith("sha3_256:")


def test_get_verification_package_policy_breach_and_vault_cert(client, tmp_path):
    runs_dir = tmp_path / "runs"
    run_id = f"run-breach-{int(datetime.now(UTC).timestamp())}"
    run_vault = runs_dir / run_id
    run_vault.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)

    # Write trace events with policy violation
    trace_file = run_vault / "run.jsonl"
    events = [
        {"event": "run_start", "timestamp": now.isoformat(), "data": {}},
        {
            "event": "policy_violation",
            "timestamp": (now + timedelta(seconds=5)).isoformat(),
            "data": {"rule": "no_exfil"},
        },
        {
            "event": "run_end",
            "timestamp": (now + timedelta(seconds=10)).isoformat(),
            "data": {"status": "EXECUTION_COMPLETED", "passed": False},
        },
    ]
    trace_file.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    # Vault certificate
    (run_vault / f"{run_id}_certificate.json").write_text(
        json.dumps({"provenance_chain": ["prov_root"]}),
        encoding="utf-8",
    )

    res = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()
    assert pkg["verdict"]["verified_outcome"] == "POLICY_BREACH"
    assert pkg["signatures"] == ["prov_root"]


def test_corrupt_files_in_vault(client, tmp_path):
    runs_dir = tmp_path / "runs"
    run_id = f"run-corrupt-{int(datetime.now(UTC).timestamp())}"
    run_vault = runs_dir / run_id
    run_vault.mkdir(parents=True, exist_ok=True)

    trace_file = run_vault / f"{run_id}.jsonl"
    trace_file.write_text(json.dumps({"event": "run_start", "data": {}}) + "\n", encoding="utf-8")

    # Corrupt json files
    (run_vault / "scenario_resolved.json").write_text("NOT_JSON", encoding="utf-8")
    (run_vault / "run_manifest.json").write_text("NOT_JSON", encoding="utf-8")
    (run_vault / f"{run_id}_certificate.json").write_text("NOT_JSON", encoding="utf-8")

    res = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()
    assert pkg["tenant_id"] == "default-tenant"
    assert pkg["workspace_id"] == "default-workspace"


def test_download_verification_package(client, tmp_path):
    runs_dir = tmp_path / "runs"
    run_id = f"run-download-{int(datetime.now(UTC).timestamp())}"
    run_vault = runs_dir / run_id
    run_vault.mkdir(parents=True, exist_ok=True)

    trace_file = run_vault / f"{run_id}.jsonl"
    trace_file.write_text(json.dumps({"event": "run_start", "data": {}}) + "\n", encoding="utf-8")

    res = client.get(f"/api/v1/evidence/packages/{run_id}?download=true")
    assert res.status_code == 200
    assert "application/json" in res.content_type
    assert f"{run_id}.agentv-package.json" in res.headers.get("Content-Disposition", "")


def test_list_verification_packages(client, tmp_path):
    runs_dir = tmp_path / "runs"
    (runs_dir / "run-001").mkdir(parents=True, exist_ok=True)
    (runs_dir / "run-002").mkdir(parents=True, exist_ok=True)
    (runs_dir / "ignored_file.txt").write_text("hello", encoding="utf-8")

    res = client.get("/api/v1/evidence/packages")
    assert res.status_code == 200
    data = res.get_json()
    assert "packages" in data
    assert len(data["packages"]) >= 2


def test_list_verification_packages_empty_dir(client, tmp_path, monkeypatch):
    nonexistent_dir = tmp_path / "does_not_exist"
    monkeypatch.setattr(config, "RUN_LOG_DIR", str(nonexistent_dir))

    res = client.get("/api/v1/evidence/packages")
    assert res.status_code == 200
    data = res.get_json()
    assert data["packages"] == []


def test_verification_package_determinism_and_unsigned_outcome(client, tmp_path):
    runs_dir = tmp_path / "runs"
    run_id = f"run-unsigned-{int(datetime.now(UTC).timestamp())}"
    run_vault = runs_dir / run_id
    run_vault.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)

    trace_file = run_vault / "run.jsonl"
    events = [
        {"event": "run_start", "timestamp": now.isoformat(), "data": {}},
        {
            "event": "run_end",
            "timestamp": (now + timedelta(seconds=10)).isoformat(),
            "data": {"status": "EXECUTION_COMPLETED", "passed": True, "score": 0.85},
        },
    ]
    trace_file.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    res1 = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res1.status_code == 200
    pkg1 = res1.get_json()
    # Without signatures, passed run is marked UNVERIFIED
    assert pkg1["verdict"]["verified_outcome"] == "UNVERIFIED"
    assert pkg1["verdict"]["score"] == 0.85

    res2 = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res2.status_code == 200
    pkg2 = res2.get_json()

    # Package hash MUST be 100% deterministic despite different timestamps
    assert pkg1["package_hash"] == pkg2["package_hash"]


def test_verification_package_direct_fragment_without_vault(client, tmp_path):
    runs_dir = tmp_path / "runs"
    run_id = f"run-direct-frag-{int(datetime.now(UTC).timestamp())}"
    trace_file = runs_dir / f"{run_id}.jsonl"
    now = datetime.now(UTC)
    events = [
        {"event": "run_start", "timestamp": now.isoformat(), "data": {}},
        {
            "event": "run_end",
            "timestamp": (now + timedelta(seconds=10)).isoformat(),
            "data": {"status": "EXECUTION_COMPLETED", "passed": False},
        },
    ]
    trace_file.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    res = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()
    assert pkg["verdict"]["verified_outcome"] == "NOT_VERIFIED"
    assert pkg["verdict"]["score"] == 0.0


def test_verification_package_score_default_verified(client, tmp_path):
    runs_dir = tmp_path / "runs"
    reports_dir = tmp_path / "reports"
    run_id = f"run-default-verified-{int(datetime.now(UTC).timestamp())}"
    run_vault = runs_dir / run_id
    run_vault.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)

    trace_file = run_vault / "run.jsonl"
    events = [
        {"event": "run_start", "timestamp": now.isoformat(), "data": {}},
        {
            "event": "run_end",
            "timestamp": (now + timedelta(seconds=10)).isoformat(),
            "data": {"status": "EXECUTION_COMPLETED", "verified": True},
        },
    ]
    trace_file.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

    cert_dir = reports_dir / "certificates"
    cert_dir.mkdir(parents=True, exist_ok=True)
    (cert_dir / f"{run_id}_certificate.json").write_text(
        json.dumps({"signatures": ["sig_test"]}), encoding="utf-8"
    )

    res = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()
    assert pkg["verdict"]["verified_outcome"] == "VERIFIED"
    assert pkg["verdict"]["score"] == 1.0
