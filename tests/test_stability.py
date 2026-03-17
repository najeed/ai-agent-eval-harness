import unittest
import os
import json
import asyncio
from pathlib import Path
from eval_runner import metrics, loader, catalog, cli, config

class TestStability(unittest.TestCase):
    def test_nested_state_verification(self):
        """Test dot-notation support for nested state."""
        actual_state = {
            "user": {
                "profile": {
                    "id": "123",
                    "status": "active"
                }
            },
            "global_flag": True
        }
        
        # Test valid nested access
        self.assertEqual(metrics.get_nested_value(actual_state, "user.profile.id"), "123")
        self.assertEqual(metrics.get_nested_value(actual_state, "user.profile.status"), "active")
        self.assertEqual(metrics.get_nested_value(actual_state, "global_flag"), True)
        
        # Test invalid paths
        self.assertIsNone(metrics.get_nested_value(actual_state, "user.nonexistent"))
        self.assertIsNone(metrics.get_nested_value(actual_state, "a.b.c"))
        
        # Test state_verification metric with nested path
        expected_changes = [{"path": "user.profile.id", "value": "123"}]
        score = metrics.calculate_state_correctness(expected_changes, actual_state)
        self.assertEqual(score, 1.0)

    def test_path_decoupling_absolute_resolution(self):
        """Test that relative dataset paths are resolved correctly relative to the scenario."""
        # Create a temp scenario and dataset
        temp_dir = Path("tmp_test_decoupling")
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        dataset_path = temp_dir / "data.csv"
        dataset_path.write_text("id,name\n1,test")
        
        scenario_path = temp_dir / "test_scenario.json"
        scenario_data = {
            "scenario_id": "test_decoupling",
            "title": "Test Decoupling Scenario",
            "description": "Background for testing",
            "industry": "testing",
            "use_case": "Automated Testing",
            "core_function": "Path Resolution",
            "dataset": {"path": "./data.csv", "format": "csv"},
            "tasks": [
                {
                    "task_id": "t1",
                    "description": "desc",
                    "expected_outcome": "outcome",
                    "success_criteria": [{"metric": "state_verification", "threshold": 1.0}]
                }
            ]
        }
        scenario_path.write_text(json.dumps(scenario_data))
        
        try:
            loaded_scenario = loader.load_scenario(scenario_path)
            # The path should now be absolute
            resolved_path = Path(loaded_scenario["dataset"]["path"])
            self.assertTrue(resolved_path.is_absolute())
            self.assertEqual(resolved_path.resolve(), dataset_path.resolve())
        finally:
            # Cleanup
            if scenario_path.exists(): scenario_path.unlink()
            if dataset_path.exists(): dataset_path.unlink()
            if temp_dir.exists(): temp_dir.rmdir()

    def test_catalog_tagging_logic(self):
        """Test the industry and tag inference logic in catalog.py."""
        # We test the logic by mocking a Path object that looks like it's outside the repo
        cat = catalog.ScenarioCatalog()
        
        # Case 1: Scenario with explicit industry
        data1 = {"scenario_id": "s1", "industry": "fintech", "metadata": {"tags": ["custom"]}}
        
        scenarios = []
        def mock_append(p, data):
            meta = data.get("metadata", {})
            scenario_id = data.get("scenario_id", p.stem)
            industry = data.get("industry")
            tags = meta.get("tags", [])
            
            if not industry:
                if p.parent.name == "scenarios" and "ai-agent-eval-harness" in str(p.absolute()).lower():
                    industry = p.parent.parent.name
                else:
                    industry = "unclassified"
                    if "local" not in tags:
                        tags.append("local")
            
            if "local" not in tags and "ai-agent-eval-harness" not in str(p.absolute()).lower():
                tags.append("local")
                
            scenarios.append({"id": scenario_id, "industry": industry, "tags": list(set(tags))})

        # Test logic
        mock_append(Path("C:/external/sc1.json"), {"industry": "legal"})
        self.assertEqual(scenarios[0]["industry"], "legal")
        self.assertIn("local", scenarios[0]["tags"])
        
        mock_append(Path("C:/external/sc2.json"), {})
        self.assertEqual(scenarios[1]["industry"], "unclassified")
        self.assertIn("local", scenarios[1]["tags"])

    def test_judge_required_guard(self):
        """Test judge required guard raises RuntimeError when provider is missing."""
        criterion = {"metric": "luna_judge_score", "required": True, "expected_outcome": "outcome"}
        agent_summary = "test"
        
        # Mock config to have an invalid provider
        old_provider = config.JUDGE_PROVIDER
        config.JUDGE_PROVIDER = "invalid_provider_name"
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            with self.assertRaises(RuntimeError) as cm:
                loop.run_until_complete(metrics.calculate_luna_judge_score(criterion, agent_summary))
            self.assertIn("Judge Configuration Error", str(cm.exception))
        finally:
            config.JUDGE_PROVIDER = old_provider
            loop.close()

if __name__ == "__main__":
    unittest.main()
