import json
from argparse import Namespace

import pytest

from eval_runner import config
from eval_runner.handlers import evaluation


def _make_finalization_event(
    run_id: str, scenario_id: str, events: list[str], outcome: str = "pass", score: float = 1.0
) -> str:
    """
    Build a valid EvaluatorFinalizationRecord event
    from a list of already-serialized JSONL lines.
    """
    import hashlib

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
    from agentv_runtime.canonical import canonical_json_encode

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
    run_id = "test_certification_run"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_dir / "run.jsonl"
    start_ev = json.dumps(
        {
            "event": "run_start",
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

    return {"root": root, "run_id": run_id, "trace_path": trace_path}


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

    sidecar_path = certify_env["trace_path"].parent / "run_manifest.json"
    with open(sidecar_path, encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest.get("behavioral_fingerprint_id") == fingerprint

    # Schema validation of sidecar manifest
    project_root = Path(__file__).parent.parent.parent.parent
    vc_schema_path = project_root / "spec" / "vc" / "vc.schema.json"
    assert vc_schema_path.exists()

    with open(vc_schema_path, encoding="utf-8") as sf:
        schema = json.load(sf)

    validate(instance=manifest, schema=schema)


@pytest.mark.asyncio
async def test_handle_certify_missing_trace(certify_env, capsys):
    """Test certify fails if trace file is missing."""
    # Passing a run-id that doesn't exist
    args = Namespace(run_id="non_existent", path=None, metadata=None, private_key=None)
    result = await evaluation.handle_certify(args)
    assert result == 1
    captured = capsys.readouterr()
    assert "Error: Trace file not found" in captured.out


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

    # Physical State Verification
    sidecar = certify_env["trace_path"].parent / "run_manifest.json"
    vault = config.REPORTS_DIR / "certificates" / f"{certify_env['run_id']}_vc.json"

    assert sidecar.exists(), "Sidecar manifest missing"
    assert vault.exists(), "Vault certificate missing"

    # Schema validation of generated VC in vault
    import json
    from pathlib import Path

    from jsonschema import validate

    project_root = Path(__file__).parent.parent.parent.parent
    vc_schema_path = project_root / "spec" / "vc" / "vc.schema.json"
    assert vc_schema_path.exists()

    with open(vc_schema_path, encoding="utf-8") as sf:
        schema = json.load(sf)

    with open(vault, encoding="utf-8") as vf:
        vc_data = json.load(vf)

    validate(instance=vc_data, schema=schema)
