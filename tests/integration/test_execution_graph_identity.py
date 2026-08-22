import json
from pathlib import Path
from unittest.mock import patch

import pytest
from jsonschema import validate

from eval_runner import cli
from eval_runner.handlers.evaluation import handle_run


def parse_args(cmd_list):
    parser = cli.get_parser(is_help=True)
    return parser.parse_args(cmd_list)


@pytest.mark.asyncio
async def test_execution_graph_canonical_identity(tmp_path, monkeypatch):
    """
    Golden Trace Integration Test:
    Verifies that the canonical execution graph emits:
    - scenario_node_id matching the scenario DAG
    - execution_instance_id matching {scenario_node_id}:attempt:{n}
    - from_scenario_node_id / to_scenario_node_id matching graph edges
    - All events strictly conform to spec/runs/runs.schema.json
    """
    monkeypatch.chdir(tmp_path)

    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", log_dir)
    monkeypatch.setenv("RUN_LOG_DIR", str(log_dir))

    # Two-node sequential scenario
    scenario_file = tmp_path / "test_scenario_dag.json"
    scenario_file.write_text(
        json.dumps(
            {
                "aes_version": 1.4,
                "metadata": {
                    "name": "DAG Identity Golden Test",
                    "id": "dag_identity_golden_test",
                    "compliance_level": "Standard",
                },
                "workflow": {
                    "nodes": [
                        {
                            "id": "fetch-data",
                            "task_description": "Fetch customer record",
                            "success_criteria": [{"metric": "generic_accuracy", "threshold": 0.5}],
                        },
                        {
                            "id": "process-data",
                            "task_description": "Process record calculations",
                            "success_criteria": [{"metric": "generic_accuracy", "threshold": 0.5}],
                        },
                    ],
                    "edges": [
                        {
                            "from": "fetch-data",
                            "to": "process-data",
                        }
                    ],
                },
                "evaluation": {
                    "consensus": {
                        "strategy": "Majority_Vote",
                        "min_judges": 1,
                        "judge_panel": ["Luna-1"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    async def mock_call_agent(*args, **kwargs):
        return {"action": "final_answer", "summary": "Task complete"}

    args_run = parse_args(
        [
            "run",
            "--scenario",
            str(scenario_file),
            "--run-id",
            "golden-dag-run",
            "--attempts",
            "1",
            "--run-log-dir",
            str(log_dir),
        ]
    )

    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_call_agent):
        res = await handle_run(args_run)
        assert res == 0

    trace_path = log_dir / "golden-dag-run" / "run.jsonl"
    assert trace_path.exists()

    project_root = Path(__file__).parent.parent.parent
    runs_schema_path = project_root / "spec" / "runs" / "runs.schema.json"
    assert runs_schema_path.exists()

    with open(runs_schema_path, encoding="utf-8") as sf:
        schema = json.load(sf)

    graph_nodes = []
    graph_edges = []

    with open(trace_path, encoding="utf-8") as tf:
        for line in tf:
            if line.strip():
                event = json.loads(line)
                validate(instance=event, schema=schema)
                if event.get("event") == "execution_graph_node":
                    graph_nodes.append(event)
                elif event.get("event") == "execution_graph_edge":
                    graph_edges.append(event)

    # Validate node identities
    assert len(graph_nodes) >= 2
    scenario_ids = [n["scenario_node_id"] for n in graph_nodes]
    assert "fetch-data" in scenario_ids
    assert "process-data" in scenario_ids

    for node in graph_nodes:
        scen_id = node["scenario_node_id"]
        assert node["execution_instance_id"] == f"{scen_id}:attempt:1"

    # Validate edge identities
    assert len(graph_edges) >= 1
    edge = graph_edges[0]
    assert edge["from_scenario_node_id"] == "fetch-data"
    assert edge["to_scenario_node_id"] == "process-data"


@pytest.mark.asyncio
async def test_execution_graph_retry_and_failure(tmp_path, monkeypatch):
    """
    Integration Test:
    Verifies that when a task fails on attempt 1 and retries on attempt 2:
    - Attempt 1 emits ExecutionNodeStatus.FAILED with failure metadata and schema conformity
    - Attempt 2 emits ExecutionEdgeType.RETRY edge
    - Schema validation passes for all events
    """
    monkeypatch.chdir(tmp_path)

    log_dir = tmp_path / "runs"
    log_dir.mkdir()
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", log_dir)
    monkeypatch.setenv("RUN_LOG_DIR", str(log_dir))

    scenario_file = tmp_path / "retry_scenario.json"
    scenario_file.write_text(
        json.dumps(
            {
                "aes_version": 1.4,
                "metadata": {
                    "name": "DAG Retry Test",
                    "id": "dag_retry_test",
                    "compliance_level": "Standard",
                },
                "workflow": {
                    "nodes": [
                        {
                            "id": "step-a",
                            "task_description": "Initial step",
                            "success_criteria": [{"metric": "generic_accuracy", "threshold": 0.5}],
                        },
                        {
                            "id": "step-b",
                            "task_description": "Second step",
                            "success_criteria": [{"metric": "generic_accuracy", "threshold": 0.5}],
                        },
                    ],
                    "edges": [{"from": "step-a", "to": "step-b"}],
                },
                "evaluation": {
                    "consensus": {
                        "strategy": "Majority_Vote",
                        "min_judges": 1,
                        "judge_panel": ["Luna-1"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    call_count = 0

    async def mock_call_agent_with_retry(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First attempt fails
            return {"action": "error", "summary": "Temporary API timeout"}
        # Subsequent attempts succeed
        return {"action": "final_answer", "summary": "Task complete"}

    args_run = parse_args(
        [
            "run",
            "--scenario",
            str(scenario_file),
            "--run-id",
            "retry-dag-run",
            "--attempts",
            "2",
            "--run-log-dir",
            str(log_dir),
        ]
    )

    with patch(
        "eval_runner.engine.AgentAdapterRegistry.call_agent",
        side_effect=mock_call_agent_with_retry,
    ):
        res = await handle_run(args_run)
        assert res == 0

    trace_path = log_dir / "retry-dag-run" / "run.jsonl"
    assert trace_path.exists()

    project_root = Path(__file__).parent.parent.parent
    runs_schema_path = project_root / "spec" / "runs" / "runs.schema.json"

    with open(runs_schema_path, encoding="utf-8") as sf:
        schema = json.load(sf)

    graph_nodes = []
    graph_edges = []

    with open(trace_path, encoding="utf-8") as tf:
        for line in tf:
            if line.strip():
                event = json.loads(line)
                validate(instance=event, schema=schema)
                if event.get("event") == "execution_graph_node":
                    graph_nodes.append(event)
                elif event.get("event") == "execution_graph_edge":
                    graph_edges.append(event)

    # Validate that failure event was emitted with required fields
    failed_nodes = [n for n in graph_nodes if n.get("status") == "failed"]
    assert len(failed_nodes) >= 1
    assert failed_nodes[0]["scenario_node_id"] == "step-a"
    assert failed_nodes[0]["execution_instance_id"] == "step-a:attempt:1"
    assert "failure_class" in failed_nodes[0]
    assert "failure_reason" in failed_nodes[0]

    # Validate retry edge on attempt 2
    retry_edges = [e for e in graph_edges if e.get("edge_type") == "retry"]
    assert len(retry_edges) >= 1
    assert retry_edges[0]["from_scenario_node_id"] == "step-a"
    assert retry_edges[0]["to_scenario_node_id"] == "step-b"


@pytest.mark.asyncio
async def test_execution_graph_cancellation(tmp_path, monkeypatch):
    """
    Integration Test:
    Verifies that when a cancellation event is set, the session records an aborted task.
    """
    import threading

    from eval_runner.session import SessionManager

    monkeypatch.chdir(tmp_path)
    log_dir = tmp_path / "runs"
    log_dir.mkdir()

    scenario = {
        "metadata": {"id": "cancel_test"},
        "workflow": {
            "nodes": [
                {"id": "node-1", "task_description": "First task"},
                {"id": "node-2", "task_description": "Second task"},
            ],
            "edges": [{"from": "node-1", "to": "node-2"}],
        },
    }

    cancel_event = threading.Event()
    cancel_event.set()  # Cancel immediately

    session = SessionManager(
        run_id="cancel-run",
        scenario=scenario,
        log_root=log_dir,
        cancellation_event=cancel_event,
    )

    results = await session.execute_tasks(attempt_number=1)
    assert len(results) >= 1
    assert results[0]["status"] == "aborted"
