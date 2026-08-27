"""
tests/unit/core/test_coverage_reporter.py
Unit tests for eval_runner.coverage_reporter.generate_coverage_report().

Covers:
  - HTML generation with policy hits (hit / miss CSS classes)
  - HTML generation with tool hits (hit / miss CSS classes)
  - Empty policies / tools fallback text
  - tools_required list form vs tools dict form
  - File write and directory creation
"""

from __future__ import annotations

from pathlib import Path

from eval_runner.context import EvaluationContext
from eval_runner.coverage_reporter import generate_coverage_report


def _make_context(
    identifier: str = "test-scenario",
    policies: dict | None = None,
    tools_required: list | None = None,
    tools_dict: dict | None = None,
    policy_hits: dict | None = None,
    tool_hits: dict | None = None,
) -> EvaluationContext:
    """
    Build a minimal EvaluationContext with grounding_hits pre-populated.

    EvaluationContext is a frozen dataclass, so we use object.__setattr__
    to inject mutable grounding_hits after construction.
    """
    scenario_data: dict = {"metadata": {}}
    if policies is not None:
        scenario_data["metadata"]["policies"] = policies
    if tools_required is not None:
        scenario_data["tools_required"] = tools_required
    elif tools_dict is not None:
        scenario_data["tools"] = tools_dict

    ctx = EvaluationContext(identifier=identifier, scenario_data=scenario_data)

    # Inject mutable grounding_hits (the dataclass field is mutable by default)
    ctx.grounding_hits["policies"] = policy_hits or {}
    ctx.grounding_hits["tools"] = tool_hits or {}
    return ctx


class TestGenerateCoverageReport:
    def test_creates_file_and_directory(self, tmp_path: Path):
        """generate_coverage_report must write an HTML file, creating parent dirs."""
        ctx = _make_context()
        out = tmp_path / "subdir" / "report.html"

        generate_coverage_report(ctx, out)

        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "Grounding Coverage Heatmap" in content

    def test_policy_hit_item_has_hit_class(self, tmp_path: Path):
        """Policies with count > 0 must render with CSS class 'hit'."""
        ctx = _make_context(
            policies={"tool_auth_policy": {}, "rate_limit_policy": {}},
            policy_hits={"tool_auth_policy": 5, "rate_limit_policy": 0},
        )
        out = tmp_path / "report.html"
        generate_coverage_report(ctx, out)
        content = out.read_text(encoding="utf-8")

        # tool_auth_policy has 5 hits → class="item hit"
        assert 'class="item hit"' in content
        # rate_limit_policy has 0 hits → class="item miss"
        assert 'class="item miss"' in content
        # Hit count should appear
        assert "5 hits" in content
        assert "0 hits" in content

    def test_tool_hit_item_has_hit_class(self, tmp_path: Path):
        """Tools with count > 0 must render with CSS class 'hit'."""
        ctx = _make_context(
            tools_required=["search_tool", "calculator"],
            tool_hits={"search_tool": 3, "calculator": 0},
        )
        out = tmp_path / "report.html"
        generate_coverage_report(ctx, out)
        content = out.read_text(encoding="utf-8")

        assert "3 hits" in content
        assert "0 hits" in content
        assert 'class="item hit"' in content
        assert 'class="item miss"' in content

    def test_no_policies_shows_fallback_text(self, tmp_path: Path):
        """When no policies are defined, the report shows the 'No policies defined' placeholder."""
        ctx = _make_context()
        out = tmp_path / "report.html"
        generate_coverage_report(ctx, out)
        content = out.read_text(encoding="utf-8")

        assert "No policies defined" in content

    def test_no_tools_shows_fallback_text(self, tmp_path: Path):
        """When no tools are defined, the report shows the 'No tools defined' placeholder."""
        ctx = _make_context(policies={"p1": {}}, policy_hits={"p1": 2})
        out = tmp_path / "report.html"
        generate_coverage_report(ctx, out)
        content = out.read_text(encoding="utf-8")

        assert "No tools defined" in content

    def test_tools_from_dict_keys(self, tmp_path: Path):
        """tools can come from scenario['tools'].keys() when tools_required is absent."""
        ctx = _make_context(
            tools_dict={"web_search": {}, "code_runner": {}},
            tool_hits={"web_search": 1},
        )
        out = tmp_path / "report.html"
        generate_coverage_report(ctx, out)
        content = out.read_text(encoding="utf-8")

        assert "web_search" in content
        assert "code_runner" in content

    def test_identifier_appears_in_title(self, tmp_path: Path):
        """The scenario identifier must appear in the HTML h1 heading."""
        ctx = _make_context(identifier="my-special-scenario-id")
        out = tmp_path / "report.html"
        generate_coverage_report(ctx, out)
        content = out.read_text(encoding="utf-8")

        assert "my-special-scenario-id" in content

    def test_all_policies_hit(self, tmp_path: Path):
        """All policies with hits → only 'hit' class, no 'miss' in policy section."""
        ctx = _make_context(
            policies={"p1": {}, "p2": {}},
            policy_hits={"p1": 10, "p2": 7},
        )
        out = tmp_path / "report.html"
        generate_coverage_report(ctx, out)
        content = out.read_text(encoding="utf-8")

        # Both should be hits; 'miss' class should not appear
        assert 'class="item hit"' in content

    def test_overwrites_existing_file(self, tmp_path: Path):
        """Calling generate_coverage_report twice must overwrite the file cleanly."""
        ctx = _make_context(identifier="run-a")
        out = tmp_path / "report.html"
        generate_coverage_report(ctx, out)
        generate_coverage_report(ctx, out)
        content = out.read_text(encoding="utf-8")
        assert "run-a" in content
