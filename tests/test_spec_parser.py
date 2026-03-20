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

    assert scenario["title"] == "Test Scenario"
    assert scenario["industry"] == "telecom"
    assert len(scenario["tasks"]) == 1
    assert scenario["tasks"][0]["title"] == "Task One"
    assert "tool1" in scenario["tasks"][0]["required_tools"]
    assert scenario["tasks"][0]["success_criteria"][0]["metric"] == "generic_accuracy"
    assert scenario["tasks"][0]["success_criteria"][0]["threshold"] == 0.9
    assert "agent1" in scenario["agent_topology"]
    assert "tool1" in scenario["policies"]


def test_parse_missing_sections():
    markdown = "# PRD: Minimal\n## Tasks\n### 1. T1\n- **Tools:** t1"
    scenario = parse_markdown_to_scenario(markdown)
    assert scenario["title"] == "Minimal"
    assert len(scenario["tasks"]) == 1
    assert "t1" in scenario["tasks"][0]["required_tools"]
