"""
tests/unit/console/test_gui_endpoint_schemas.py

Endpoint-schema suite: locks the GET response contracts of the
console API against JSON Schemas in ``spec/console-api/``. One test per
endpoint; a violation prints the field-level diff instead of a bare assert.

Harness pattern mirrors test_console_routes_runs.py: bare Flask app +
blueprint registration, config paths monkeypatched into a per-module jail,
AGENTV_TEST_AUTH_BYPASS=1 supplied by tests/unit/console/conftest.py.
"""

import json
import tempfile
from pathlib import Path

import pytest
from flask import Flask
from jsonschema import Draft7Validator

from eval_runner import config
from eval_runner.console.routes import core_bp
from eval_runner.console.routes.agent_targets import agent_targets_bp
from eval_runner.console.routes.evidence import evidence_bp
from eval_runner.console.routes.runs import run_bp, runs_cache
from eval_runner.console.routes.scenarios import scenario_bp
from eval_runner.console.routes.system import system_bp
from eval_runner.utils import rmtree_resilient

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "spec" / "console-api"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def api_jail(request):
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "master")
    tmp_root = Path(tempfile.gettempdir()) / f"aes_endpoint_schema_jail_{worker_id}"
    root = tmp_root / "root"
    runs = root / "results"
    reports = root / "reports"

    if tmp_root.exists():
        rmtree_resilient(tmp_root)

    (reports / "certificates").mkdir(parents=True)
    runs.mkdir(parents=True)
    yield {"root": root, "runs": runs, "reports": reports}

    if tmp_root.exists():
        rmtree_resilient(tmp_root)


@pytest.fixture
def api_client(api_jail, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", api_jail["root"])
    monkeypatch.setattr(config, "RUN_LOG_DIR", api_jail["runs"])
    monkeypatch.setattr(config, "REPORTS_DIR", api_jail["reports"])
    monkeypatch.setattr(
        config,
        "AGENT_TARGETS_PATH",
        api_jail["root"] / "data" / "agent_targets.json",
    )

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["NAV_REGISTRY"] = [
        {
            "id": "dashboard",
            "title": "Dashboard",
            "path": "/",
            "icon": "home",
            "type": "internal",
            "group": "Verify",
        }
    ]
    # Production-parity registration order (see console/app.py).
    app.register_blueprint(system_bp, url_prefix="/api")
    app.register_blueprint(scenario_bp, url_prefix="/api")
    app.register_blueprint(run_bp, url_prefix="/api")
    app.register_blueprint(evidence_bp, url_prefix="/api")
    app.register_blueprint(agent_targets_bp)
    # Master blueprint carries the unprefixed /v1 shims (e.g. /v1/doctor).
    app.register_blueprint(core_bp)

    yield app.test_client()


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def _validate_payload(schema_file: str, payload) -> None:
    schema = json.loads((SCHEMA_DIR / schema_file).read_text(encoding="utf-8"))
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        diff = "\n".join(
            f"  - {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors
        )
        raise AssertionError(f"{schema_file} contract violated:\n{diff}")


# ---------------------------------------------------------------------------
# Locked endpoints (one test each)
# ---------------------------------------------------------------------------


def test_runs_contract(api_client, monkeypatch):
    """GET /api/runs — envelope plus server-authoritative verdict badges."""
    monkeypatch.setattr(
        runs_cache,
        "get_runs",
        lambda query="": [{"run_id": "run-r1", "result_status": "success"}],
    )
    res = api_client.get("/api/runs")
    assert res.status_code == 200
    _validate_payload("runs.schema.json", res.get_json())


def test_scenarios_contract(api_client):
    """GET /api/scenarios — faceted listing envelope."""
    res = api_client.get("/api/scenarios")
    assert res.status_code == 200
    _validate_payload("scenarios.schema.json", res.get_json())


def test_nav_contract(api_client):
    """GET /api/nav — consolidated navigation registry."""
    res = api_client.get("/api/nav")
    assert res.status_code == 200
    _validate_payload("nav.schema.json", res.get_json())


def test_system_status_contract(api_client):
    """GET /api/status — RuntimeHealth probe shape (status never unconditional)."""
    res = api_client.get("/api/status")
    assert res.status_code == 200
    _validate_payload("system-status.schema.json", res.get_json())


def test_doctor_contract(api_client):
    """GET /v1/doctor — environmental health audit derived from REAL probes."""
    res = api_client.get("/v1/doctor")
    assert res.status_code == 200
    _validate_payload("doctor.schema.json", res.get_json())


def test_metrics_contract(api_client):
    """GET /api/v1/metrics — metric discovery."""
    res = api_client.get("/api/v1/metrics")
    assert res.status_code == 200
    _validate_payload("metrics.schema.json", res.get_json())


def test_agent_targets_contract(api_client):
    """GET /api/v1/agent-targets — reusable target registry envelope."""
    res = api_client.get("/api/v1/agent-targets")
    assert res.status_code == 200
    _validate_payload("agent-targets.schema.json", res.get_json())


def test_evidence_packages_contract(api_jail, api_client):
    """GET /api/v1/evidence/packages — summary rows for vaulted run dirs."""
    vault = api_jail["runs"] / "run-e2e1"
    vault.mkdir()
    (vault / "run-e2e1_certificate.json").write_text("{}", encoding="utf-8")
    (vault / "run_manifest.json").write_text("{}", encoding="utf-8")

    res = api_client.get("/api/v1/evidence/packages")
    assert res.status_code == 200
    payload = res.get_json()
    assert len(payload["packages"]) == 1, "seeded vault dir must surface one package"
    _validate_payload("evidence-packages.schema.json", payload)


def test_certificate_contract(api_jail, api_client):
    """GET /api/v1/certificates/<run_id> — Public Trust Protocol passthrough."""
    cert_path = api_jail["reports"] / "certificates" / "run-cert1_vc.json"
    cert_path.write_text(
        json.dumps({"run_id": "run-cert1", "trace_hash": "sha3_256:" + "ab" * 32}),
        encoding="utf-8",
    )
    res = api_client.get("/api/v1/certificates/run-cert1")
    assert res.status_code == 200
    _validate_payload("certificate.schema.json", res.get_json())
