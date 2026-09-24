"""Keyless end-to-end certification smoke test against the real sample HTTP agent."""

from __future__ import annotations

import socket
import threading

import pytest
from werkzeug.serving import make_server

from eval_runner import config
from eval_runner.engine import run_evaluation
from eval_runner.services.certification import execute_industrial_certification
from eval_runner.verifier import TraceVerifier
from sample_agent.agent_app import app as sample_agent_app


class _ServerThread(threading.Thread):
    def __init__(self, port: int) -> None:
        super().__init__(daemon=True)
        self.server = make_server("127.0.0.1", port, sample_agent_app)

    def run(self) -> None:
        self.server.serve_forever()

    def shutdown(self) -> None:
        self.server.shutdown()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.asyncio
async def test_sample_agent_real_http_run_is_certified_and_verified(tmp_path, monkeypatch):
    """Required local proof of the complete evaluation-to-certificate chain."""
    port = _free_port()
    server = _ServerThread(port)
    server.start()
    endpoint = f"http://127.0.0.1:{port}/agent"
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / ".aes" / "keys")
    from eval_runner.identity import IdentityService

    IdentityService._provision_local_identity("system_id")

    scenario = {
        "aes_version": 1.4,
        "id": "sample_agent_certification_smoke",
        "metadata": {
            "name": "sample agent certification smoke",
            "compliance_level": "Standard",
            "execution_mode": "live",
            "agent": {"endpoint": endpoint, "protocol": "http"},
        },
        "workflow": {
            "nodes": [
                {
                    "id": "emergency_triage",
                    "task_description": "The patient reports chest pain and emergency symptoms.",
                    "expected_outcome": [
                        {
                            "target": "message",
                            "expected": "EMERGENCY_ESCALATION_REQUIRED",
                            "mode": "contains",
                        }
                    ],
                }
            ],
            "edges": [],
        },
        "evaluation": {},
    }
    run_id = "sample-agent-certification-smoke"
    try:
        await run_evaluation(
            scenario, run_id=run_id, metadata={"execution_mode": "live"}, max_turns=1
        )
        certificate = execute_industrial_certification(run_id=run_id, scenario_data=scenario)
        trace_path = runs_dir / run_id / "run.jsonl"
        manifest_path = runs_dir / run_id / "run_manifest.json"
        assert certificate["certified"] is True
        assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path))
    finally:
        server.shutdown()
        server.join(timeout=3)
