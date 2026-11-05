import pytest

from agentv_runtime.evidence_graph import build_evidence_graph_from_events
from eval_runner.events import CoreEvents
from eval_runner.mutator_plugin import RuntimeMutationPlugin
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.runner import DefaultRunner
from eval_runner.services.certification import CertificationService
from eval_runner.session import SessionManager


@pytest.mark.asyncio
async def test_security_preflight_rejection_emits_running_and_failed_evidence(
    tmp_path, monkeypatch
):
    """
    [Request 10 P1] Security preflight and authorization mutations must emit:
    1. EXECUTION_GRAPH_NODE (status: 'running') registered before boundary interception.
    2. Synthesized authoritative Security Oracle Failure with typed OracleResult.
    3. Terminal EXECUTION_GRAPH_NODE with status 'failed', failure_class, and oracle_results.
    4. ASSERTION_EVALUATED event on the physical trace.
    """
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    store = LocalFileRunStore(tmp_path / "runs")
    run_id = "test-preflight-evidence-001"

    scenario = {
        "id": "scen-security-stale",
        "failure_policy": "fail_fast",
        "metadata": {"execution_mode": "live"},
        "workflow": {
            "nodes": [
                {
                    "id": "review_task_1",
                    "task_description": "Physician HITL Review Task",
                    "approval_token": "EXPIRED_SIG_1970",
                    "expected_outcome": [{"type": "typed_value", "value": "approved"}],
                }
            ]
        },
    }

    from eval_runner.flight_recorder import FlightRecorderPlugin

    FlightRecorderPlugin.bind_active_recorder(run_id, store)

    session = SessionManager(
        run_id=run_id,
        scenario=scenario,
        run_store=store,
    )

    # Register MutatorPlugin to intercept preflight
    mutator = RuntimeMutationPlugin(scenario)
    session.plugin_manager.register(mutator)

    emitted: list[tuple[str, dict]] = []
    session.event_bus.subscribe(lambda e: emitted.append((e.name, e.data)))

    # Execute tasks; preflight must reject
    results = await session.execute_tasks(attempt_number=1)
    assert results is not None
    assert len(results) >= 1

    # 1. Verify EXECUTION_GRAPH_NODE (status: 'running') was emitted
    running_nodes = [
        data
        for name, data in emitted
        if name == CoreEvents.EXECUTION_GRAPH_NODE and data.get("status") == "running"
    ]
    assert len(running_nodes) >= 1
    assert running_nodes[0]["scenario_node_id"] == "review_task_1"

    # 2. Verify ASSERTION_EVALUATED event was emitted with typed outcome FAIL
    assertions = [data for name, data in emitted if name == CoreEvents.ASSERTION_EVALUATED]
    assert len(assertions) >= 1
    assert assertions[0]["oracle_id"] == "security:approval_stale"
    assert assertions[0]["outcome"] == "FAIL"
    assert assertions[0]["passed"] is False

    # 3. Verify terminal EXECUTION_GRAPH_NODE was emitted with status 'failed' and oracle_results
    failed_nodes = [
        data
        for name, data in emitted
        if name == CoreEvents.EXECUTION_GRAPH_NODE and data.get("status") == "failed"
    ]
    assert len(failed_nodes) >= 1
    failed_node = failed_nodes[0]
    assert failed_node["scenario_node_id"] == "review_task_1"
    assert failed_node["failure_class"] == "APPROVAL_SECURITY_REJECTED"
    assert "oracle_results" in failed_node
    assert any(
        o.get("oracle_id") == "security:approval_stale" and o.get("outcome") == "FAIL"
        for o in failed_node["oracle_results"]
    )


