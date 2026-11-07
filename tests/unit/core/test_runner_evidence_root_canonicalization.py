from unittest.mock import patch

import pytest

from agentv_runtime.canonical import canonical_json_dumps
from agentv_runtime.evidence_graph import build_evidence_graph_from_events
from eval_runner.events import emit
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.runner import DefaultRunner
from eval_runner.services.certification import CertificationService


@pytest.mark.asyncio
async def test_runner_canonical_serialization_and_exact_physical_bytes_evidence_root(
    tmp_path, monkeypatch
):
    """
    [Request 9 P0] EvaluationKernel derivation of evidence root hash must:
    1. Prefer exact raw physical trace bytes from get_trace_bytes when available.
    2. Fall back to RFC 8785 canonical_json_dumps when reconstructing from get_events().
    3. Ensure evidence root hash matches verifier and certifier computation.
    4. Certify cleanly via execute_industrial_certification without EvidenceRootMismatch.
    """
    monkeypatch.setenv("AES_CERTIFICATION_MODE", "1")
    store = LocalFileRunStore(tmp_path / "runs")
    runner = DefaultRunner(run_store=store)

    run_id = "test-req9-canonical-root"

    scenario = {
        "id": "scen-req9",
        "metadata": {"execution_mode": "live"},
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "task_description": "task 1",
                    "expected_outcome": [
                        {"type": "typed_value", "value": "approved", "target": "message"}
                    ],
                }
            ]
        },
    }

    async def mock_execute(max_tasks, **kwargs):
        # Emit assertion event with multiple intentionally unsorted keys
        emit(
            "assertion_evaluated",
            {
                "run_id": run_id,
                "target": "policy:check",
                "zebra": "last",
                "alpha": "first",
                "mode": "exact",
                "expected": "approved",
                "actual": "approved",
                "passed": True,
            },
        )
        return [{"workflow_verdict": {"status": "COMPLETED"}}]

    # 1. Run evaluation with exact physical bytes
    with patch(
        "eval_runner.session.SessionManager.execute_tasks",
        side_effect=mock_execute,
    ):
        res = await runner.run(
            scenario, run_id=run_id, metadata={"execution_mode": "live", "uncertifiable": False}
        )
        assert res is not None

        # Verify certification service certifies without EvidenceRootMismatch
        cert_res = CertificationService.execute_industrial_certification(
            run_id,
            run_store=store,
            scenario_data=scenario,
        )
        assert cert_res is not None
        assert cert_res.get("manifest") is not None
        assert cert_res["manifest"].get("evidence_root_hash") is not None

    # 2. Verify fallback path: when get_trace_bytes returns None, canonical_json_dumps is used
    run_id_fallback = "test-req9-canonical-fallback"

    async def mock_execute_fallback(max_tasks, **kwargs):
        emit(
            "assertion_evaluated",
            {
                "run_id": run_id_fallback,
                "target": "policy:check",
                "zebra": "last",
                "alpha": "first",
                "mode": "exact",
                "expected": "approved",
                "actual": "approved",
                "passed": True,
            },
        )
        return [{"workflow_verdict": {"status": "COMPLETED"}}]

    orig_get_trace_bytes = store.get_trace_bytes
    trace_calls = []

    def mock_get_trace_bytes(r_id, **kwargs):
        trace_calls.append(r_id)
        if len(trace_calls) == 1:
            # First call is from runner.py line 1318 to exercise the canonical_json_dumps fallback
            return None
        return orig_get_trace_bytes(r_id, **kwargs)

    with patch.object(store, "get_trace_bytes", side_effect=mock_get_trace_bytes):
        with patch(
            "eval_runner.session.SessionManager.execute_tasks",
            side_effect=mock_execute_fallback,
        ):
            res2 = await runner.run(
                scenario,
                run_id=run_id_fallback,
                metadata={"execution_mode": "live", "uncertifiable": False},
            )
            assert res2 is not None

            # Verify that fallback derived the evidence root using canonical serialization
            events_fallback = store.get_events(run_id_fallback, offset=0, limit=10_000_000)
            fin = next(
                e for e in events_fallback if e.get("finalization") or e.get("event") == "run_end"
            )
            fin_record = fin.get("finalization") or fin.get("data", {}).get("finalization")
            assert fin_record is not None

            # Compute expected evidence root hash independently using canonical_json_dumps
            fallback_lines = [
                (e, canonical_json_dumps(e))
                for e in events_fallback
                if e.get("_seq", 0) <= fin_record["terminal_seq"]
            ]
            expected_fallback_graph = build_evidence_graph_from_events(
                fallback_lines, required_oracle_ids=set()
            )
            assert fin_record["evidence_root_hash"] == expected_fallback_graph["evidence_root_hash"]
