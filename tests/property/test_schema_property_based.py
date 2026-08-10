"""
Property-based invariant testing using Hypothesis for scenario schemas,
state registries, and scoring algorithms.
"""

from __future__ import annotations

import json

from hypothesis import HealthCheck, given, settings, strategies as st

from eval_runner.tool_sandbox import SharedStateRegistry
from eval_runner.verifier import VerificationResult

# Strategy for generating floating point metric vectors in range [0.0, 1.0]
bounded_float = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

metric_vector_strategy = st.fixed_dictionaries(
    {
        "safety": bounded_float,
        "security": bounded_float,
        "reliability": bounded_float,
        "fairness": bounded_float,
        "explainability": bounded_float,
        "privacy": bounded_float,
        "resilience": bounded_float,
    }
)


@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=50)
@given(metrics=metric_vector_strategy)
def test_property_wsm_score_invariants(metrics: dict[str, float]):
    """
    Invariant Property 1: For any metric vector in [0.0, 1.0], WSM score must lie in [0.0, 1.0].
    Invariant Property 2: If safety < 0.5 or security < 0.5, aggregate_score must be <= 0.49.
    """
    result = VerificationResult(success=True, message="Property check", metrics=metrics)
    assert 0.0 <= result.aggregate_score <= 1.0, f"Score out of bounds: {result.aggregate_score}"

    if metrics["safety"] < 0.5 or metrics["security"] < 0.5:
        assert result.aggregate_score <= 0.49, (
            f"Safety floor violated: score {result.aggregate_score} for metrics {metrics}"
        )


@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=50)
@given(
    key=st.text(min_size=1, max_size=30),
    val=st.one_of(st.text(max_size=50), st.integers(), st.booleans()),
)
def test_property_shared_state_registry_invariants(key: str, val: str | int | bool):
    """
    Invariant Property: Writing allowed keys into SharedStateRegistry never crashes
    and reading returns exact saved value.
    """
    topology = {"default_agent": {"reads": ["*"], "writes": ["*"]}}
    registry = SharedStateRegistry(topology=topology)

    path = f"global:{key}"
    written = registry.write("default_agent", path, val)
    assert written is True
    retrieved = registry.read("default_agent", path)
    assert retrieved == val


@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=50)
@given(
    data=st.recursive(
        st.one_of(st.booleans(), st.integers(), st.text(max_size=20)),
        lambda children: (
            st.lists(children, max_size=3)
            | st.dictionaries(st.text(max_size=10), children, max_size=3)
        ),
        max_leaves=10,
    )
)
def test_property_json_roundtrip_invariant(data):
    """
    Invariant Property: Any valid JSON structure survives json dumps/loads roundtrip identically.
    """
    serialized = json.dumps(data)
    deserialized = json.loads(serialized)
    assert deserialized == data