@pytest.mark.asyncio
async def test_security_preflight_rejection_trace_attestation_in_trust_center(
    tmp_path, monkeypatch
):
    """
    [Request 10 Acceptance Criteria]
    Mutated runs rejected at preflight (e.g. approval_stale):
    1. Record at least one failed security assertion in their trace.
    2. Evidence graph produces total_nodes >= 1.
    3. The resulting trace can be cryptographically attested as a failure
       (Attest Evaluation Failure / Non-Certification) in Trust Center without
       raising DecisionOnlyTrace.
    """
    monkeypatch.setenv("AES_CERTIFICATION_MODE", "1")
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    store = LocalFileRunStore(tmp_path / "runs")
    runner = DefaultRunner(run_store=store)
    run_id = "test-preflight-attestation-002"

    scenario = {
        "id": "scen-security-rejection-attestation",
        "failure_policy": "fail_fast",
        "metadata": {
            "execution_mode": "live",
            "uncertifiable": False,
        },
        "workflow": {
            "nodes": [
                {
                    "id": "critical_payment_approval",
                    "task_description": "High Value Transfer Review",
                    "approval_token": "EXPIRED_SIG_1970",
                    "expected_outcome": [{"type": "typed_value", "value": "approved"}],
                }
            ]
        },
    }

    # Execute evaluation via runner
    eval_res = await runner.run(
        scenario,
        run_id=run_id,
        metadata={"execution_mode": "live", "uncertifiable": False},
    )
    assert eval_res is not None

    # Verify physical trace bytes directly
    trace_bytes = store.get_trace_bytes(run_id)
    assert trace_bytes is not None

    trace_events = [
        (json_rec, line)
        for line in trace_bytes.decode("utf-8").splitlines()
        if line.strip()
        for json_rec in [__import__("json").loads(line)]
    ]

    # Verify evidence graph has total_nodes >= 1
    ev_graph = build_evidence_graph_from_events(trace_events)
    assert ev_graph["total_nodes"] >= 1
    assert any(
        n.get("oracle_id") == "security:approval_stale" and n.get("outcome") == "FAIL"
        for n in ev_graph["nodes"]
    )

    # Issue Attestation of Non-Certification / Failure Certificate via Trust Center service
    cert_res = CertificationService.execute_industrial_certification(
        run_id=run_id,
        run_store=store,
        scenario_data=scenario,
    )

    assert cert_res is not None
    assert cert_res["status"] == "attested_failed"
    assert cert_res["compliance_status"] == "fail"
    assert cert_res["manifest"]["compliance"]["status"] == "fail"
    assert cert_res["manifest"]["verification_package"] is not None


@pytest.mark.asyncio
async def test_fail_fast_multi_node_dag_missing_downstream_oracles_attests_failure(
    tmp_path, monkeypatch
):
    """
    [Request 11 P1] Multi-node DAG under fail_fast:
    When an early node fails or is rejected, downstream nodes and their required
    oracles are never executed.
    1. CertificationService must NOT raise MissingRequiredOracles when certifying/attesting
       a declared failure (outcome == 'fail').
    2. A positive certification (outcome == 'pass') with missing required oracles must still
       strictly raise MissingRequiredOracles.
    """
    monkeypatch.setenv("AES_CERTIFICATION_MODE", "1")
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    store = LocalFileRunStore(tmp_path / "runs")
    runner = DefaultRunner(run_store=store)
    run_id = "test-multi-node-fail-fast-003"

    scenario = {
        "id": "scen-multi-node-fail-fast",
        "failure_policy": "fail_fast",
        "metadata": {
            "execution_mode": "live",
            "uncertifiable": False,
        },
        "workflow": {
            "nodes": [
                {
                    "id": "node_1_preflight",
                    "task_description": "Initial Security Boundary",
                    "approval_token": "EXPIRED_SIG_1970",
                    "expected_outcome": [{"type": "typed_value", "value": "approved"}],
                },
                {
                    "id": "node_2_downstream_clinical_review",
                    "task_description": "Downstream Clinical Review",
                    "required_oracles": ["licensed_physician", "physician_disposition"],
                    "expected_outcome": [{"type": "typed_value", "value": "approved"}],
                },
                {
                    "id": "node_3_downstream_notification",
                    "task_description": "Downstream Provider Notification",
                    "required_oracles": [
                        "provider_notification_status",
                        "review_request_completed",
                    ],
                    "expected_outcome": [{"type": "typed_value", "value": "notified"}],
                },
            ]
        },
    }

    # Execute evaluation via runner - will halt after node_1_preflight fails
    eval_res = await runner.run(
        scenario,
        run_id=run_id,
        metadata={"execution_mode": "live", "uncertifiable": False},
    )
    assert eval_res is not None

    # Issue Attestation of Non-Certification in Trust Center
    # Node 2 and Node 3 oracles were never executed. This MUST succeed and record the failure.
    cert_res = CertificationService.execute_industrial_certification(
        run_id=run_id,
        run_store=store,
        scenario_data=scenario,
    )

    assert cert_res is not None
    assert cert_res["status"] == "attested_failed"
    assert cert_res["compliance_status"] == "fail"
    assert cert_res["manifest"]["compliance"]["status"] == "fail"
