"""
Consolidated Metric & Calibration Test Suite for AgentV Evaluation Harness.
Standardizes verification across heuristics, LLM-based judges, and judge calibration.
"""

import json
import json as _json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner import calibrator, metrics, reporter
from eval_runner.metrics import MetricRegistry, planning as _planning
from eval_runner.metrics.accuracy import (
    calculate_calculation_accuracy,
    calculate_luna_judge_score as _luna,
    calculate_output_matches,
    calculate_verification_accuracy,
)
from eval_runner.metrics.defense import calculate_defense_high_fidelity_metric
from eval_runner.metrics.technical import calculate_technical_correctness
from eval_runner.metrics.utils import extract_numbers
from eval_runner.session import SessionManager as _SessionManager

# --- 1. Core Heuristics & Accuracy ---


def test_heuristic_logic():
    # Tool Call
    assert metrics.calculate_tool_call_correctness(["a"], ["a"]) == 1.0
    assert metrics.calculate_tool_call_correctness(["a"], ["b"]) == 0.0

    # Output Match
    criterion = {"expected": ["Success", "regex:ID-\\d+"]}
    assert calculate_output_matches(criterion, "Success ID-123") == 1.0
    assert calculate_output_matches(criterion, "Success") == 0.5


# --- 2. Advanced LLM-Based Metrics ---


@pytest.mark.asyncio
async def test_luna_judge_mechanics():
    criterion = {"expected_outcome": "Happy"}
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"response": "0.9"}

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        mock_resp_cm = MagicMock()
        mock_resp_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session.post.return_value = mock_resp_cm

        score = await metrics.calculate_luna_judge_score(criterion, "User is happy")
        assert score == 0.9


# --- 3. Latency & Parsimony ---


def test_efficiency_metrics():
    assert metrics.calculate_delegation_latency(2, 1) == 1.0
    assert metrics.calculate_path_parsimony({}, 1, 5) == 1.0
    assert metrics.calculate_delegation_loop_risk(["A", "B", "C"]) == 1.0
    assert metrics.calculate_delegation_loop_risk(["A", "B", "A"]) == 0.0


# --- 4. Judge Calibration Logic ---


def test_calibrator_smoke(tmp_path, capsys):
    trace_file = tmp_path / "trace.json"
    events = [
        {"event": "evaluation", "task_id": "t1", "value": 0.8, "metadata": {"human": False}},
        {"event": "evaluation", "task_id": "t1", "value": 1.0, "metadata": {"human": True}},
    ]
    trace_file.write_text("\n".join(json.dumps(e) for e in events))

    calibrator.run_calibration(str(trace_file))
    stdout = capsys.readouterr().out
    assert "JUDGE CALIBRATION REPORT" in stdout
    assert "Total Samples:         1" in stdout


def test_calibrator_directory_aggregation(tmp_path, capsys):
    d = tmp_path / "runs"
    d.mkdir()
    (d / "a.jsonl").write_text(
        json.dumps({"event": "evaluation", "task_id": "t3", "value": 0.9}) + "\n"
    )
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"t3": 1.0}))

    calibrator.run_calibration(str(d), golden_path=str(golden))
    stdout = capsys.readouterr().out
    assert "Loaded 1 golden labels" in stdout


# === Ported from test_metrics.py ===


@pytest.mark.asyncio
async def test_luna_judge_fallback_jaccard():
    """Luna-Judge falls back to Jaccard when Ollama is unreachable."""
    criterion = {"expected_outcome": "apple banana"}
    with patch("aiohttp.ClientSession", side_effect=Exception("Connection Refused")):
        score = await metrics.calculate_luna_judge_score(criterion, "apple orange")
        assert 0.33 < score < 0.34


def test_tool_correctness_both_empty():
    assert metrics.calculate_tool_call_correctness([], []) == 1.0


def test_tool_correctness_superset():
    assert metrics.calculate_tool_call_correctness(["a"], ["a", "b"]) == 0.0


def test_tool_correctness_duplicates_ignored():
    assert metrics.calculate_tool_call_correctness(["a", "a", "b"], ["b", "a"]) == 1.0


@pytest.mark.asyncio
async def test_generic_accuracy_non_empty_and_empty():
    criterion = {"metric": "information_retrieval_accuracy", "threshold": 0.8}
    assert (
        await metrics.calculate_generic_accuracy(criterion, "Agent retrieved successfully.") == 1.0
    )
    assert await metrics.calculate_generic_accuracy(criterion, "") == 0.0


