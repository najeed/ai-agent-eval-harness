import json
from argparse import Namespace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.handlers import analysis, evaluation
from eval_runner.identity import IdentityService
from eval_runner.verifier import TraceVerifier


def _make_finalization_event(
    run_id: str,
    scenario_id: str,
    events: list[str],
    outcome: str = "pass",
    score: float = 1.0,
    run_dir: Any = None,
    exec_manifest: Any = None,
) -> str:
    """
    Build a valid EvaluatorFinalizationRecord event
    from a list of already-serialized JSONL lines.
    """
    import hashlib
    from pathlib import Path

    from agentv_runtime.evidence_graph import build_evidence_graph_from_events
    from agentv_runtime.finalization import EvaluatorFinalizationRecord
    from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash

    parsed: list[tuple[dict[str, Any], str]] = []
    for line in events:
        raw_line = line.rstrip("\r\n")
        if raw_line.strip():
            try:
                parsed.append((json.loads(raw_line), raw_line))
            except Exception:
                pass

    ev_graph = build_evidence_graph_from_events(parsed)
    evidence_root = ev_graph.get(
        "evidence_root_hash", f"sha3_256:{hashlib.sha3_256(b'empty').hexdigest()}"
    )

    scenario_data = {"id": scenario_id, "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scenario_data)
    if exec_manifest is None:
        exec_manifest = ExecutionManifest(
            manifest_id=f"man_{run_id}",
            scenario_id=scenario_id,
            scenario_version="1.0.0",
            scenario_hash=scen_hash,
        )
    exec_manifest_hash = exec_manifest.compute_manifest_hash()
    if run_dir is not None:
        (Path(run_dir) / "execution_manifest.json").write_text(
            json.dumps(exec_manifest.to_dict()), encoding="utf-8"
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
    rec = rec.sign()
    fin_dict = rec.to_dict()
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

    from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "pqc_test_run"
    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id=run_id, scenario_id="test_scenario")

    scenario_data = {"id": "test_scenario", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scenario_data)
    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="test_scenario",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
    )
    store.save_run_manifest(
        run_id,
        {
            "execution_manifest": exec_manifest.to_dict(),
            "scenario_data": scenario_data,
        },
    )

    start_ev = {
        "event": "run_start",
        "run_id": "pqc_test_run",
        "scenario_id": "test_scenario",
        "scenario_data": {"id": "test_scenario", "version": "1.0.0"},
        "data": {"execution_mode": "live", "execution_mode_declared": True},
    }
    assert_ev = {"event": "assertion_evaluated", "assertion": "accuracy", "passed": True}
    metrics_ev = {"event": "summary_metrics", "metrics": {"success_rate": 1.0}}
    end_ev = {"event": "run_end", "outcome": "pass", "status": "pass", "score": 1.0}

    core_events = [start_ev, assert_ev, metrics_ev, end_ev]
    store.append_events(run_id, core_events)

    trace_file = runs_dir / run_id / "run.jsonl"
    raw_lines = [
        line for line in trace_file.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    fin_ev_str = _make_finalization_event(
        run_id, "test_scenario", raw_lines, exec_manifest=exec_manifest
    )
    store.append_events(run_id, [json.loads(fin_ev_str)])

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
    from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash

    IdentityService._provision_local_identity(identity_id)
    store.create_run(run_id=run_id, scenario_id="test_scenario")

    scenario_data = {"id": "test_scenario", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scenario_data)
    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="test_scenario",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
    )

    start_ev = {
        "event": "run_start",
        "run_id": run_id,
        "scenario_id": "test_scenario",
        "scenario_data": scenario_data,
        "data": {"execution_mode": "live", "execution_mode_declared": True},
    }
    assert_ev = {"event": "assertion_evaluated", "assertion": "accuracy", "passed": True}
    metrics_ev = {"event": "summary_metrics", "metrics": {"success_rate": 1.0}}
    end_ev = {"event": "run_end", "outcome": "pass", "status": "pass", "score": 1.0}

    core_events_str = [
        json.dumps(start_ev),
        json.dumps(assert_ev),
        json.dumps(metrics_ev),
        json.dumps(end_ev),
    ]
    fin_ev_str = _make_finalization_event(
        run_id, "test_scenario", core_events_str, exec_manifest=exec_manifest
    )
    all_events = [start_ev, assert_ev, metrics_ev, end_ev, json.loads(fin_ev_str)]
    store.append_events(run_id, all_events)

    trace_bytes = store.get_trace_bytes(run_id)
    assert trace_bytes is not None

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        identity_id=identity_id,
        provisional=True,
    )
    store.save_run_manifest(run_id, manifest)
    store.update_run_status(run_id, "SEALED")
    return manifest


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
