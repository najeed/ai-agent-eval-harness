"""Legacy manifest projections remain diagnostic and reject contradictory bindings."""

import hashlib

import pytest

from agentv_runtime.evidence_graph import build_evidence_graph_from_events
from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
from agentv_runtime.package import VerificationPackage
from eval_runner.verifier import VerificationAuthority


@pytest.mark.parametrize(
    ("binding", "expected_valid"), [("matching", True), ("omitted", True), ("altered", False)]
)
@pytest.mark.parametrize("entrypoint", ["verify_package", "verify_package_artifacts"])
@pytest.mark.parametrize("has_compliance", [False, True])
def test_legacy_manifest_projection_does_not_override_declared_binding(
    binding, expected_valid, entrypoint, has_compliance
):
    scenario = {"id": "scenario-a", "version": "1.0.0"}
    manifest = ExecutionManifest(
        manifest_id="manifest-a",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=compute_scenario_hash(scenario),
        created_at="2026-10-29T00:00:00Z",
        created_by="test",
    )
    projection = {
        key: value
        for key, value in manifest.to_dict().items()
        if key not in {"agent_config", "runtime_config", "environment"}
    }
    projection["vc_version"] = "3.0.0"
    if has_compliance:
        projection["compliance"] = {"status": "pass", "score": 1.0}
    trace = b'{"event":"run_start","_seq":1}\n'
    graph = build_evidence_graph_from_events(
        [({"event": "run_start", "_seq": 1}, trace.decode().rstrip("\n"))]
    )
    trace_hash = "sha3_256:" + hashlib.sha3_256(trace).hexdigest()
    package = VerificationPackage(
        scenario_id=manifest.scenario_id,
        scenario_version=manifest.scenario_version,
        scenario_hash=manifest.scenario_hash,
        manifest_id=manifest.manifest_id,
        manifest_hash={
            "matching": manifest.compute_manifest_hash(),
            "omitted": "",
            "altered": "sha3_256:" + "0" * 64,
        }[binding],
        execution_identity={"run_id": "run-a"},
        trace_hash=trace_hash,
        trace_seal={"trace_digest": trace_hash, "event_count": 1},
        evidence_root_hash=graph["evidence_root_hash"],
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
    )

    result = getattr(VerificationAuthority, entrypoint)(
        package,
        raw_trace_bytes=trace,
        canonical_manifest=projection,
        scenario_data=scenario,
        require_signature=False,
    )
    assert result["verified"] is expected_valid, result["failures"]
    assert result.get("authoritative", False) is False
    assert result.get("certified", False) is False
    if not expected_valid:
        assert any("ManifestHashMismatch" in failure for failure in result["failures"])
