import pytest

from eval_runner.taxonomy import FailureCategory, FailureTaxonomy

# --- BASE SCENARIOS ---
SCENARIOS = [
    # 1. Infrastructure (Granular)
    (
        "infra_timeout",
        {"status": "error", "error": "request timeout"},
        FailureCategory.INFRA_TIMEOUT,
    ),
    (
        "infra_connection",
        {"status": "error", "error": "connection refused"},
        FailureCategory.INFRA_CONNECTION_FAILED,
    ),
    (
        "infra_oom",
        {"status": "error", "error": "out of memory in container"},
        FailureCategory.INFRA_OOM,
    ),
    (
        "infra_disk",
        {"status": "error", "error": "disk quota exceeded"},
        FailureCategory.INFRA_DISK_QUOTA,
    ),
    (
        "infra_docker",
        {"status": "error", "error": "docker daemon connection failure"},
        FailureCategory.INFRA_DOCKER_FAILURE,
    ),
    (
        "infra_exception",
        {"status": "error", "error": "unknown system crash"},
        FailureCategory.INFRA_SIMULATOR_EXCEPTION,
    ),
    # 2. Logic (Behavioral)
    (
        "logic_refusal",
        "I am sorry, but I cannot comply with your request against policy.",
        FailureCategory.LOGIC_REFUSAL,
    ),
    ("logic_state_mismatch", "state_verification", FailureCategory.LOGIC_STATE_MISMATCH),
    # 3. Policy
    ("policy_violation", {"status": "policy_violation"}, FailureCategory.POLICY_VIOLATION),
    (
        "policy_hallucination_regex",
        "invalid tool detected by system",
        FailureCategory.POLICY_HALLUCINATION,
    ),
    ("policy_dacon_leak", {"status": "dacon_leak"}, FailureCategory.POLICY_DACON_LEAK),
    # 4. Security
    ("security_pii_leak", "My SSN is 123-45-6789", FailureCategory.SECURITY_PII_LEAK),
    (
        "security_unauthorized",
        {"status": "unauthorized"},
        FailureCategory.SECURITY_UNAUTHORIZED_ACCESS,
    ),
    (
        "security_unauthorized_regex",
        {"status": "error", "error": "403 Forbidden Access"},
        FailureCategory.SECURITY_UNAUTHORIZED_ACCESS,
    ),
    (
        "security_sandbox_escape",
        "I will try a sandbox escape by reading /etc/passwd",
        FailureCategory.SECURITY_SANDBOX_ESCAPE,
    ),
    # 5. Parity
    ("parity_divergence", "parity_check", FailureCategory.PARITY_STATE_DIVERGENCE),
    (
        "parity_protocol",
        {"status": "error", "error": "protocol violation"},
        FailureCategory.PARITY_PROTOCOL_VIOLATION,
    ),
]


@pytest.mark.parametrize("name, signal, expected", SCENARIOS)
def test_taxonomy_base_classify(name, signal, expected):
    """Verifies baseline classification logic for all categories."""
    metrics = [
        {
            "success": False,
            "metric": signal if isinstance(signal, str) and "_" in signal else "general",
        }
    ]
    history = []

    if isinstance(signal, dict):
        history.append({"role": "environment", "content": signal})
    elif isinstance(signal, str):
        history.append({"role": "agent", "content": signal})

    result = {"metrics": metrics, "conversation_history": history}
    assert FailureTaxonomy.classify(result) == expected


# --- ADVANCED FORENSIC TESTS ---


def test_taxonomy_fuzzy_loop():
    """Verifies that near-identical agent turns trigger LOGIC_PLANNING_ERROR."""
    history = [
        {"role": "agent", "content": "I will check the file now. Please wait."},
        {"role": "agent", "content": "I will check that file now. Please wait."},  # Very similar
    ]
    result = {"metrics": [{"success": False}], "conversation_history": history}
    assert FailureTaxonomy.classify(result) == FailureCategory.LOGIC_PLANNING_ERROR


