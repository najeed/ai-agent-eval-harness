from eval_runner.taxonomy import (
    BaseForensicAnalyzer,
    CausalChain,
    DiagnosticResult,
    FailureCategory,
    FailureTaxonomy,
)


def test_failure_category_behavior():
    """Test auto() values are lowercase and __str__ works."""
    assert str(FailureCategory.SUCCESS) == "success"
    assert FailureCategory.INFRA_OOM.value == "infra_oom"


def test_causal_chain():
    """Test causal chain chronologic ledger."""
    chain = CausalChain()
    chain.add(FailureCategory.LOGIC_STALL, "Turn 5 stall", turn_index=5, severity="high")

    assert len(chain) == 1
    assert chain[0]["trigger"] == FailureCategory.LOGIC_STALL
    assert chain[0]["evidence"] == "Turn 5 stall"
    assert chain[0]["severity"] == "high"
    assert "timestamp" in chain[0]


def test_diagnostic_result():
    """Test diagnostic report and dict conversion."""
    chain = CausalChain()
    chain.add(FailureCategory.SECURITY_PII_LEAK, "SSN Found")
    res = DiagnosticResult(
        FailureCategory.SECURITY_PII_LEAK, FailureCategory.SECURITY_PII_LEAK, chain
    )

    d = res.to_dict()
    assert d["root_cause"] == "security_pii_leak"
    assert len(d["causal_chain"]) == 1
    assert "DiagnosticResult" in repr(res)


def test_taxonomy_check_success():
    """Test full and partial success detection."""
    metrics_full = [{"success": True}, {"success": True}]
    assert FailureTaxonomy._check_success(metrics_full) == FailureCategory.SUCCESS

    metrics_partial = [{"success": True}, {"success": False}]
    assert FailureTaxonomy._check_success(metrics_partial) == FailureCategory.PARTIAL_PASS

    assert FailureTaxonomy._check_success([]) is None


def test_taxonomy_check_metrics():
    """Test explicit metric keyword detection."""
    m1 = [{"success": False, "metric": "state_verification_check"}]
    assert FailureTaxonomy._check_metrics(m1) == FailureCategory.LOGIC_STATE_MISMATCH

    m2 = [{"success": False, "metric": "parity_audit"}]
    assert FailureTaxonomy._check_metrics(m2) == FailureCategory.PARITY_STATE_DIVERGENCE


def test_taxonomy_check_environment_infra():
    """Test infrastructure error mapping via system identity."""
    # OOM
    h1 = [
        {"identity": "system_id", "content": {"status": "error", "error": "Process killed by OOM"}}
    ]
    assert FailureTaxonomy._check_environment(h1) == FailureCategory.INFRA_OOM

    # Docker
    h2 = [{"identity": "env_id", "content": {"status": "error", "message": "Docker socket error"}}]
    assert FailureTaxonomy._check_environment(h2) == FailureCategory.INFRA_SANDBOX_FAILURE

    # Connection
    h3 = [
        {
            "identity": "environment_id",
            "content": {"status": "error", "result": "Connection refused"},
        }
    ]
    assert FailureTaxonomy._check_environment(h3) == FailureCategory.INFRA_CONNECTION_FAILED

    # Unauthorized
    h4 = [{"identity": "system_id", "content": {"status": "unauthorized"}}]
    assert FailureTaxonomy._check_environment(h4) == FailureCategory.SECURITY_UNAUTHORIZED_ACCESS


def test_taxonomy_check_agent_behavior():
    """Test agent-side refusal, hallucination and PII leaks."""
    # Refusal
    h1 = [{"role": "agent", "content": "I cannot comply with this policy"}]
    assert FailureTaxonomy._check_agent(h1) == FailureCategory.LOGIC_REFUSAL

    # PII Leak
    h2 = [{"role": "agent", "content": "My SSN is 123-45-6789"}]
    assert FailureTaxonomy._check_agent(h2) == FailureCategory.SECURITY_PII_LEAK

    # Hallucination (Regex)
    h3 = [{"role": "agent", "content": "I am calling an invalid tool now"}]
    assert FailureTaxonomy._check_agent(h3) == FailureCategory.POLICY_HALLUCINATION


