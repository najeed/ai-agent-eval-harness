import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.handlers import analysis, evaluation
from eval_runner.identity import IdentityService
from eval_runner.verifier import TraceVerifier


def _make_finalization_event(
    run_id: str, scenario_id: str, events: list[str], outcome: str = "pass", score: float = 1.0
) -> str:
    """
    Build a valid EvaluatorFinalizationRecord event
    from a list of already-serialized JSONL lines.
    """
    import hashlib

    from agentv_runtime.canonical import canonical_json_encode
    from agentv_runtime.evidence_graph import build_evidence_graph_from_events
    from agentv_runtime.finalization import EvaluatorFinalizationRecord
    from agentv_runtime.manifest import compute_scenario_hash

    parsed = []
    for line in events:
        line = line.strip()
        if line:
            try:
                parsed.append(json.loads(line))
            except Exception:
                pass

    ev_graph = build_evidence_graph_from_events(parsed)
    evidence_root = ev_graph.get(
        "evidence_root_hash", f"sha3_256:{hashlib.sha3_256(b'empty').hexdigest()}"
    )

    scenario_data = {"id": scenario_id, "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scenario_data)
    exec_manifest_payload = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_hash": scen_hash,
        "execution_mode": "live",
    }
    exec_manifest_hash = (
        f"sha3_256:{hashlib.sha3_256(canonical_json_encode(exec_manifest_payload)).hexdigest()}"
    )

    rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=exec_manifest_hash,
        scenario_id=scenario_id,
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="test_evaluator",
        evaluator_config_hash="sha3_256:abc123",
        required_oracle_ids=[],
        evidence_root_hash=evidence_root,
        outcome=outcome,
        score=score,
        terminal_seq=1,
    )
    fin_dict = rec.to_dict()
    fin_dict["finalization_hash"] = rec.compute_finalization_hash()
    return json.dumps({"event": "evaluator_finalization", "data": fin_dict})


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

    run_id = "pqc_test_run"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_dir / "run.jsonl"
    start_ev = json.dumps(
        {
            "event": "run_start",
            "run_id": "pqc_test_run",
            "scenario_id": "test_scenario",
            "scenario_data": {"id": "test_scenario", "version": "1.0.0"},
            "data": {"execution_mode": "live", "execution_mode_declared": True},
        }
    )
    assert_ev = json.dumps(
        {"event": "assertion_evaluated", "assertion": "accuracy", "passed": True}
    )
    metrics_ev = json.dumps({"event": "summary_metrics", "metrics": {"success_rate": 1.0}})
    end_ev = json.dumps({"event": "run_end", "outcome": "pass", "status": "pass", "score": 1.0})

    core_events = [start_ev, assert_ev, metrics_ev, end_ev]
    fin_ev = _make_finalization_event(run_id, "test_scenario", core_events)
    trace_path.write_text("\n".join(core_events + [fin_ev]) + "\n", encoding="utf-8")

    return {
        "root": root,
        "run_id": run_id,
        "trace_path": trace_path,
        "run_dir": run_dir,
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
    manifest_path = pqc_env["run_dir"] / "run_manifest.json"
    assert manifest_path.exists()
    with open(manifest_path) as f:
        manifest = json.load(f)

    # Hybrid check: provenance_chain should have 2 entries (Classical + PQC)
    chain = manifest["provenance_chain"]
    assert len(chain) == 2
    assert chain[0]["algorithm"] == "ED25519"
    assert chain[1]["algorithm"] == "ML-DSA-65"
    assert chain[1]["signature"] == "pqc_signature_hex"


@pytest.mark.asyncio
async def test_handle_verify_pqc(pqc_env, monkeypatch):
    """Verify handle_verify validates a hybrid manifest."""
    # 1. Create a Hybrid Manifest
    identity_id = "test_verify_id"
    IdentityService.get_private_key(identity_id)

    mock_client = MagicMock()
    mock_client.sign_digest.return_value = "pqc_sig"
    mock_client.verify_digest.return_value = True
    monkeypatch.setattr(IdentityService, "_pqc_client", mock_client)
    monkeypatch.setattr(config, "PQC_ENABLED", True)

    TraceVerifier.sign_trace(
        str(pqc_env["trace_path"]), run_id=pqc_env["run_id"], identity_id=identity_id
    )

    # The transactional certification pipeline already consulted the PQC
    # client during its self-verification stage. Reset so this test asserts
    # only on the handler's own verification pass.
    mock_client.verify_digest.reset_mock()

    # 2. Execute Verify
    args = Namespace(run_id=pqc_env["run_id"], pqc=True)
    result = await evaluation.handle_verify(args)
    assert result == 0

    # Ensure PQC client was consulted
    mock_client.verify_digest.assert_called_once()


@pytest.mark.asyncio
async def test_handle_gate_pqc(pqc_env, monkeypatch):
    """Verify handle_gate validates hybrid signatures."""
    # 1. Create Hybrid Manifest
    identity_id = "gate_id"
    IdentityService.get_private_key(identity_id)

    mock_client = MagicMock()
    mock_client.sign_digest.return_value = "gate_pqc_sig"
    mock_client.verify_digest.return_value = True
    monkeypatch.setattr(IdentityService, "_pqc_client", mock_client)
    monkeypatch.setattr(config, "PQC_ENABLED", True)

    TraceVerifier.sign_trace(
        str(pqc_env["trace_path"]), run_id=pqc_env["run_id"], identity_id=identity_id
    )

    # Reset pipeline self-verification calls (see test_handle_verify_pqc).
    mock_client.verify_digest.reset_mock()

    # 2. Execute Gate
    args = Namespace(run_id=pqc_env["run_id"], hash=None, verify_ledger=True, pqc=True)
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
