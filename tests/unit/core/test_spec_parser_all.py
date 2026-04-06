import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# SUT
import eval_runner.spec_parser as spec_parser


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
    mock_provider.generate.return_value = (
        '```json\n[{"task_id": "T1", "title": "T1 Title"}]\n```'
    )
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


def test_save_scenario_json():
    mock_path = MagicMock(spec=Path)
    mock_path.parent = MagicMock()

    m = MagicMock()
    with patch("builtins.open", MagicMock(return_value=m)):
        with patch("json.dump") as mock_dump:
            spec_parser.save_scenario_json({"test": 1}, mock_path)
            mock_dump.assert_called()
            mock_path.parent.mkdir.assert_called()

