import json
from unittest.mock import AsyncMock, patch

import pytest

from eval_runner.spec_parser import (
    parse_markdown_to_scenario,
    save_scenario_json,
    synthesize_tasks_from_prd,
)


@pytest.mark.asyncio
async def test_parse_markdown_basic():
    """Test basic metadata extraction (Title, Industry, Use Case)."""
    md = """# PRD: Loan Approval System
**Industry:** Fintech
**Use Case:** Credit Scoring
**Core Function:** Risk Assessment
## Overview
A system for assessing loan risk.
"""
    scenario = await parse_markdown_to_scenario(md)

    assert scenario["metadata"]["name"] == "Loan Approval System"
    assert scenario["industry"] == "Fintech"
    assert scenario["use_case"] == "Credit Scoring"
    assert scenario["core_function"] == "Risk Assessment"
    assert "A system for assessing loan risk." in scenario["description"]


@pytest.mark.asyncio
async def test_parse_markdown_h3_tasks():
    """Test task extraction via H3 headers with expected outcomes."""
    md = """# Test
## Tasks
### 1. Identify Identity
Determine if the user is real. (Expect: User is verified)
### 2. Check Assets
Verify bank balance. (Goal: Balance > 1000)
"""
    scenario = await parse_markdown_to_scenario(md)

    nodes = scenario["workflow"]["nodes"]
    assert len(nodes) == 2
    assert nodes[0]["title"] == "Identify Identity"
    assert "Determine if the user is real" in nodes[0]["task_description"]
    assert nodes[0]["expected_outcome"][0]["expected"] == "User is verified"

    assert nodes[1]["title"] == "Check Assets"
    assert nodes[1]["expected_outcome"][0]["expected"] == "Balance > 1000"

    # Check edges
    assert len(scenario["workflow"]["edges"]) == 1
    assert scenario["workflow"]["edges"][0]["from"] == "task-1"
    assert scenario["workflow"]["edges"][0]["to"] == "task-2"


@pytest.mark.asyncio
async def test_parse_markdown_bullet_tasks():
    """Test task extraction via bullet points."""
    md = """# Test
## Test Cases
- Task A (Expect: Done)
- Task B
"""
    scenario = await parse_markdown_to_scenario(md)

    nodes = scenario["workflow"]["nodes"]
    assert len(nodes) == 2
    assert "Task A" in nodes[0]["task_description"]
    assert nodes[0]["expected_outcome"][0]["expected"] == "Done"
    assert "Task B" in nodes[1]["task_description"]


@pytest.mark.asyncio
async def test_parse_markdown_topology():
    """Test topology parsing for agents."""
    md = """# Test
## Topology
**Manager:** reads from `User`, writes to `Analyst`, `Officer`.
**Analyst:** reads from `Manager`, writes to `Officer`.
"""
    scenario = await parse_markdown_to_scenario(md)

    topo = scenario["metadata"]["agent_topology"]
    assert "Manager" in topo
    assert "User" in topo["Manager"]["reads"]
    assert "Analyst" in topo["Manager"]["writes"]
    assert "Officer" in topo["Manager"]["writes"]

    assert "Analyst" in topo
    assert "Manager" in topo["Analyst"]["reads"]
    assert "Officer" in topo["Analyst"]["writes"]


@pytest.mark.asyncio
async def test_parse_markdown_policies():
    """Test policy parsing in policies section."""
    md = """# Test
## Policies
- **MaxRetries:** {"limit": 3, 'strategy': 'exponential'}
- **Timeout:** 30
"""
    scenario = await parse_markdown_to_scenario(md)

    policies = scenario["metadata"]["policies"]
    assert policies["MaxRetries"]["limit"] == 3
    assert policies["MaxRetries"]["strategy"] == "exponential"
    # Fallback default for non-JSON lines (30 is not valid JSON for a dict)
    assert policies["Timeout"] == 30


@pytest.mark.asyncio
async def test_synthesize_tasks_llm_success(monkeypatch):
    """Test LLM synthesis path with mock provider."""
    import eval_runner.config as config

    monkeypatch.setattr(config, "GOOGLE_API_KEY", "dummy-key")

    mock_tasks = [
        {
            "task_id": "llm-1",
            "title": "LLM Task",
            "description": "Derived",
            "expected_outcome": "Pass",
        }
    ]

    with patch("eval_runner.spec_parser.GeminiProvider") as mock_provider_cls:
        mock_provider = AsyncMock()
        mock_provider.generate.return_value = "```json\n" + json.dumps(mock_tasks) + "\n```"
        mock_provider_cls.return_value = mock_provider

        tasks = await synthesize_tasks_from_prd("dummy md")
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == "llm-1"


@pytest.mark.asyncio
async def test_parse_markdown_llm_fallback_full():
    """Test full fallback path in parse_markdown_to_scenario when no structure found."""
    md = """# Empty PRD
## Tasks
No concrete tasks here!
"""
    mock_synthesized = [
        {"title": "Synthesized", "description": "From LLM", "expected_outcome": "OK"}
    ]

    # Corrected patch logic
    with patch(
        "eval_runner.spec_parser.synthesize_tasks_from_prd", new_callable=AsyncMock
    ) as mock_synth:
        mock_synth.return_value = mock_synthesized
        scenario = await parse_markdown_to_scenario(md)
        assert len(scenario["workflow"]["nodes"]) == 1
        assert scenario["workflow"]["nodes"][0]["title"] == "Synthesized"


@pytest.mark.asyncio
async def test_synthesize_tasks_llm_error_recovery():
    """Test fallback to empty node when LLM fails and no tasks found."""
    md = """# Fail PRD
## Tasks
No tasks.
"""
    with patch(
        "eval_runner.spec_parser.synthesize_tasks_from_prd", side_effect=Exception("LLM DEAD")
    ):
        scenario = await parse_markdown_to_scenario(md)
        assert len(scenario["workflow"]["nodes"]) == 1
        assert "Generated as fallback" in scenario["workflow"]["nodes"][0]["task_description"]


def test_save_scenario_json(tmp_path):
    """Test scenario saving utility."""
    path = tmp_path / "scenario.json"
    data = {"test": True}
    save_scenario_json(data, path)

    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["test"] is True
