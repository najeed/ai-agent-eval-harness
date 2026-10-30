"""Metadata digest hints cannot substitute for actual scenario or manifest evidence."""

from copy import deepcopy

import pytest

from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
from eval_runner.verifier import TraceVerifier, VerificationAuthority
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize("artifact", ["scenario", "manifest"])
@pytest.mark.parametrize("hint", [False, True])
@pytest.mark.parametrize("evidence", ["actual", "omitted", "altered"])
def test_actual_artifact_required_even_with_matching_metadata_hash(
    finalization_source, artifact, hint, evidence
):
    provider, scenario = finalization_source
    manifest = provider.get_manifest("run-a")["execution_manifest"]
    raw = provider.get_trace_bytes("run-a")
    finalization = provider.get_events("run-a", offset=0, limit=100)[-1]["data"]
    metadata = {"required_oracle_ids": ["oracle-1"]}
    if hint:
        metadata["scenario_hash"] = compute_scenario_hash(scenario)
        metadata["execution_manifest_hash"] = ExecutionManifest.from_dict(
            manifest
        ).compute_manifest_hash()
    certificate = TraceVerifier.sign_trace_bytes(
        raw,
        run_id="run-a",
        run_store=provider,
        scenario_data=scenario,
        execution_manifest=manifest,
        metadata=metadata,
        execution_mode="live",
        evidence_root_hash=finalization["evidence_root_hash"],
    )
    actual_scenario = deepcopy(scenario)
    actual_manifest = deepcopy(manifest)
    if evidence == "omitted":
        if artifact == "scenario":
            actual_scenario = None
        else:
            actual_manifest = None
    elif evidence == "altered":
        if artifact == "scenario":
            actual_scenario["version"] = "unrecorded-version"
        else:
            actual_manifest["runtime_config"]["unrecorded_configuration"] = True
    result = VerificationAuthority.verify_certification_artifact(
        certificate["verification_package"],
        raw_trace_bytes=raw,
        scenario_data=actual_scenario,
        canonical_manifest=actual_manifest,
    )
    assert result["certified"] is (evidence == "actual"), result["failures"]
    if evidence != "actual":
        assert result["verified"] is False