def test_communication_clarity_boundaries():
    assert metrics.calculate_communication_clarity({}, "The issue is a local Wi-Fi problem.") == 1.0
    assert metrics.calculate_communication_clarity({}, "OK") == 0.0
    assert metrics.calculate_communication_clarity({}, "           ") == 0.0
    assert metrics.calculate_communication_clarity({}, "1234567890") == 0.0
    assert metrics.calculate_communication_clarity({}, "12345678901") == 1.0


def test_policy_compliance_violation_and_safe():
    history = [
        {"role": "user", "content": "hello"},
        {"role": "agent", "content": {"action": "call_tool"}, "status": "policy_violation"},
        {"role": "environment", "content": {"status": "policy_violation", "message": "error"}},
    ]
    assert metrics.calculate_policy_compliance(history) == 0.0
    safe_history = [{"role": "agent", "content": "OK", "sandbox_response": {"status": "success"}}]
    assert metrics.calculate_policy_compliance(safe_history) == 1.0


def test_delegation_latency_decay():
    assert metrics.calculate_delegation_latency(2, 1) == 1.0
    assert metrics.calculate_delegation_latency(2, 2) == 1.0
    assert metrics.calculate_delegation_latency(2, 3) == 0.8
    assert metrics.calculate_delegation_latency(2, 7) == 0.0


def test_delegation_loop_risk_cycle():
    assert metrics.calculate_delegation_loop_risk(["A", "B", "C"]) == 1.0
    assert metrics.calculate_delegation_loop_risk(["A", "B", "A"]) == 0.0
    assert metrics.calculate_delegation_loop_risk([]) == 1.0


def test_consensus_scoring():
    assert metrics.calculate_consensus_scoring(["Hello world", "Hello world"]) == 1.0
    assert metrics.calculate_consensus_scoring(["Hello world", "Hello"]) == 0.5
    assert metrics.calculate_consensus_scoring(["A", "B"]) == 0.0
    score = metrics.calculate_consensus_scoring(["A", "B", "A"])
    assert 0.33 < score < 0.34


def test_safety_pii_detection():
    assert metrics.calculate_pii_safety({}, "Contact me at test@example.com") == 0.0
    assert metrics.calculate_pii_safety({}, "Call 123-456-7890") == 0.0
    assert metrics.calculate_pii_safety({}, "No PII here.") == 1.0
    assert metrics.calculate_pii_safety({}, "") == 1.0


def test_refusal_calibration():
    assert metrics.calculate_refusal_calibration({"expect_refusal": True}, "I cannot help.") == 1.0
    assert metrics.calculate_refusal_calibration({"expect_refusal": False}, "I am sorry.") == 0.0
    assert (
        metrics.calculate_refusal_calibration({"expect_refusal": True}, "Sure, hacking it.") == 0.0
    )
    assert (
        metrics.calculate_refusal_calibration({"expect_refusal": False}, "Here is weather.") == 1.0
    )


@pytest.mark.asyncio
async def test_luna_judge_exact_match_and_fallback():
    criterion = {"expected_outcome": "The repo is cloned"}
    assert await metrics.calculate_luna_judge_score(criterion, "The repo is cloned") == 1.0

    mock_fail = MagicMock()
    mock_fail.__aenter__ = AsyncMock(side_effect=Exception("Conn fail"))
    with patch("aiohttp.ClientSession", return_value=mock_fail):
        assert await metrics.calculate_luna_judge_score(criterion, "repo cloned") == 0.5
        assert await metrics.calculate_luna_judge_score(criterion, "something else") == 0.0


def test_consistency_score():
    assert metrics.calculate_consistency_score(["hello", "hello"]) == 1.0
    assert metrics.calculate_consistency_score(["hello", "world"]) == 0.0
    score = metrics.calculate_consistency_score(["a b", "a c"])
    assert 0.33 < score < 0.34


def test_state_correctness_full_and_partial():
    expected = [
        {"path": "git.branch", "expected": "main"},
        {"path": "db['active']", "expected": True},
        {"path": "tables.users[0].id", "expected": 1},
    ]
    actual = {"git": {"branch": "main"}, "db": {"active": True}, "tables": {"users": [{"id": 1}]}}
    assert metrics.calculate_state_correctness(expected, actual) == 1.0
    actual["git"]["branch"] = "develop"
    assert metrics.calculate_state_correctness(expected, actual) == pytest.approx(2 / 3)


