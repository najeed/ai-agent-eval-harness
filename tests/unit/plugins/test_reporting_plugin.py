import unittest
from pathlib import Path
from unittest.mock import MagicMock

from eval_runner.context import EvaluationContext
from eval_runner.reporting_plugin import ReportingPlugin


class TestReportingPlugin(unittest.TestCase):
    def test_generate_repro_script_with_metadata_path(self):
        plugin = ReportingPlugin()
        mock_args = MagicMock()
        mock_args.scenario = "scenarios/finance/my_test.json"

        ctx = EvaluationContext(
            identifier="my_test",
            scenario_data={},
            metadata={"args": {"scenario": "scenarios/finance/my_test.json"}},
        )

        plugin.generate_repro_script(ctx)

        repro_file = Path("reports/repro/repro_my_test.txt")
        self.assertTrue(repro_file.exists())

        with open(repro_file) as f:
            content = f.read()
            self.assertIn("agentv run --scenario scenarios/finance/my_test.json", content)

        # Cleanup
        # repro_file.unlink()

    def test_generate_repro_script_default_path(self):
        plugin = ReportingPlugin()
        ctx = EvaluationContext(identifier="default_test", scenario_data={}, metadata={})

        plugin.generate_repro_script(ctx)

        repro_file = Path("reports/repro/repro_default_test.txt")
        self.assertTrue(repro_file.exists())

        with open(repro_file) as f:
            content = f.read()
            self.assertIn("agentv run --scenario scenarios/default_test.json", content)

    def test_on_batch_complete_emits_metric_evaluated(self):
        from unittest.mock import patch

        plugin = ReportingPlugin()
        ctx = EvaluationContext(
            identifier="test_run", scenario_data={}, metadata={}, run_id="run_123"
        )

        attempt_1 = [
            {"conversation_history": [{"role": "agent", "content": "Done."}], "metrics": []}
        ]
        attempt_2 = [
            {"conversation_history": [{"role": "agent", "content": "Done."}], "metrics": []}
        ]
        all_attempts = [attempt_1, attempt_2]

        emitted = []

        def _record_emit(name, payload, **kwargs):
            emitted.append((name, payload))

        with patch("eval_runner.events.emit", side_effect=_record_emit):
            plugin.on_metrics_calculated(ctx, all_attempts)

        self.assertEqual(len(all_attempts[-1][0]["metrics"]), 1)
        self.assertEqual(all_attempts[-1][0]["metrics"][0]["metric"], "consistency_score")
        self.assertEqual(all_attempts[-1][0]["metrics"][0]["outcome"], "PASS")

        # Verify normative runtime trace stream is not contaminated with synthetic reporting events
        self.assertEqual(len(emitted), 0)


if __name__ == "__main__":
    unittest.main()
