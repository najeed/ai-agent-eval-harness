from unittest.mock import patch

from eval_runner.taxonomy import CausalChain, DiagnosticResult, FailureCategory, FailureTaxonomy


def test_causal_chain_add():
    """Verify that causal chain correctly records structured forensic triggers."""
    chain = CausalChain()
    chain.add(FailureCategory.LOGIC_STALL, "Agent stuck in loop", turn_index=5, severity="high")

    assert len(chain) == 1
    assert chain[0]["trigger"] == FailureCategory.LOGIC_STALL
    assert chain[0]["evidence"] == "Agent stuck in loop"
    assert chain[0]["severity"] == "high"
    assert "timestamp" in chain[0]


def test_diagnostic_result_fallback_diagnosis():
    """Verify diagnostic fallback logic for historical auditability."""
    history = [
        {"role": "user", "content": "hello"},
        {"role": "agent", "content": "I am an agent"},
        {"role": "environment", "content": "error"},
    ]
    diag = DiagnosticResult(FailureCategory.LOGIC_STALL, FailureCategory.UNKNOWN_FAILURE)
    fallback = diag._fallback_diagnosis(history)

    # Should point to last agent index (index 1)
    assert fallback["index"] == 1
    assert fallback["root_cause"] == "logic_stall"


def test_classify_from_events_tool_results():
    """Verify failure classification from raw telemetry events (tool results)."""
    events = [
        {"event": "run_start", "scenario": "test"},
        {"event": "agent_response", "content": "I call a tool"},
        {
            "event": "tool_result",
            "identity": "system_id",
            "status": "error",
            "result": "Docker socket not found",
        },
    ]

    cat = FailureTaxonomy.classify_from_events(events)
    # Identity 'system_id' + error containing 'docker' -> INFRA_SANDBOX_FAILURE
    assert cat == FailureCategory.INFRA_SANDBOX_FAILURE


def test_check_environment_granular_mapping():
    """Verify granular infrastructure error mapping."""
    # OOM
    hist_oom = [{"identity": "env_id", "content": {"status": "error", "message": "Out of memory"}}]
    assert FailureTaxonomy._check_environment(hist_oom) == FailureCategory.INFRA_OOM

    # Disk Quota
    hist_disk = [
        {"identity": "env_id", "content": {"status": "error", "message": "disk quota exceeded"}}
    ]
    assert FailureTaxonomy._check_environment(hist_disk) == FailureCategory.INFRA_DISK_QUOTA

    # Connection Refused
    hist_conn = [
        {"identity": "env_id", "content": {"status": "error", "message": "connection refused"}}
    ]
    assert FailureTaxonomy._check_environment(hist_conn) == FailureCategory.INFRA_CONNECTION_FAILED


def test_check_agent_fabrication_hallucination():
    """Verify detection of fabricated tool results."""
    history = [
        {"role": "environment", "content": "Database secret is 456"},
        {
            "role": "agent",
            "content": "I got tool_result: 'Database secret is 123'",
        },  # Fabricated value
    ]

    # task_result context
    tr = {"conversation_history": history, "tool_registry": {"get_secret": {"parameters": []}}}

    with patch("eval_runner.taxonomy.logger"):
        res = FailureTaxonomy._check_agent(history, tr)
        assert res == FailureCategory.POLICY_HALLUCINATION


def test_classify_empty_events():
    """Verify classification behavior for empty event streams."""
    assert FailureTaxonomy.classify_from_events([]) == FailureCategory.UNKNOWN_FAILURE
