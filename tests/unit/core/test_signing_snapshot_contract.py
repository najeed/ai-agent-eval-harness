"""Explicit signing snapshots cannot be replaced by stale metadata projections."""

from copy import deepcopy

import pytest

from eval_runner.verifier import TraceVerifier, VerificationAuthority
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize("explicit_snapshot", [False, True])
@pytest.mark.parametrize("root_hint", [False, True])
def test_signing_preserves_explicit_snapshot_or_resolves_provider_fallback(
    finalization_source, explicit_snapshot, root_hint
):
    provider, scenario = finalization_source
    execution_manifest = provider.get_manifest("run-a")["execution_manifest"]
    trace = provider.get_trace_bytes("run-a")
    finalization = provider.get_events("run-a", offset=0, limit=100)[-1]["data"]

    class MetadataView:
        def get_trace_bytes(self, run_id, context=None):
            return provider.get_trace_bytes(run_id, context=context)

        def get_run(self, run_id, context=None):
            return provider.get_run(run_id, context=context)

        def get_manifest(self, run_id, context=None):
            projection = deepcopy(provider.get_manifest(run_id, context=context))
            if explicit_snapshot:
                projection["scenario_data"]["description"] = "stale metadata projection"
                projection["execution_manifest"]["metadata"]["projection_revision"] = "stale"
            return projection

    snapshot = (
        {"scenario_data": scenario, "execution_manifest": execution_manifest}
        if explicit_snapshot
        else {}
    )
    if root_hint:
        snapshot["evidence_root_hash"] = finalization["evidence_root_hash"]
    certificate = TraceVerifier.sign_trace_bytes(
        trace,
        run_id="run-a",
        run_store=MetadataView(),
        metadata={"required_oracle_ids": ["oracle-1"]},
        execution_mode="live",
        **snapshot,
    )
    assert certificate["scenario_data"] == scenario
    assert certificate["execution_manifest"] == execution_manifest
    result = VerificationAuthority.verify_certification_artifact(
        certificate["verification_package"],
        raw_trace_bytes=trace,
        canonical_manifest=execution_manifest,
        scenario_data=scenario,
    )
    assert result["verified"], result["failures"]


@pytest.mark.parametrize("missing_field", ["scenario_data", "execution_manifest"])
@pytest.mark.parametrize("replacement", [None, {}, [], "absent"])
def test_invalid_provider_snapshot_fallback_cannot_authorize(
    finalization_source, missing_field, replacement
):
    provider, scenario = finalization_source
    physical = provider.get_manifest("run-a")
    execution_manifest = physical["execution_manifest"]
    finalization = provider.get_events("run-a", offset=0, limit=100)[-1]["data"]
    trace = provider.get_trace_bytes("run-a")

    class MetadataView:
        def get_trace_bytes(self, run_id, context=None):
            return provider.get_trace_bytes(run_id, context=context)

        def get_run(self, run_id, context=None):
            return provider.get_run(run_id, context=context)

        def get_manifest(self, run_id, context=None):
            projection = deepcopy(provider.get_manifest(run_id, context=context))
            if replacement == "absent":
                projection.pop(missing_field, None)
            else:
                projection[missing_field] = replacement
            return projection

    arguments = {"scenario_data": scenario, "execution_manifest": execution_manifest}
    arguments.pop(missing_field)
    try:
        certificate = TraceVerifier.sign_trace_bytes(
            trace,
            run_id="run-a",
            run_store=MetadataView(),
            metadata={"required_oracle_ids": ["oracle-1"]},
            evidence_root_hash=finalization["evidence_root_hash"],
            execution_mode="live",
            **arguments,
        )
    except (ValueError, TypeError):
        pass
    else:
        result = VerificationAuthority.verify_certification_artifact(
            certificate["verification_package"],
            raw_trace_bytes=trace,
            canonical_manifest=execution_manifest
            if missing_field != "execution_manifest"
            else None,
            scenario_data=scenario if missing_field != "scenario_data" else None,
        )
        assert result["verified"] is False, result
        assert result["certified"] is False, result
    assert provider.get_run("run-a")["lifecycle"] != "SEALED"