# === Ported from test_metrics_accuracy.py ===


def test_output_matches_empty_target():
    assert calculate_output_matches({}, "some summary") == 1.0
    assert calculate_output_matches({"expected": []}, "some summary") == 1.0


def test_output_matches_single_string():
    assert calculate_output_matches({"expected": "Success"}, "Operation Success") == 1.0
    assert calculate_output_matches({"expected": "Success"}, "Failure") == 0.0


def test_output_matches_list():
    assert (
        calculate_output_matches({"expected": ["Success", "Done"]}, "Success - Task is Done") == 1.0
    )
    assert (
        calculate_output_matches({"expected": ["Success", "Done"]}, "Success - Not finished") == 0.5
    )
    assert calculate_output_matches({"expected": ["Success", "Done"]}, "Pending") == 0.0


def test_output_matches_regex():
    assert calculate_output_matches({"expected": ["regex:ID-\\d+"]}, "Case ID-123") == 1.0
    assert calculate_output_matches({"expected": ["regex:ID-\\d+"]}, "Case ID-ABC") == 0.0


def test_output_matches_mixed():
    assert (
        calculate_output_matches(
            {"expected": ["Completed", "regex:TRX-[a-z]+"]}, "Completed TRX-abc"
        )
        == 1.0
    )
    assert (
        calculate_output_matches(
            {"expected": ["Completed", "regex:TRX-[a-z]+"]}, "Completed No TRX"
        )
        == 0.5
    )


def test_output_matches_non_string_summary():
    assert calculate_output_matches({"expected": "123"}, 123) == 1.0
    assert calculate_output_matches({"expected": "123"}, None) == 0.0


def test_output_matches_non_standard_target():
    assert calculate_output_matches({"expected": 123}, "The key is 123") == 1.0


# === Ported from test_metrics_extra.py ===


@pytest.mark.asyncio
async def test_luna_judge_score_branches():
    # Empty expected → 1.0
    assert await _luna({"expected_outcome": ""}, "test") == 1.0
    # Exact match short-circuit
    assert await _luna({"expected_outcome": "exact"}, "exact") == 1.0

    # required=True + provider failure → RuntimeError
    with patch(
        "eval_runner.llm_providers.LLMProviderFactory.create", side_effect=Exception("API limit")
    ):
        with pytest.raises(RuntimeError, match="Judge Configuration Error"):
            await _luna({"expected_outcome": "a", "required": True}, "b")

    # required=False + provider failure → Jaccard fallback
    with patch(
        "eval_runner.llm_providers.LLMProviderFactory.create", side_effect=Exception("limit")
    ):
        res = await _luna({"expected_outcome": "hello", "required": False}, "hello world")
        assert res > 0.0

    # Model override + float parsing from string
    mock_provider = MagicMock()
    mock_provider.model = "old-model"
    mock_provider.generate = AsyncMock(return_value="0.95 text")
    with patch("eval_runner.llm_providers.LLMProviderFactory.create", return_value=mock_provider):
        res = await _luna(
            {"expected_outcome": "a", "judge_config": {"judge_model": "new-model"}}, "b"
        )
        assert res == 0.95
        assert mock_provider.model == "new-model"

    # Parse failure → Jaccard fallback
    mock_provider.generate = AsyncMock(return_value="nan string")
    with patch("eval_runner.llm_providers.LLMProviderFactory.create", return_value=mock_provider):
        res = await _luna({"expected_outcome": "a"}, "b")
        assert res >= 0.0


@pytest.mark.asyncio
async def test_defense_metric_rubric():
    with patch("eval_runner.metrics.calculate_luna_judge_score", return_value=0.88) as mock_luna:
        res = await calculate_defense_high_fidelity_metric(
            {"metric": "roe_compliance_score"}, "agent said"
        )
        assert res == 0.88
        assert mock_luna.call_args[0][0]["judge_config"]["judge_rubric"] == "policy_adherence"


@pytest.mark.asyncio
async def test_technical_metric_rubric():
    with patch("eval_runner.metrics.calculate_luna_judge_score", return_value=0.92) as mock_luna:
        res = await calculate_technical_correctness({}, "agent code")
        assert res == 0.92
        assert mock_luna.call_args[0][0]["judge_config"]["judge_rubric"] == "technical_correctness"


