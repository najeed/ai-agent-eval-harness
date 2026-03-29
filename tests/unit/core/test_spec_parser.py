import pytest
from eval_runner.spec_parser import parse_markdown_to_scenario


def test_parse_valid_markdown():
    markdown = """# PRD: Test Scenario
**Industry:** telecom
**Use Case:** support
**Core Function:** billing

## Scenario Overview
A test overview.

## Tasks
### 1. Task One
Description of task one.
- **Expected Outcome:** Success
- **Tools:** tool1, tool2
- **Criteria:** generic_accuracy (0.9)

## Agent Topology
- **agent1:** writes to ns1, reads from ns2

## Policies
- **tool1:** {"max_limit": 10}
"""
    scenario = parse_markdown_to_scenario(markdown)

    assert scenario["metadata"]["name"] == "Test Scenario"
    assert scenario["industry"] == "telecom"
    assert "workflow" in scenario
    assert len(scenario["workflow"]["nodes"]) == 1
    assert len(scenario["workflow"]["nodes"]) == 1
    assert "agent1" in scenario["metadata"]["agent_topology"]
    assert "tool1" in scenario["metadata"]["policies"]


def test_parse_missing_sections():
    markdown = "# PRD: Minimal\n## Tasks\n### 1. T1\n- **Tools:** t1"
    scenario = parse_markdown_to_scenario(markdown)
    assert scenario["metadata"]["name"] == "Minimal"
    assert "workflow" in scenario
    assert len(scenario["workflow"]["nodes"]) == 1
    assert len(scenario["workflow"]["nodes"]) == 1
    # No legacy tasks block
