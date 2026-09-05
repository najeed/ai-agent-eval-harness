"""
tests.acceptance.conftest
Pytest fixtures and environment isolation for AgentV product acceptance tests.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from eval_runner.identity import IdentityService
from tests.acceptance.support.acceptance_runner import AgentVAcceptanceRunner
from tests.acceptance.support.report import AcceptanceReportAggregator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def signing_identity():
    """Ensure standard system signing identity is provisioned for certification."""
    IdentityService._provision_local_identity("system_id")
    return "system_id"


@pytest.fixture()
def isolated_acceptance_env(tmp_path, monkeypatch, signing_identity):
    """
    Provides an isolated execution environment for acceptance runs, redirecting
    RUN_LOG_DIR, REPORTS_DIR, and TRUST_ROOT into tmp_path while inheriting repo root.
    """
    runs_dir = tmp_path / "runs"
    reports_dir = tmp_path / "reports"
    trust_dir = tmp_path / ".aes" / "keys"

    for d in (runs_dir, reports_dir, trust_dir):
        d.mkdir(parents=True, exist_ok=True)

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    sys_key_dir = trust_dir / "system_id"
    sys_key_dir.mkdir(parents=True, exist_ok=True)
    priv_key = ed25519.Ed25519PrivateKey.generate()
    priv_bytes = priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = priv_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    (sys_key_dir / "private_key.pem").write_bytes(priv_bytes)
    (sys_key_dir / "public_key.pem").write_bytes(pub_bytes)

    env = dict(os.environ)
    env["RUN_LOG_DIR"] = str(runs_dir)
    env["REPORTS_DIR"] = str(reports_dir)
    env["TRUST_ROOT"] = str(trust_dir)
    env["ALLOW_SYSTEM_IDENTITY_PROVISIONING"] = "true"
    env["AES_PUBLIC_KEY_SYSTEM_ID"] = pub_bytes.decode("utf-8")

    runner = AgentVAcceptanceRunner(repo_root=REPO_ROOT, env=env)
    return {
        "runner": runner,
        "runs_dir": runs_dir,
        "reports_dir": reports_dir,
        "trust_dir": trust_dir,
        "env": env,
        "tmp_path": tmp_path,
    }


@pytest.fixture(scope="session")
def acceptance_aggregator(repo_root) -> AcceptanceReportAggregator:
    agg = AcceptanceReportAggregator(repo_root=repo_root)
    yield agg
    if agg.results:
        agg.generate_report_files()
