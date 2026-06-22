from unittest.mock import AsyncMock, patch

import pytest

# SUT
import eval_runner.spec_parser as spec_parser
from eval_runner.spec_parser import (
    parse_markdown_to_scenario,
    save_scenario_json,
)


@pytest.mark.asyncio
async def test_parse_markdown_to_scenario_structured():
    md = """
# PRD: My Awesome App
**Industry:** Fintech
**Use Case:** Loan Approval
**Core Function:** Credit Scoring

## Overview
This is a test 앱.

## Tasks
### 1. Verification
Verify the user's ID.
### 2. Scoring
Calculate the score.

## Topology
**AgentA:** writes to [topic1], reads from topic2
**AgentB:** reads from [topic1, topic3]

## Policies
- **Retries:** {"count": 3}
- **Broken:** {not-json}
"""
    scenario = await spec_parser.parse_markdown_to_scenario(md)

    assert scenario["metadata"]["name"] == "My Awesome App"
    assert scenario["industry"] == "Fintech"
    assert scenario["use_case"] == "Loan Approval"
    assert scenario["core_function"] == "Credit Scoring"
    assert scenario["description"] == "This is a test 앱."

    # Nodes/Edges
    assert len(scenario["workflow"]["nodes"]) == 2
    assert len(scenario["workflow"]["edges"]) == 1
    assert scenario["workflow"]["edges"][0]["from"] == "task-1"

    # Topology
    assert "AgentA" in scenario["metadata"]["agent_topology"]
    assert scenario["metadata"]["agent_topology"]["AgentA"]["writes"] == ["topic1"]
    assert scenario["metadata"]["agent_topology"]["AgentB"]["reads"] == ["topic1", "topic3"]

    # Policies
    assert scenario["metadata"]["policies"]["Retries"]["count"] == 3
    assert scenario["metadata"]["policies"]["Broken"]["max_limit"] == 100


@pytest.mark.asyncio
async def test_parse_markdown_minimal_and_empty():
    md = """
# Minimal
## Overview
## Tasks
## Topology
Invalid line here.
## Policies
"""
    scenario = await spec_parser.parse_markdown_to_scenario(md)
    assert scenario["metadata"]["name"] == "Minimal"
    assert scenario["description"] == ""

    # Cover line 62: sections with only whitespace header
    md_empty = "## \n"
    await spec_parser.parse_markdown_to_scenario(md_empty)


@pytest.mark.asyncio
@patch("eval_runner.spec_parser.synthesize_tasks_from_prd")
async def test_parse_markdown_llm_synthesis_logic(mock_synth):
    mock_synth.return_value = [
        {"task_id": "T1", "description": "LLM Task 1", "expected_outcome": "OK"},
        {"title": "No ID Task"},
    ]

    md = "# LLM Test\n## Tasks\n(No H3 headers here)"
    scenario = await spec_parser.parse_markdown_to_scenario(md)
    assert len(scenario["workflow"]["nodes"]) == 2
    assert scenario["workflow"]["nodes"][0]["id"] == "T1"
    assert scenario["workflow"]["nodes"][1]["task_description"] == "No ID Task"
    assert len(scenario["workflow"]["edges"]) == 1


@pytest.mark.asyncio
@patch(
    "eval_runner.spec_parser.synthesize_tasks_from_prd",
    side_effect=Exception("Synthesis failure"),
)
async def test_parse_markdown_llm_synthesis_failure(mock_synth):
    md = "# Failure Test\n## Tasks\n(Empty)"
    scenario = await spec_parser.parse_markdown_to_scenario(md)
    assert len(scenario["workflow"]["nodes"]) == 1
    assert scenario["workflow"]["nodes"][0]["id"] == "task-1"


@pytest.mark.asyncio
@patch("eval_runner.spec_parser.GeminiProvider")
@patch("eval_runner.config.GOOGLE_API_KEY", "mock-key")
async def test_synthesize_tasks_from_prd_success(mock_gemini_cls):
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = '```json\n[{"task_id": "T1", "title": "T1 Title"}]\n```'
    mock_gemini_cls.return_value = mock_provider

    tasks = await spec_parser.synthesize_tasks_from_prd("md content")

    assert len(tasks) == 1
    assert tasks[0]["task_id"] == "T1"


