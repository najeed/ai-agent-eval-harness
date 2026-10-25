import json
from argparse import Namespace
from typing import Any

import pytest

from eval_runner.handlers import evaluation


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
    from pathlib import Path

    from agentv_runtime.evidence_graph import (
        build_evidence_graph_from_events,
        compute_evidence_graph_root,
    )
    from agentv_runtime.finalization import EvaluatorFinalizationRecord
    from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash

    raw_events = []
    for line in events:
        line = line.strip()
        if line:
            try:
                raw_events.append((json.loads(line), line))
            except Exception:
                pass

    ev_graph = build_evidence_graph_from_events(raw_events)
    evidence_root = (
        ev_graph.get("evidence_root_hash")
        or ev_graph.get("root_hash")
        or compute_evidence_graph_root(ev_graph)
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
        terminal_seq=raw_events[-1][0].get("_seq", len(raw_events)) if raw_events else 1,
    )
    rec = rec.sign()
    fin_dict = rec.to_dict()
    return json.dumps({"event": "evaluator_finalization", "data": fin_dict})


@pytest.fixture
def certify_env(tmp_path, monkeypatch):
    """
    Creates a physical context for certification testing.
    Standardized for Zero-Mock verification.
    """
    root = tmp_path / "root"
    root.mkdir()

    # Configure industrial paths
    runs_dir = root / "runs"
    runs_dir.mkdir()
    reports_dir = root / "reports"
    reports_dir.mkdir()
    (reports_dir / "certificates").mkdir()

    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", reports_dir)
    monkeypatch.setattr("eval_runner.config.TRUST_ROOT", root / ".aes" / "keys")

    # Certification is fail-closed: provision the signing identity
    # so the transactional pipeline can actually sign.
    from eval_runner.identity import IdentityService

    IdentityService._provision_local_identity("system_id")

    # Authoritative Eval Artifact
    from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "test_certification_run"
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

    from agentv_runtime.canonical import canonical_json_dumps

    start_ev = {
        "_seq": 1,
        "event": "run_start",
        "scenario_id": "test_scenario",
        "scenario_data": {"id": "test_scenario", "version": "1.0.0"},
        "data": {"execution_mode": "live", "execution_mode_declared": True},
    }
    assert_ev = {"_seq": 2, "event": "assertion_evaluated", "assertion": "accuracy", "passed": True}
    metrics_ev = {"_seq": 3, "event": "summary_metrics", "metrics": {"success_rate": 1.0}}
    end_ev = {"_seq": 4, "event": "run_end", "outcome": "pass", "status": "pass", "score": 1.0}

    core_events = [start_ev, assert_ev, metrics_ev, end_ev]
    core_events_str = [canonical_json_dumps(e) for e in core_events]
    fin_ev_str = _make_finalization_event(
        run_id, "test_scenario", core_events_str, exec_manifest=exec_manifest
    )
    fin_dict = json.loads(fin_ev_str)
    fin_dict["_seq"] = 5
    all_events = core_events + [fin_dict]
    store.append_events(run_id, all_events)

    return {
        "root": root,
        "run_id": run_id,
        "store": store,
        "trace_path": runs_dir / run_id / "run.jsonl",
    }


@pytest.mark.asyncio
async def test_handle_certify_with_fingerprint(certify_env, capsys):
    """Verify Pillar 2: Behavioral Fingerprint persistence and VC schema compliance."""
    fingerprint = "industrial_v1_baseline"
    args = Namespace(
        run_id=certify_env["run_id"],
        path=None,
        metadata=None,
        private_key=None,
        fingerprint=fingerprint,
        identity="system_id",
        status="pass",
        score=1.0,
        policy_ref="NIST-800-53",
        ttl=30,
    )

    result = await evaluation.handle_certify(args)
    assert result == 0

    # Verify Physical Manifest Content
    import json
    from pathlib import Path

    from jsonschema import validate

    sidecar = certify_env["store"].get_manifest(certify_env["run_id"])
    assert sidecar is not None
    assert sidecar.get("behavioral_fingerprint_id") == fingerprint

    # Schema validation of sidecar manifest
    project_root = Path(__file__).parent.parent.parent.parent
    vc_schema_path = project_root / "spec" / "vc" / "vc.schema.json"
    assert vc_schema_path.exists()

    with open(vc_schema_path, encoding="utf-8") as sf:
        schema = json.load(sf)

    validate(instance=sidecar, schema=schema)