def test_calculation_accuracy_branches():
    assert calculate_calculation_accuracy({"expected_outcome": ""}, "") == 0.0
    assert (
        calculate_calculation_accuracy({"expected_outcome": "text only"}, "agent response") == 1.0
    )
    res = calculate_calculation_accuracy({"expected_outcome": "5 and 10"}, "found 5 but missed ten")
    assert res == 0.5


def test_verification_accuracy_keyword_hit():
    res = calculate_verification_accuracy(
        {"expected_outcome": "validate"}, "I have verified the output"
    )
    assert res >= 0.5


# === Ported from test_metrics_modular.py ===


def test_metric_registry_retrieval():
    assert MetricRegistry.get("tool_call_correctness") is not None


@patch("eval_runner.metrics.utils.extract_numbers")
def test_calculation_accuracy_logic(mock_extract):
    mock_extract.side_effect = [[100.0], [100.0]]
    assert (
        calculate_calculation_accuracy({"expected_outcome": "Result is 100"}, "Agent says 100")
        == 1.0
    )
    mock_extract.side_effect = [[100.0], [50.0]]
    assert (
        calculate_calculation_accuracy({"expected_outcome": "Result is 100"}, "Agent says 50")
        == 0.0
    )


def test_numeric_utility_extraction():
    numbers = extract_numbers("The invoice total is $1,250.50 with a discount of 5%.")
    assert 1250.5 in numbers
    assert 5.0 in numbers


@pytest.mark.asyncio
@patch("eval_runner.llm_providers.LLMProviderFactory.create")
async def test_planning_quality_rubric(mock_factory):
    from eval_runner.metrics.planning import calculate_planning_quality

    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(return_value="1.0")
    mock_factory.return_value = mock_provider
    with patch("eval_runner.rubrics.RubricRegistry.get") as mock_rubric_get:
        mock_rubric_get.return_value = "Mock Rubric {expected_outcome} {agent_summary}"
        await calculate_planning_quality(
            {"expected_outcome": "Plan A", "required": True}, "Agent Plan B"
        )
        mock_rubric_get.assert_called_with("strategic_planning")


def test_root_cause_analysis_is_callable():
    from eval_runner.metrics.planning import calculate_root_cause_analysis

    assert callable(calculate_root_cause_analysis)


# === Ported from test_metrics_planning.py ===


@pytest.mark.asyncio
async def test_planning_quality_metric():
    with patch(
        "eval_runner.metrics.calculate_luna_judge_score", new_callable=AsyncMock
    ) as mock_judge:
        mock_judge.return_value = 0.85
        score = await _planning.calculate_planning_quality(
            {"id": "c1", "judge_config": {"temp": 0.5}}, "Agent planned well."
        )
        assert score == 0.85
        assert mock_judge.call_args[0][0]["judge_config"]["judge_rubric"] == "strategic_planning"


@pytest.mark.asyncio
async def test_root_cause_analysis_metric():
    with patch(
        "eval_runner.metrics.calculate_luna_judge_score", new_callable=AsyncMock
    ) as mock_judge:
        mock_judge.return_value = 0.9
        score = await _planning.calculate_root_cause_analysis({}, "Found the bug.")
        assert score == 0.9
        assert mock_judge.call_args[0][0]["judge_config"]["judge_rubric"] == "causal_inference"


# === Ported from test_metrics_dispatch.py ===


class _MockSandbox:
    def __init__(self):
        self.state = {"db": {"active": True}}

    async def get_full_state(self):
        return self.state


@pytest.fixture
def dispatch_session():
    scenario = {"id": "test-scenario", "success_criteria": []}
    return _SessionManager("run_1", scenario)


@pytest.mark.asyncio
async def test_metric_dispatch_standard(dispatch_session):
    @metrics.MetricRegistry.register("test_standard_ported")
    async def standard_metric(eval_context, summary):
        assert isinstance(eval_context, dict)
        assert isinstance(summary, str)
        return 1.0

    node = {"success_criteria": [{"metric": "test_standard_ported"}]}
    results = await dispatch_session._calculate_metrics(
        node, 1, 1, [], _MockSandbox(), {"used_tools": []}
    )
    assert results["metrics"][0]["score"] == 1.0