@pytest.mark.asyncio
@patch("eval_runner.config.GOOGLE_API_KEY", None)
@patch.dict("os.environ", {}, clear=True)
async def test_synthesize_tasks_from_prd_no_key():
    tasks = await spec_parser.synthesize_tasks_from_prd("md content")
    assert tasks == []


@pytest.mark.asyncio
@patch("eval_runner.spec_parser.GeminiProvider")
@patch("eval_runner.config.GOOGLE_API_KEY", "mock-key")
async def test_synthesize_tasks_from_prd_llm_warning(mock_gemini_cls):
    mock_provider = AsyncMock()
    mock_provider.generate.side_effect = Exception("LLM Error")
    mock_gemini_cls.return_value = mock_provider

    with patch.dict("os.environ", {"GOOGLE_API_KEY": "env-key"}):
        tasks = await spec_parser.synthesize_tasks_from_prd("md content")
        assert tasks == []


@pytest.mark.asyncio
async def test_parse_markdown_basic_extra():
    md = """# PRD: Loan Approval System
**Industry:** Fintech
**Use Case:** Credit Scoring
**Core Function:** Risk Assessment
## Overview
A system for assessing loan risk.
"""
    scenario = await parse_markdown_to_scenario(md)
    assert scenario["metadata"]["name"] == "Loan Approval System"


@pytest.mark.asyncio
async def test_parse_markdown_h3_tasks_extra():
    md = """# Test
## Tasks
### 1. Identify Identity
Determine if the user is real. (Expect: User is verified)
"""
    scenario = await parse_markdown_to_scenario(md)
    assert len(scenario["workflow"]["nodes"]) == 1


@pytest.mark.asyncio
async def test_parse_markdown_bullet_tasks_extra():
    md = """# Test
## Test Cases
- Task A (Expect: Done)
- Task B
"""
    scenario = await parse_markdown_to_scenario(md)
    assert len(scenario["workflow"]["nodes"]) == 2


@pytest.mark.asyncio
async def test_parse_markdown_topology_extra():
    md = """# Test
## Topology
**Manager:** reads from `User`, writes to `Analyst`.
"""
    scenario = await parse_markdown_to_scenario(md)
    assert "Manager" in scenario["metadata"]["agent_topology"]


@pytest.mark.asyncio
async def test_parse_markdown_policies_extra():
    md = """# Test
## Policies
- **MaxRetries:** {"limit": 3}
- **Timeout:** 30
"""
    scenario = await parse_markdown_to_scenario(md)
    assert scenario["metadata"]["policies"]["MaxRetries"]["limit"] == 3


def test_save_scenario_json_native(tmp_path):
    path = tmp_path / "scenario.json"
    save_scenario_json({"test": True}, path)
    assert path.exists()


@pytest.mark.asyncio
async def test_parse_markdown_schema_compliance():
    from pathlib import Path

    md = """
# PRD: Schema Compliance App
**Industry:** Fintech
**Use Case:** Compliance Check
**Core Function:** Auto Validation

## Overview
Validates that generated JSON conforms to the actual JSON schema.

## Tasks
### 1. Verification
Verify the user's details.

## Topology
**Validator:** writes to [logs]

## Policies
- **Retries:** {"count": 3}
"""
    scenario = await spec_parser.parse_markdown_to_scenario(md)

    # Run JSON schema validation
    import json

    from jsonschema import validate
    from referencing import Registry, Resource

    project_root = Path(__file__).parent.parent.parent.parent
    schema_path = project_root / "spec" / "aes" / "aes.schema.json"

    assert schema_path.exists(), f"Schema file not found at {schema_path}"

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    defs_dir = schema_path.parent / "definitions"
    registry = Registry()
    if defs_dir.exists():
        for fpath in defs_dir.glob("*.json"):
            with open(fpath) as f_def:
                registry = registry.with_resource(
                    uri=f"definitions/{fpath.name}",
                    resource=Resource.from_contents(json.load(f_def)),
                )

    # Validate the generated scenario dictionary. It should not raise ValidationError
    validate(instance=scenario, schema=schema, registry=registry)
