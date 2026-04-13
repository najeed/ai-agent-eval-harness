"""
coverage_plugin.py

Built-in plugin for Grounding Coverage Heatmap generation.
"""

from pathlib import Path

from .context import EvaluationContext
from .coverage_reporter import generate_coverage_report
from .plugins import BaseEvalPlugin


class CoveragePlugin(BaseEvalPlugin):
    """Generates grounding coverage reports after evaluation."""

    def after_evaluation(self, context: EvaluationContext, results: list):
        # Default report path: reports/coverage/[identifier].html
        report_path = Path("reports/coverage") / f"{context.identifier}_coverage.html"
        generate_coverage_report(context, report_path)
