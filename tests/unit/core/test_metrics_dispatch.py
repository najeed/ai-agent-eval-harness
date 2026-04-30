import pytest

from eval_runner import metrics
from eval_runner.session import SessionManager


class MockSandbox:
    def __init__(self):
        self.state = {"db": {"active": True}}

    async def get_full_state(self):
        return self.state


@pytest.fixture
def session():
    scenario = {"id": "test-scenario", "success_criteria": []}
    return SessionManager("run_1", scenario)


@pytest.mark.asyncio
async def test_metric_dispatch_standard(session):
    """Test dispatching to a metric with standard parameters."""

    @metrics.MetricRegistry.register("test_standard")
    async def standard_metric(eval_context, summary):
        assert isinstance(eval_context, dict)
        assert isinstance(summary, str)
        return 1.0

    node = {"success_criteria": [{"metric": "test_standard"}]}
    sandbox = MockSandbox()
    results = await session._calculate_metrics(node, 1, 1, [], sandbox, {"used_tools": []})

    assert len(results["metrics"]) == 1
    assert results["metrics"][0]["metric"] == "test_standard"
    assert results["metrics"][0]["score"] == 1.0


@pytest.mark.asyncio
async def test_metric_dispatch_industrial_params(session):
    """Test dispatching to a metric with newly added industrial parameters."""

    @metrics.MetricRegistry.register("test_industrial")
    def industrial_metric(expected, actual, agent_sequence, protocol_sequence):
        # These should be populated by the patched SessionManager
        assert expected == "goal"
        assert actual == "summary"
        assert isinstance(agent_sequence, list)
        assert isinstance(protocol_sequence, list)
        return 0.9

    node = {"success_criteria": [{"metric": "test_industrial", "expected": "goal"}]}
    sandbox = MockSandbox()
    # Mocking history to contain an agent message
    history = [{"role": "agent", "content": "summary", "agent_id": "agent_1"}]

    results = await session._calculate_metrics(node, 1, 1, history, sandbox, {"used_tools": []})

    # This will FAIL until SessionManager is patched
    assert len(results["metrics"]) == 1
    assert results["metrics"][0]["score"] == 0.9


@pytest.mark.asyncio
async def test_metric_dispatch_aliases(session):
    """Test dispatching using aliases in context_map."""

    @metrics.MetricRegistry.register("test_aliases")
    def alias_metric(sandbox_state, used_tools):
        assert "db" in sandbox_state
        assert isinstance(used_tools, list)
        return 1.0

    node = {"success_criteria": [{"metric": "test_aliases"}]}
    sandbox = MockSandbox()
    results = await session._calculate_metrics(node, 1, 1, [], sandbox, {"used_tools": ["t1"]})

    assert results["metrics"][0]["score"] == 1.0


@pytest.mark.asyncio
async def test_metric_dispatch_failure_mode(session, capsys):
    """Test that metrics with unfulfillable signatures fail gracefully with an error message."""

    @metrics.MetricRegistry.register("test_failure")
    def failure_metric(impossible_param):
        return 0.0

    node = {"success_criteria": [{"metric": "test_failure"}]}
    sandbox = MockSandbox()

    results = await session._calculate_metrics(node, 1, 1, [], sandbox, {"used_tools": []})

    # Should not be in results as it failed to execute
    assert len(results["metrics"]) == 0

    captured = capsys.readouterr()
    assert "missing 1 required positional argument: 'impossible_param'" in captured.out


@pytest.mark.asyncio
async def test_metric_isolation(session):
    """Test that metrics cannot mutate the session state (Side-Effect Prevention)."""

    # Registered with source="EXTERNAL" to trigger isolation
    @metrics.MetricRegistry.register("test_isolation", source="EXTERNAL_PLUGIN")
    def mutator_metric(sandbox_state):
        sandbox_state["db"]["mutated"] = True
        return 1.0

    node = {"success_criteria": [{"metric": "test_isolation"}]}
    sandbox = MockSandbox()

    await session._calculate_metrics(node, 1, 1, [], sandbox, {"used_tools": []})

    # Original state should NOT be mutated
    assert "mutated" not in sandbox.state["db"]


@pytest.mark.asyncio
async def test_metric_trust_boundaries(session):
    """Test trust-based parameter masking."""

    # 1. CORE metric (Trusted)
    @metrics.MetricRegistry.register("core_metric", source="CORE")
    def core_metric(session_metadata):
        assert session_metadata is not None
        return 1.0

    # 2. UNTRUSTED External metric
    @metrics.MetricRegistry.register("external_metric", source="EXTERNAL")
    def external_metric(session_metadata=None):
        # Should be None or empty because it's untrusted
        assert session_metadata is None or session_metadata == {}
        return 0.5

    # 3. TRUSTED Plugin metric
    @metrics.MetricRegistry.register("trusted_plugin_metric", source="TrustedPlugin")
    def trusted_metric(session_metadata):
        assert session_metadata is not None
        return 1.0

    # Setup trust in the session manager
    session.plugin_manager.provenance_map["TrustedPlugin"] = {"trusted": True}
    session.plugin_manager.provenance_map["EXTERNAL"] = {"trusted": False}

    sandbox = MockSandbox()

    # Run Core
    node_core = {"success_criteria": [{"metric": "core_metric"}]}
    res_core = await session._calculate_metrics(node_core, 1, 1, [], sandbox, {"used_tools": []})
    assert res_core["metrics"][0]["score"] == 1.0

    # Run External
    node_ext = {"success_criteria": [{"metric": "external_metric"}]}
    res_ext = await session._calculate_metrics(node_ext, 1, 1, [], sandbox, {"used_tools": []})
    assert res_ext["metrics"][0]["score"] == 0.5

    # Run Trusted Plugin
    node_trusted = {"success_criteria": [{"metric": "trusted_plugin_metric"}]}
    res_trusted = await session._calculate_metrics(
        node_trusted, 1, 1, [], sandbox, {"used_tools": []}
    )
    assert res_trusted["metrics"][0]["score"] == 1.0
