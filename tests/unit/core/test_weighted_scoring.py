from eval_runner.taxonomy import CausalChain, FailureCategory
from eval_runner.triage import Confidence, TriageEngine


def test_weighted_scoring_causal_chain_ranking():
    """Verifies that the Weighted Evidence Model ranks evidence correctly."""
    history = [
        {"role": "agent", "identity": "agent_id", "content": "Doing something..."},
        {"identity": "env_id", "content": {"status": "error", "error": "connection timeout"}},
    ]

    # Simulate a result with multiple evidence points
    # Trigger 1: Tool Error (lower rank/confidence)
    # Trigger 2: Infra Timeout (higher rank/confidence)
    chain = CausalChain()
    chain.add(
        FailureCategory.INFRA_TIMEOUT,
        "Network was unreachable",
        turn_index=1,
        severity="high",
        rank=5,
    )
    chain.add(
        FailureCategory.LOGIC_STALL, "Agent slowed down", turn_index=0, severity="low", rank=0
    )

    result = {"conversation_history": history, "diagnostic_report": {"causal_chain": list(chain)}}

    diagnosis = TriageEngine.identify_root_cause(result)

    # Should pick INFRA_TIMEOUT because it has higher rank/certainty in the weighted model
    assert diagnosis["category"] == FailureCategory.INFRA_TIMEOUT
    assert diagnosis["confidence"] == Confidence.CERTAIN
    assert "Network was unreachable" in diagnosis["reason"]


def test_conflict_resolution_logic():
    """Verifies that explicit policy violations override generic stalls."""
    history = [
        {
            "role": "agent",
            "identity": "agent_id",
            "content": "I will try to access the root password.",
        },
        {"identity": "env_id", "content": {"status": "policy_violation"}},
        {
            "role": "agent",
            "identity": "agent_id",
            "content": "I will try to access the root password.",
        },
        {"identity": "env_id", "content": {"status": "policy_violation"}},
        {
            "role": "agent",
            "identity": "agent_id",
            "content": "I will try to access the root password.",
        },
    ]

    # This history has a Stall (3 repetitions) AND Policy Violations
    # TriageEngine should rank Policy higher than a generic behavioral stall
    diagnosis = TriageEngine.identify_root_cause(history)

    assert diagnosis["category"] == FailureCategory.POLICY_VIOLATION
    assert diagnosis["confidence"] == Confidence.HIGH
    assert "policy violation" in diagnosis["reason"].lower()
