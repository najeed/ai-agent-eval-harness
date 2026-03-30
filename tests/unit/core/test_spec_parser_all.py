import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
import json
import asyncio

# SUT
import eval_runner.spec_parser as spec_parser

class TestSpecParser(unittest.TestCase):

    def test_parse_markdown_to_scenario_structured(self):
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
        scenario = spec_parser.parse_markdown_to_scenario(md)
        
        self.assertEqual(scenario["metadata"]["name"], "My Awesome App")
        self.assertEqual(scenario["industry"], "Fintech")
        self.assertEqual(scenario["use_case"], "Loan Approval")
        self.assertEqual(scenario["core_function"], "Credit Scoring")
        self.assertEqual(scenario["description"], "This is a test 앱.")
        
        # Nodes/Edges
        self.assertEqual(len(scenario["workflow"]["nodes"]), 2)
        self.assertEqual(len(scenario["workflow"]["edges"]), 1)
        self.assertEqual(scenario["workflow"]["edges"][0]["from"], "task-1")
        
        # Topology
        self.assertIn("AgentA", scenario["metadata"]["agent_topology"])
        self.assertEqual(scenario["metadata"]["agent_topology"]["AgentA"]["writes"], ["topic1"])
        self.assertEqual(scenario["metadata"]["agent_topology"]["AgentB"]["reads"], ["topic1", "topic3"])
        
        # Policies
        self.assertEqual(scenario["metadata"]["policies"]["Retries"]["count"], 3)
        self.assertEqual(scenario["metadata"]["policies"]["Broken"]["max_limit"], 100)

    def test_parse_markdown_minimal_and_empty(self):
        md = """
# Minimal
## Overview
## Tasks
## Topology
Invalid line here.
## Policies
"""
        scenario = spec_parser.parse_markdown_to_scenario(md)
        self.assertEqual(scenario["metadata"]["name"], "Minimal")
        self.assertEqual(scenario["description"], "") 
        
        # Cover line 62: sections with only whitespace header
        md_empty = "## \n"
        spec_parser.parse_markdown_to_scenario(md_empty)

    @patch("eval_runner.spec_parser.synthesize_tasks_from_prd")
    def test_parse_markdown_llm_synthesis_logic(self, mock_synth):
        mock_synth.return_value = [
            {"task_id": "T1", "description": "LLM Task 1", "expected_outcome": "OK"},
            {"title": "No ID Task"}
        ]
        
        md = "# LLM Test\n## Tasks\n(No H3 headers here)"
        scenario = spec_parser.parse_markdown_to_scenario(md)
        self.assertEqual(len(scenario["workflow"]["nodes"]), 2)
        self.assertEqual(scenario["workflow"]["nodes"][0]["id"], "T1")
        self.assertEqual(scenario["workflow"]["nodes"][1]["task_description"], "No ID Task")
        self.assertEqual(len(scenario["workflow"]["edges"]), 1)

    @patch("eval_runner.spec_parser.synthesize_tasks_from_prd", side_effect=Exception("Synthesis failure"))
    def test_parse_markdown_llm_synthesis_failure(self, mock_synth):
        md = "# Failure Test\n## Tasks\n(Empty)"
        scenario = spec_parser.parse_markdown_to_scenario(md)
        self.assertEqual(len(scenario["workflow"]["nodes"]), 1)
        self.assertEqual(scenario["workflow"]["nodes"][0]["id"], "task-1")

    @patch("eval_runner.spec_parser.GeminiProvider")
    @patch("eval_runner.config.GOOGLE_API_KEY", "mock-key")
    def test_synthesize_tasks_from_prd_success(self, mock_gemini_cls):
        mock_provider = AsyncMock()
        mock_provider.generate.return_value = '```json\n[{"task_id": "T1", "title": "T1 Title"}]\n```'
        mock_gemini_cls.return_value = mock_provider
        
        tasks = asyncio.run(spec_parser.synthesize_tasks_from_prd("md content"))
        
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["task_id"], "T1")

    @patch("eval_runner.config.GOOGLE_API_KEY", None)
    @patch.dict("os.environ", {}, clear=True)
    def test_synthesize_tasks_from_prd_no_key(self):
        tasks = asyncio.run(spec_parser.synthesize_tasks_from_prd("md content"))
        self.assertEqual(tasks, [])

    @patch("eval_runner.spec_parser.GeminiProvider")
    @patch("eval_runner.config.GOOGLE_API_KEY", "mock-key")
    def test_synthesize_tasks_from_prd_llm_warning(self, mock_gemini_cls):
        mock_provider = AsyncMock()
        mock_provider.generate.side_effect = Exception("LLM Error")
        mock_gemini_cls.return_value = mock_provider
        
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "env-key"}):
            # Fixed: Use asyncio.run for Target 5 resilience
            tasks = asyncio.run(spec_parser.synthesize_tasks_from_prd("md content"))
            self.assertEqual(tasks, [])

    def test_save_scenario_json(self):
        mock_path = MagicMock(spec=Path)
        mock_path.parent = MagicMock()
        
        m = MagicMock()
        with patch("builtins.open", MagicMock(return_value=m)):
            with patch("json.dump") as mock_dump:
                spec_parser.save_scenario_json({"test": 1}, mock_path)
                mock_dump.assert_called()
                mock_path.parent.mkdir.assert_called()

if __name__ == '__main__':
    unittest.main()