@pytest.mark.asyncio
async def test_handle_certify_missing_trace(certify_env, capsys):
    """Test certify fails if trace file is missing."""
    # Passing a run-id that doesn't exist
    args = Namespace(run_id="non_existent", path=None, metadata=None, private_key=None)
    result = await evaluation.handle_certify(args)
    assert result == 1
    captured = capsys.readouterr()
    assert any(
        msg in captured.out
        for msg in ("ProviderOwnedEvidenceRequired", "not found", "Trace bytes not returned")
    )


@pytest.mark.asyncio
async def test_handle_certify_success(certify_env, capsys):
    """Test certify succeeds and creates a physical manifest."""
    # Use the established run-id
    args = Namespace(
        run_id=certify_env["run_id"],
        path=None,
        metadata=None,
        private_key=None,
        identity="system_id",
        status="pass",
        score=1.0,
        policy_ref="NIST-800-53",
        ttl=30,
    )

    result = await evaluation.handle_certify(args)
    assert result == 0

    captured = capsys.readouterr()
    assert "Success: Verification Certificate generated" in captured.out
    assert f"Run ID: {certify_env['run_id']}" in captured.out

    # Provider Manifest State Verification
    manifest = certify_env["store"].get_manifest(certify_env["run_id"])
    assert manifest is not None, "Provider manifest missing"
    assert manifest.get("vc_version") == "3.0.0"

    # Schema validation of generated VC in manifest
    import json
    from pathlib import Path

    from jsonschema import validate

    project_root = Path(__file__).parent.parent.parent.parent
    vc_schema_path = project_root / "spec" / "vc" / "vc.schema.json"
    assert vc_schema_path.exists()

    with open(vc_schema_path, encoding="utf-8") as sf:
        schema = json.load(sf)

    validate(instance=manifest, schema=schema)


def test_sign_trace_unconditional_finalization_mandate(tmp_path, monkeypatch):
    """
    P0 Certification Completeness Sentinel:
    Non-provisional certification unconditionally requires EvaluatorFinalizationRecord.
    Caller discretion via require_finalization=False cannot bypass it.
    Only explicit provisional=True permits non-certifying diagnostic signing.
    """
    from eval_runner.identity import IdentityService
    from eval_runner.verifier import TraceVerifier

    root = tmp_path / "finalization_mandate_test"
    root.mkdir()
    runs_dir = root / "runs"
    runs_dir.mkdir()
    reports_dir = root / "reports"
    reports_dir.mkdir()
    (reports_dir / "certificates").mkdir()

    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", reports_dir)
    monkeypatch.setattr("eval_runner.config.TRUST_ROOT", root / ".aes" / "keys")
    IdentityService._provision_local_identity("system_id")

    from eval_runner.reference.local_run_store import LocalFileRunStore
    from eval_runner.services.certification import execute_industrial_certification

    run_id = "run-mandate-test"
    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id=run_id, scenario_id="test_scenario")
    # Bare trace without EvaluatorFinalizationRecord
    events = [
        {
            "event": "run_start",
            "run_id": run_id,
            "data": {"execution_mode": "live", "execution_mode_declared": True},
        },
        {"event": "run_end", "run_id": run_id, "status": "pass"},
    ]
    store.append_events(run_id, events)
    trace_bytes = store.get_trace_bytes(run_id)
    assert trace_bytes is not None

    # 1. Non-provisional certification requires EvaluatorFinalizationRecord -> FAILS
    with pytest.raises(
        ValueError,
        match="(MissingEvaluatorFinalization|missing mandatory "
        "authoritative EvaluatorFinalizationRecord)",
    ):
        execute_industrial_certification(
            run_id=run_id,
            run_store=store,
            scenario_data={"id": "test_scenario", "version": "1.0.0"},
        )

    # 2. Explicit provisional=True (non-certifying diagnostic) -> ALLOWED
    diag_res = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        execution_mode="live",
        provisional=True,
    )
    assert diag_res is not None
    assert diag_res.get("provisional") is True