@pytest.mark.asyncio
async def test_metric_dispatch_aliases(dispatch_session):
    @metrics.MetricRegistry.register("test_aliases_ported")
    def alias_metric(sandbox_state, used_tools):
        assert "db" in sandbox_state
        assert isinstance(used_tools, list)
        return 1.0

    node = {"success_criteria": [{"metric": "test_aliases_ported"}]}
    results = await dispatch_session._calculate_metrics(
        node, 1, 1, [], _MockSandbox(), {"used_tools": ["t1"]}
    )
    assert results["metrics"][0]["score"] == 1.0


@pytest.mark.asyncio
async def test_metric_dispatch_failure_mode(dispatch_session, capsys):
    @metrics.MetricRegistry.register("test_failure_ported")
    def failure_metric(impossible_param):
        return 0.0

    node = {"success_criteria": [{"metric": "test_failure_ported"}]}
    results = await dispatch_session._calculate_metrics(
        node, 1, 1, [], _MockSandbox(), {"used_tools": []}
    )
    assert len(results["metrics"]) == 0
    captured = capsys.readouterr()
    assert "missing 1 required positional argument: 'impossible_param'" in captured.out


@pytest.mark.asyncio
async def test_metric_isolation(dispatch_session):
    @metrics.MetricRegistry.register("test_isolation_ported", source="EXTERNAL_PLUGIN")
    def mutator_metric(sandbox_state):
        sandbox_state["db"]["mutated"] = True
        return 1.0

    node = {"success_criteria": [{"metric": "test_isolation_ported"}]}
    sandbox = _MockSandbox()
    await dispatch_session._calculate_metrics(node, 1, 1, [], sandbox, {"used_tools": []})
    assert "mutated" not in sandbox.state["db"]


@pytest.mark.asyncio
async def test_metric_trust_boundaries(dispatch_session):
    @metrics.MetricRegistry.register("core_metric_ported", source="CORE")
    def core_metric(session_metadata):
        assert session_metadata is not None
        return 1.0

    @metrics.MetricRegistry.register("external_metric_ported", source="EXTERNAL")
    def external_metric(session_metadata=None):
        assert session_metadata is None or session_metadata == {}
        return 0.5

    dispatch_session.plugin_manager.provenance_map["EXTERNAL"] = {"trusted": False}

    node_core = {"success_criteria": [{"metric": "core_metric_ported"}]}
    res_core = await dispatch_session._calculate_metrics(
        node_core, 1, 1, [], _MockSandbox(), {"used_tools": []}
    )
    assert res_core["metrics"][0]["score"] == 1.0

    node_ext = {"success_criteria": [{"metric": "external_metric_ported"}]}
    res_ext = await dispatch_session._calculate_metrics(
        node_ext, 1, 1, [], _MockSandbox(), {"used_tools": []}
    )
    assert res_ext["metrics"][0]["score"] == 0.5


# === Ported from test_metrics_trajectory.py ===


def test_path_parsimony_calculation():
    assert metrics.calculate_path_parsimony({}, 1, 5) == 1.0
    assert metrics.calculate_path_parsimony({}, 5, 5) == 0.0
    assert metrics.calculate_path_parsimony({}, 3, 5) == 0.5
    assert metrics.calculate_path_parsimony({}, 1, 1) == 1.0


def test_mermaid_generation():
    task_results = {
        "conversation_history": [
            {"role": "agent", "content": {"action": "call_tool"}},
            {"role": "environment", "content": {"status": "success"}},
        ]
    }
    mermaid = reporter.generate_mermaid_trajectory(task_results)
    assert "graph TD" in mermaid
    assert "Start((Start))" in mermaid
    assert "End((End))" in mermaid


def test_trajectory_json_export(tmp_path):
    scenario = {
        "id": "test_hitl_ci",
        "workflow": {"nodes": [{"id": "task1", "task_description": "test"}], "edges": []},
    }
    results = [{"task_id": "t1", "metrics": []}]
    reporter.save_trajectory(scenario, results, base_dir=tmp_path)
    export_files = list(tmp_path.glob("reports/trajectories/test_hitl_ci_*.json"))
    assert len(export_files) == 1
    with open(export_files[0]) as f:
        data = _json.load(f)
    assert data["metadata"]["id"] == "test_hitl_ci"
    assert "results" in data
