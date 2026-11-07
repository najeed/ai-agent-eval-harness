from argparse import Namespace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.handlers import analysis, evaluation
from eval_runner.identity import IdentityService
from eval_runner.services.certification import execute_industrial_certification
from tests.acceptance.test_acceptance_provider_native_certification import _seed_provider_run


@pytest.fixture
def pqc_env(tmp_path, monkeypatch):
    """Setup a physical context for PQC CLI testing."""
    root = tmp_path / "root"
    root.mkdir()

    runs_dir = root / "runs"
    runs_dir.mkdir()
    reports_dir = root / "reports"
    reports_dir.mkdir()
    (reports_dir / "certificates").mkdir()

    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", reports_dir)
    monkeypatch.setattr("eval_runner.config.TRUST_ROOT", root / "trust")

    from eval_runner.reference.local_run_store import LocalFileRunStore

    IdentityService._provision_local_identity("eval_kernel")
    run_id = "pqc_test_run"
    store = LocalFileRunStore(log_dir=runs_dir)
    _seed_provider_run(store, run_id)

    return {
        "root": root,
        "run_id": run_id,
        "store": store,
        "trace_path": runs_dir / run_id / "run.jsonl",
        "run_dir": runs_dir / run_id,
    }


@pytest.mark.asyncio
async def test_handle_certify_pqc(pqc_env, monkeypatch):
    """Verify handle_certify produces a hybrid manifest when PQC is enabled."""
    # 1. Setup Mock PQC Client
    mock_client = MagicMock()
    mock_client.sign_digest.return_value = "pqc_signature_hex"
    monkeypatch.setattr(IdentityService, "_pqc_client", mock_client)
    monkeypatch.setattr(config, "PQC_ENABLED", True)
    monkeypatch.setattr(config, "PQC_PROVIDER", "cyclecore")
    IdentityService._provision_local_identity("test_id")

    # 2. Execute Certify
    args = Namespace(
        run_id=pqc_env["run_id"],
        identity="test_id",
        status="pass",
        score=1.0,
        policy_ref=None,
        ttl=None,
        fingerprint=None,
        pqc=True,
    )

    # We simulate the CLI main() logic by manually setting config.PQC_ENABLED
    # since we are calling the handler directly.
    result = await evaluation.handle_certify(args)
    assert result == 0

    # 3. Verify Manifest
    manifest = pqc_env["store"].get_manifest(pqc_env["run_id"])
    assert manifest is not None

    # Hybrid check: provenance_chain should have 2 entries (Classical + PQC)
    chain = manifest["provenance_chain"]
    assert len(chain) == 2
    assert chain[0]["algorithm"] == "ED25519"
    assert chain[1]["algorithm"] == "ML-DSA-65"
    assert chain[1]["signature"] == "pqc_signature_hex"


def _create_signed_pqc_run(store, run_id: str, identity_id: str) -> dict[str, Any]:
    IdentityService._provision_local_identity(identity_id)
    scenario = _seed_provider_run(store, run_id)
    result = execute_industrial_certification(
        run_id, run_store=store, scenario_data=scenario, identity_id=identity_id
    )
    return result["manifest"]


@pytest.mark.asyncio
async def test_handle_verify_pqc(pqc_env, monkeypatch):
    """Verify handle_verify validates a hybrid manifest."""
    identity_id = "test_verify_id"
    mock_client = MagicMock()
    mock_client.sign_digest.return_value = "pqc_sig"
    mock_client.verify_digest.return_value = True
    monkeypatch.setattr(IdentityService, "_pqc_client", mock_client)
    monkeypatch.setattr(config, "PQC_ENABLED", True)

    run_id = "pqc_verify_run"
    store = pqc_env["store"]
    _create_signed_pqc_run(store, run_id, identity_id)

    # Reset calls so this test asserts only on the handler's verification pass
    mock_client.verify_digest.reset_mock()

    args = Namespace(run_id=run_id, pqc=True)
    result = await evaluation.handle_verify(args)
    assert result == 0

    # Ensure PQC client was consulted
    mock_client.verify_digest.assert_called_once()


@pytest.mark.asyncio
async def test_handle_gate_pqc(pqc_env, monkeypatch):
    """Verify handle_gate validates hybrid signatures."""
    identity_id = "gate_id"
    mock_client = MagicMock()
    mock_client.sign_digest.return_value = "gate_pqc_sig"
    mock_client.verify_digest.return_value = True
    monkeypatch.setattr(IdentityService, "_pqc_client", mock_client)
    monkeypatch.setattr(config, "PQC_ENABLED", True)

    run_id = "pqc_gate_run"
    store = pqc_env["store"]
    _create_signed_pqc_run(store, run_id, identity_id)

    mock_client.verify_digest.reset_mock()

    args = Namespace(run_id=run_id, hash=None, verify_ledger=True, pqc=True)
    result = await evaluation.handle_gate(args)
    assert result == 0

    # Ensure PQC client was consulted
    mock_client.verify_digest.assert_called_once()


@pytest.mark.asyncio
async def test_handle_report_pqc_flag(pqc_env, monkeypatch, capsys):
    """Verify handle_report accepts the PQC flag without error."""
    # handle_report doesn't do much with PQC right now other than branding,
    # but we must ensure the flag is accepted.
    monkeypatch.setattr(config, "PQC_ENABLED", True)

    # Mocking reporter to avoid actual HTML file generation overhead
    with patch("eval_runner.reporter.generate_html_report") as mock_report:
        mock_report.return_value = Path("dummy.html")

        args = Namespace(run_id=pqc_env["run_id"], share=False, pqc=True)
        result = await analysis.handle_report(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "[Report] Generating stylized HTML" in captured.out
