"""Signing cannot adopt a chosen root that omits a non-finalization decision."""

import json
import re

import pytest

from agentv_runtime.evidence_graph import build_evidence_graph_from_events
from agentv_runtime.finalization import EvaluatorFinalizationRecord
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.verifier import EvidenceRootMismatchError, TraceVerifier, VerificationAuthority
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


def test_signing_rejects_root_that_omits_terminal_evidence(finalization_source, tmp_path):
    source, scenario = finalization_source
    events = source.get_events("run-a", offset=0, limit=100)
    original_finalization = events.pop()["data"]
    events[-1]["assertions"] = [
        {"oracle_id": "terminal-note", "passed": True, "event_seq": 3, "severity": "informational"}
    ]
    provider = LocalFileRunStore(tmp_path / "terminal-evidence")
    provider.create_run("run-a", scenario["id"])
    provider.append_events("run-a", events)
    provider.save_run_manifest("run-a", source.get_manifest("run-a"))
    lines = provider.get_trace_bytes("run-a").decode("utf-8").splitlines()
    pairs = [(json.loads(line), line) for line in lines]
    root = build_evidence_graph_from_events(pairs, required_oracle_ids=["oracle-1"])[
        "evidence_root_hash"
    ]
    omitted_root = build_evidence_graph_from_events(
        [(event, line) for event, line in pairs if event["event"] != "session_decision"],
        required_oracle_ids=["oracle-1"],
    )["evidence_root_hash"]
    assert root != omitted_root
    finalization = EvaluatorFinalizationRecord.from_dict(
        {**original_finalization, "evidence_root_hash": root}, require_authoritative=False
    ).sign()
    provider.append_events(
        "run-a", [{"event": "evaluator_finalization", "data": finalization.to_dict(), "_seq": 4}]
    )
    raw = provider.get_trace_bytes("run-a")
    from eval_runner.utils import crypto

    count = len([line for line in raw.splitlines() if line.strip()])
    provider.update_run_status(
        "run-a",
        "FINALIZING",
        details={
            "evidence_capture": {
                "complete": True,
                "event_count": count,
                "terminal_seq": count,
                "trace_hash": "sha3_256:" + crypto.checksum(raw),
            }
        },
    )
    manifest = provider.get_manifest("run-a")["execution_manifest"]

    def sign(claimed_root):
        return TraceVerifier.sign_trace_bytes(
            raw,
            run_id="run-a",
            run_store=provider,
            scenario_data=scenario,
            execution_manifest=manifest,
            metadata={"required_oracle_ids": ["oracle-1"]},
            execution_mode="live",
            evidence_root_hash=claimed_root,
        )

    certificate = sign(root)
    result = VerificationAuthority.verify_certification_artifact(
        certificate["verification_package"],
        raw_trace_bytes=raw,
        canonical_manifest=manifest,
        scenario_data=scenario,
    )
    assert result["certified"], result["failures"]
    expected_msg = (
        rf"EvidenceRootMismatch: declared={re.escape(omitted_root)} "
        rf"computed={re.escape(root)}"
    )
    with pytest.raises(EvidenceRootMismatchError, match=expected_msg):
        sign(omitted_root)