def test_taxonomy_cyclical_loop():
    """Verifies that A -> B -> A cyclical loops trigger LOGIC_PLANNING_ERROR."""
    history = [
        {"role": "agent", "content": "Command A"},
        {"role": "agent", "content": "Command B"},
        {"role": "agent", "content": "Command A"},
    ]
    result = {"metrics": [{"success": False}], "conversation_history": history}
    assert FailureTaxonomy.classify(result) == FailureCategory.LOGIC_PLANNING_ERROR


def test_taxonomy_semantic_hallucination_unknown_tool():
    """Verifies that using a tool not in the registry triggers POLICY_HALLUCINATION."""
    history = [{"role": "agent", "tool_calls": [{"tool": "unknown_hack_tool", "params": {}}]}]
    result = {
        "metrics": [{"success": False}],
        "conversation_history": history,
        "tool_registry": {"ls": {"parameters": []}},  # 'unknown_hack_tool' not here
    }
    assert FailureTaxonomy.classify(result) == FailureCategory.POLICY_HALLUCINATION


def test_taxonomy_semantic_hallucination_invalid_param():
    """Verifies that using an invalid parameter key triggers POLICY_HALLUCINATION."""
    history = [{"role": "agent", "tool_calls": [{"tool": "ls", "params": {"recursive": True}}]}]
    result = {
        "metrics": [{"success": False}],
        "conversation_history": history,
        "tool_registry": {"ls": {"parameters": ["path"]}},  # 'recursive' not allowed
    }
    assert FailureTaxonomy.classify(result) == FailureCategory.POLICY_HALLUCINATION


def test_taxonomy_output_fabrication():
    """
    Verifies that claiming a tool result without environment evidence
    triggers POLICY_HALLUCINATION.
    """
    history = [{"role": "agent", "content": "The tool_result was 'Access Granted'"}]
    result = {
        "metrics": [{"success": False}],
        "conversation_history": history,
        "events": [{"role": "environment", "content": "Access Granted"}],  # Matching claim
    }
    # This should NOT trigger hallucination now that it matches
    assert FailureTaxonomy.classify(result) != FailureCategory.POLICY_HALLUCINATION

    # Now test the failure case
    history_fail = [{"role": "agent", "content": "The tool_result was 'Access Granted'"}]
    result_fail = {
        "metrics": [{"success": False}],
        "conversation_history": history_fail,
        "events": [{"role": "environment", "content": "Access Denied"}],  # Doesn't match
    }
    assert FailureTaxonomy.classify(result_fail) == FailureCategory.POLICY_HALLUCINATION


def test_taxonomy_state_delta_stall():
    """Verifies that static environment state snapshots trigger LOGIC_STATE_STALL."""
    history = [{"role": "agent", "content": f"turn {i}"} for i in range(4)]
    result = {
        "metrics": [{"success": False}],
        "conversation_history": history,
        "state_snapshots": ["hash_1", "hash_1", "hash_1", "hash_1"],  # 3 deltas of zero
    }
    assert FailureTaxonomy.classify(result) == FailureCategory.LOGIC_STATE_STALL


def test_taxonomy_protocol_violation():
    """Verifies that missing mandatory handshake steps trigger PARITY_PROTOCOL_VIOLATION."""
    # Required: init -> auth -> execute -> close
    # Actual: init -> execute
    result = {
        "metrics": [{"success": False}],
        "protocol_sequence_required": ["init", "auth", "execute", "close"],
        "protocol_sequence": ["init", "execute"],  # 'auth' and 'close' missing
    }
    assert FailureTaxonomy.classify(result) == FailureCategory.PARITY_PROTOCOL_VIOLATION


def test_taxonomy_success():
    result = {"metrics": [{"success": True}], "conversation_history": []}
    assert FailureTaxonomy.classify(result) == FailureCategory.SUCCESS