def test_taxonomy_hallucination_validation():
    """Test tool registry validation halluncination check."""
    tool_reg = {"valid_tool": {"parameters": ["p1"]}}

    # Unknown tool
    res1 = {
        "tool_registry": tool_reg,
        "conversation_history": [
            {"role": "agent", "tool_calls": [{"name": "fake_tool", "arguments": {}}]}
        ],
    }
    assert (
        FailureTaxonomy._check_agent(res1["conversation_history"], res1)
        == FailureCategory.POLICY_HALLUCINATION
    )

    # Invalid param
    res2 = {
        "tool_registry": tool_reg,
        "conversation_history": [
            {"role": "agent", "tool_calls": [{"name": "valid_tool", "arguments": {"bad_param": 1}}]}
        ],
    }
    assert (
        FailureTaxonomy._check_agent(res2["conversation_history"], res2)
        == FailureCategory.POLICY_HALLUCINATION
    )


def test_taxonomy_stall_detection():
    """Test turn-based and state-delta stalls."""
    # Turn stall
    h_long = [{"role": "agent"}] * FailureTaxonomy.STALL_THRESHOLD
    assert FailureTaxonomy._check_stall(h_long) == FailureCategory.LOGIC_STALL

    # State-delta stall
    snapshots = ["snap1", "snap1", "snap1", "snap1"]
    res = {"state_snapshots": snapshots}
    assert FailureTaxonomy._check_stall([], res) == FailureCategory.LOGIC_STATE_STALL


def test_taxonomy_detect_loops():
    """Test fuzzy repetition and cyclical patterns."""
    # Fuzzy Loop (Near-duplicate)
    h1 = [
        {"role": "agent", "content": "I will try to open the file."},
        {"role": "agent", "content": "I will now try to open the file."},
    ]
    # Ratio: 2 * 27 / (28 + 29) = 54 / 57 = 0.947 > 0.9
    assert FailureTaxonomy._detect_loops(h1) == FailureCategory.LOGIC_PLANNING_ERROR

    # Cyclical Loop A -> B -> A
    h2 = [
        {"role": "agent", "content": "Action A"},
        {"role": "agent", "content": "Action B"},
        {"role": "agent", "content": "Action A"},
    ]
    assert FailureTaxonomy._detect_loops(h2) == FailureCategory.LOGIC_PLANNING_ERROR

    # Repeated Action Stall (Normalized)
    h3 = [
        {"role": "agent", "content": "ls -l /tmp"},
        {"role": "agent", "content": "ls -la /var"},
        {"role": "agent", "content": "ls ."},
    ]
    assert FailureTaxonomy._detect_loops(h3) == FailureCategory.LOGIC_STATE_STALL


def test_taxonomy_protocol_violation():
    """Test industrial protocol sequence enforcement."""
    res_fail = {
        "protocol_sequence_required": ["init", "auth"],
        "protocol_sequence": ["init", "close"],  # Missing auth
    }
    assert FailureTaxonomy._check_protocol(res_fail) == FailureCategory.PARITY_PROTOCOL_VIOLATION

    res_out_of_order = {
        "protocol_sequence_required": ["init", "auth"],
        "protocol_sequence": ["auth", "init"],
    }
    assert (
        FailureTaxonomy._check_protocol(res_out_of_order)
        == FailureCategory.PARITY_PROTOCOL_VIOLATION
    )


def test_taxonomy_register_custom_analyzer():
    """Test registering and triggering extra forensic analyzers."""

    class CustomAnalyzer(BaseForensicAnalyzer):
        def analyze(self, h, res=None):
            return FailureCategory.INFRA_SIMULATOR_EXCEPTION

    # Reset for clean state
    FailureTaxonomy._analyzers = []
    analyzer = CustomAnalyzer()
    FailureTaxonomy.register_analyzer(analyzer)

    # _diagnose calls custom analyzer if default checks pass
    assert FailureTaxonomy._diagnose([], []) == FailureCategory.INFRA_SIMULATOR_EXCEPTION


def test_taxonomy_classify_entry_points():
    """Test top-level entry points (classify, classify_from_events)."""
    # Success path
    assert FailureTaxonomy.classify({"metrics": [{"success": True}]}) == FailureCategory.SUCCESS

    # Raw events path
    events = [
        {"event": "agent_response", "content": "My SSN is 000-00-0000"},
        {"event": "evaluation", "success": False},
    ]
    assert FailureTaxonomy.classify_from_events(events) == FailureCategory.SECURITY_PII_LEAK

    # Unknown
    assert FailureTaxonomy.classify_from_events([]) == FailureCategory.UNKNOWN_FAILURE
