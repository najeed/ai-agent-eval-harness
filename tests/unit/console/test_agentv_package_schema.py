"""
[Spec] agentv-package.json contract: the built package must validate against
spec/agentv-package/agentv-package.schema.json, including the REQUIRED
five-field chain header.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from eval_runner import config
from eval_runner.console.routes.evidence import build_verification_package

SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "spec" / "agentv-package" / "agentv-package.schema.json"
)


@pytest.fixture
def package_vault(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    vault = runs / "pkg-contract-run"
    vault.mkdir(parents=True)

    (vault / "run.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "run_start",
                        "run_id": "pkg-contract-run",
                        "scenario": "sample",
                        "identifier": "target-abc",
                        "execution_mode": "live",
                        "execution_mode_declared": True,
                        "reproducibility_fingerprint": "sha3_256:" + "a" * 64,
                    }
                ),
                json.dumps(
                    {
                        "event": "run_end",
                        "run_id": "pkg-contract-run",
                        "data": {"passed": False, "status": "EXECUTION_FAILED"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (vault / "scenario_resolved.json").write_text(
        json.dumps({"id": "sample", "aes_version": 1.4}), encoding="utf-8"
    )

    monkeypatch.setattr(config, "RUN_LOG_DIR", runs)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    return "pkg-contract-run"


def test_package_validates_against_spec_schema(package_vault):
    pkg = build_verification_package(package_vault)
    assert pkg is not None

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=pkg, schema=schema)


def test_chain_header_binds_five_fields(package_vault):
    from agentv_runtime.manifest import compute_scenario_hash

    pkg = build_verification_package(package_vault)
    chain = pkg["chain"]

    assert chain["run_id"] == package_vault
    assert chain["scenario_hash"] == compute_scenario_hash({"id": "sample", "aes_version": 1.4})
    assert chain["resolved_config_hash"] == "sha3_256:" + "a" * 64
    assert chain["agent_target_id"] == "target-abc"
    assert chain["execution_mode"] == "live"
    assert chain["execution_mode_declared"] is True


def test_undeclared_mode_stamps_unknown_provisional(tmp_path, monkeypatch):
    """A trace with no declared mode yields truthful unknown + provisional."""
    runs = tmp_path / "runs"
    vault = runs / "legacy-run"
    vault.mkdir(parents=True)
    (vault / "run.jsonl").write_text(
        json.dumps({"event": "run_end", "data": {"passed": False}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")

    pkg = build_verification_package("legacy-run")
    assert pkg["chain"]["execution_mode"] == "unknown"
    assert pkg["chain"]["execution_mode_declared"] is False
