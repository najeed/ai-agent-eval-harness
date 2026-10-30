"""Explicit oracle source references must identify existing provider evidence."""

import json

import pytest

from agentv_runtime.evidence_graph import build_evidence_graph_from_events
from agentv_runtime.finalization import EvaluatorFinalizationRecord
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.verifier import CertificationFailedError, TraceVerifier, VerificationAuthority
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize("location", ["event", "data"])
@pytest.mark.parametrize("reference", [2, 999])
def test_explicit_oracle_carrier_reference_requires_recorded_source(
    finalization_source, tmp_path, location, reference
):
    source, scenario = finalization_source
    events = source.get_events("run-a", offset=0, limit=100)
    old_finalization = events.pop()["data"]
    if location == "data":
        oracle = events[1]
        events[1] = {
            "event": oracle["event"],
            "_seq": oracle["_seq"],
            "data": {key: value for key, value in oracle.items() if key not in {"event", "_seq"}},
        }
        events[1]["data"]["event_seq"] = reference
    else:
        events[1]["event_seq"] = reference
    provider = LocalFileRunStore(tmp_path / "referenced-oracle")
    provider.create_run("run-a", scenario["id"])
    provider.append_events("run-a", events)
    provider.save_run_manifest("run-a", source.get_manifest("run-a"))
    lines = provider.get_trace_bytes("run-a").decode("utf-8").splitlines()
    graph = build_evidence_graph_from_events(
        [(json.loads(line), line) for line in lines], required_oracle_ids=["oracle-1"]
    )
    finalization = EvaluatorFinalizationRecord.from_dict(
        {**old_finalization, "evidence_root_hash": graph["evidence_root_hash"]},
        require_authoritative=False,
    ).sign()
    provider.append_events(
        "run-a", [{"event": "evaluator_finalization", "data": finalization.to_dict(), "_seq": 4}]
    )
    provider.update_run_status("run-a", "FINALIZING")
    raw = provider.get_trace_bytes("run-a")
    manifest = provider.get_manifest("run-a")["execution_manifest"]

    def sign():
        return TraceVerifier.sign_trace_bytes(
            raw,
            run_id="run-a",
            run_store=provider,
            scenario_data=scenario,
            execution_manifest=manifest,
            metadata={"required_oracle_ids": ["oracle-1"]},
            evidence_root_hash=finalization.evidence_root_hash,
            execution_mode="live",
        )

    if reference == 999:
        with pytest.raises(CertificationFailedError, match="UnboundOracleTraceCarrier"):
            sign()
        assert provider.get_run("run-a")["lifecycle"] != "SEALED"
        assert not provider.get_manifest("run-a").get("verification_package")
        return

    certificate = sign()
    result = VerificationAuthority.verify_certification_artifact(
        certificate["verification_package"],
        raw_trace_bytes=raw,
        canonical_manifest=manifest,
        scenario_data=scenario,
    )
    assert result["certified"], result["failures"]
