import unittest
from pathlib import Path
from unittest.mock import MagicMock
from eval_runner.reporting_plugin import ReportingPlugin
from eval_runner.context import EvaluationContext

class TestReportingPlugin(unittest.TestCase):
    def test_generate_repro_script_with_metadata_path(self):
        plugin = ReportingPlugin()
        mock_args = MagicMock()
        mock_args.scenario = "scenarios/finance/my_test.json"
        
        ctx = EvaluationContext(
            scenario_id="my_test",
            scenario_data={},
            metadata={"args": {"scenario": "scenarios/finance/my_test.json"}}
        )
        
        plugin.generate_repro_script(ctx)
        
        repro_file = Path("reports/repro/repro_my_test.txt")
        self.assertTrue(repro_file.exists())
        
        with open(repro_file, "r") as f:
            content = f.read()
            self.assertIn("eval-harness run --scenario scenarios/finance/my_test.json", content)
        
        # Cleanup
        # repro_file.unlink()

    def test_generate_repro_script_default_path(self):
        plugin = ReportingPlugin()
        ctx = EvaluationContext(
            scenario_id="default_test",
            scenario_data={},
            metadata={}
        )
        
        plugin.generate_repro_script(ctx)
        
        repro_file = Path("reports/repro/repro_default_test.txt")
        self.assertTrue(repro_file.exists())
        
        with open(repro_file, "r") as f:
            content = f.read()
            self.assertIn("eval-harness run --scenario scenarios/default_test.json", content)

if __name__ == "__main__":
    unittest.main()
