import json
from pathlib import Path

import pytest

from eval_runner.publication_suite.html_builder import HTMLBuilder


@pytest.fixture
def mock_aggregated_data(tmp_path):
    data1 = {
        "agent": "Agent-A",
        "scenarios": {
            "scen_1": {
                "pass_rate": 0.9,
                "avg_latency": 1.5,
                "avg_cost": 0.01,
                "metrics": [{"metric": "consistency_score", "score": 0.8}],
            },
            "scen_2": {"pass_rate": 0.8, "avg_latency": 2.0, "avg_cost": 0.02},
        },
    }
    data2 = {
        "agent": "Agent-B",
        "scenarios": {"scen_1": {"pass_rate": 0.7, "avg_latency": 2.5, "avg_cost": 0.03}},
    }

    path1 = tmp_path / "batch1" / "agg1.json"
    path2 = tmp_path / "batch2" / "agg2.json"
    path1.parent.mkdir(parents=True)
    path2.parent.mkdir(parents=True)

    with open(path1, "w") as f:
        json.dump(data1, f)
    with open(path2, "w") as f:
        json.dump(data2, f)

    return [str(path1), str(path2)], tmp_path


def test_html_builder_single_agent(mock_aggregated_data):
    paths, _ = mock_aggregated_data
    builder = HTMLBuilder([paths[0]])
    output_path = builder.build()

    assert output_path.exists()
    assert output_path.name == "leaderboard.html"
    content = output_path.read_text()
    assert "Agent-A" in content
    assert "PILOT PREVIEW" not in content


def test_html_builder_multi_agent(mock_aggregated_data):
    paths, _ = mock_aggregated_data
    builder = HTMLBuilder(paths)
    output_path = builder.build()

    assert output_path.exists()
    assert output_path.name == "leaderboard.html"
    # For multi-agent, it should go to the parent directory of the batches
    assert output_path.parent == Path(paths[0]).parent.parent
    content = output_path.read_text()
    assert "Agent-A" in content
    assert "Agent-B" in content


def test_html_builder_pilot_mode(mock_aggregated_data):
    paths, _ = mock_aggregated_data
    builder = HTMLBuilder([paths[0]], is_pilot=True)
    output_path = builder.build()

    assert output_path.name == "pilot_preview.html"
    content = output_path.read_text()
    assert "PILOT PREVIEW" in content


def test_html_builder_empty_scenarios(tmp_path):
    data = {"agent": "Empty", "scenarios": {}}
    path = tmp_path / "empty.json"
    with open(path, "w") as f:
        json.dump(data, f)

    builder = HTMLBuilder([str(path)])
    output_path = builder.build()
    assert output_path.exists()
