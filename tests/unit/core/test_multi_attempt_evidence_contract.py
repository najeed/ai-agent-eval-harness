"""Repeated oracle IDs bind to distinct provider-owned execution events."""

import pytest

from agentv_runtime.evidence_graph import build_evidence_graph_from_events, hash_source_line
from agentv_runtime.finalization import EvaluatorFinalizationRecord
from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
from eval_runner.services.certification import execute_industrial_certification
from eval_runner.verifier import TraceVerifier
from tests.unit.core.test_certification_service_and_trust_boundary import provider as provider


@pytest.mark.parametrize(
    ("second_outcome", "duplicate_first", "phantom_second"),
    [("PASS", False, False), ("FAIL", False, False), ("PASS", True, False), ("PASS", False, True)],
)
def test_multiple_attempts_preserve_oracle_identity_and_duplicate_rejection(
    provider, second_outcome, duplicate_first, phantom_second
):
    run_id = "multi-attempt"
    scenario = {"id": "scenario-multi", "version": "1.0.0", "required_oracles": ["oracle-1"]}
    manifest = ExecutionManifest(
        manifest_id="manifest-multi",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=compute_scenario_hash(scenario),
        metadata={"required_oracle_ids": ["oracle-1"]},
        runtime_config={"execution_mode": "live", "required_oracle_ids": ["oracle-1"]},
    )
    events = [{"event": "run_start", "_seq": 1, "execution_mode": "live"}]
    for attempt, outcome in enumerate(["PASS", second_outcome], start=1):
        oracle = {
            "oracle_id": "oracle-1",
            "scenario_node_id": "node",
            "resolver": "fixture",
            "requiredness": "REQUIRED",
            "outcome": outcome,
        }
        events.append(
            {
                "event": "agent_response"
                if attempt == 2 and phantom_second
                else "execution_graph_node",
                "_seq": attempt + 1,
                "data": {
                    "node_id": "node",
                    "attempt": attempt,
                    "attempt_id": f"attempt-{attempt}",
                    "execution_instance_id": f"node:attempt:{attempt}",
                    "oracle_results": [oracle, dict(oracle)]
                    if attempt == 1 and duplicate_first
                    else [oracle],
                },
            }
        )
    passing = second_outcome == "PASS"
    events.append(
        {"event": "session_decision", "_seq": 4, "decision": "PASS" if passing else "FAIL"}
    )
    provider.create_run(run_id, scenario["id"])
    provider.append_events(run_id, events)
    lines = provider.get_trace_bytes(run_id).decode().splitlines()
    graph = build_evidence_graph_from_events(
        list(zip(events, lines, strict=True)), required_oracle_ids=["oracle-1"]
    )
    finalization = EvaluatorFinalizationRecord(
        finalization_id="finalization-multi",
        run_id=run_id,
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=manifest.scenario_hash,
        execution_manifest_hash=manifest.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:evaluator-config",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["oracle-1"],
        evidence_root_hash=graph["evidence_root_hash"],
        outcome="pass" if passing else "fail",
        score=1.0 if passing else 0.0,
        terminal_seq=4,
        finalized_at="2026-10-29T00:00:00Z",
    ).sign()
    provider.append_events(
        run_id, [{"event": "evaluator_finalization", "_seq": 5, "data": finalization.to_dict()}]
    )
    provider.save_run_manifest(
        run_id,
        {"run_id": run_id, "execution_manifest": manifest.to_dict(), "scenario_data": scenario},
    )

    if duplicate_first or phantom_second:
        failure = "DuplicateOracleId" if duplicate_first else "UngroundedPackagedOracle"
        with pytest.raises(Exception, match=failure):
            execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)
        assert provider.get_run(run_id)["lifecycle"] != "SEALED"
        return

    issued = execute_industrial_certification(run_id, run_store=provider, scenario_data=scenario)
    package = provider.get_manifest(run_id)["verification_package"]
    rows = package["executed_oracle_results"]
    assert len(rows) == 2
    assert {row["sequence"] for row in rows} == {2, 3}
    source_hashes = {
        event["_seq"]: hash_source_line(line) for event, line in zip(events, lines, strict=True)
    }
    for row in rows:
        assert row["source_hash"] == source_hashes[row["sequence"]]
    assert len({row["source_hash"] for row in rows}) == 2
    result = TraceVerifier.verify_run(run_id, run_store=provider)
    assert result["is_valid"] is True
    assert result["verified"] is passing
    assert issued["certified"] is passing
