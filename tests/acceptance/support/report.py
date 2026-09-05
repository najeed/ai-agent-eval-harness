"""
tests.acceptance.support.report
Authoritative reporter generating acceptance certification summaries and CI artifacts.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..result import AcceptanceResult


class AcceptanceReportAggregator:
    """Aggregates AcceptanceResult items and outputs certified reports."""

    def __init__(self, repo_root: Path | str | None = None):
        self.repo_root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
        self.results: list[AcceptanceResult] = []
        self.start_time = datetime.now(UTC)

    def add_result(self, result: AcceptanceResult) -> None:
        self.results.append(result)

    def summarize(self) -> dict[str, Any]:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.accepted)
        failed = sum(1 for r in self.results if not r.accepted)

        # Categorized failures
        false_negatives = 0
        false_positives = 0
        security_failures = 0
        evidence_failures = 0
        execution_errors = 0

        for r in self.results:
            if not r.accepted:
                for f in r.failures:
                    f_lower = f.lower()
                    if "false_negative" in f_lower:
                        false_negatives += 1
                    elif "false_positive" in f_lower:
                        false_positives += 1
                    elif (
                        "security" in f_lower or "unauthorized" in f_lower or "injection" in f_lower
                    ):
                        security_failures += 1
                    elif "evidence" in f_lower or "certificate" in f_lower or "sealed" in f_lower:
                        evidence_failures += 1
                    elif "execution_status" in f_lower or "error" in f_lower:
                        execution_errors += 1

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "total_cases": total,
            "passed_cases": passed,
            "failed_cases": failed,
            "false_negatives": false_negatives,
            "false_positives": false_positives,
            "security_failures": security_failures,
            "evidence_failures": evidence_failures,
            "execution_errors": execution_errors,
            "results": [r.to_dict() for r in self.results],
        }

    def generate_report_files(self, base_reports_dir: Path | str | None = None) -> Path:
        """Writes acceptance-summary.json, acceptance-summary.md, and updates 'latest' directory."""
        reports_base = (
            Path(base_reports_dir).resolve()
            if base_reports_dir
            else (self.repo_root / "reports" / "acceptance")
        )
        timestamp_str = self.start_time.strftime("%Y%m%d_%H%M%S")
        target_dir = reports_base / timestamp_str
        target_dir.mkdir(parents=True, exist_ok=True)

        summary_data = self.summarize()

        # 1. JSON report
        json_path = target_dir / "acceptance-summary.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)

        # 2. Markdown report
        md_path = target_dir / "acceptance-summary.md"
        md_lines = [
            "# AgentV Acceptance Certification Report",
            f"**Timestamp**: `{summary_data['timestamp']}`  ",
            f"**Total Cases**: {summary_data['total_cases']} | "
            f"**Passed**: {summary_data['passed_cases']} | "
            f"**Failed**: {summary_data['failed_cases']}",
            "",
            "## Zero-Tolerance Thresholds",
            f"- False Negatives: `{summary_data['false_negatives']}`",
            f"- False Positives: `{summary_data['false_positives']}`",
            f"- Security Failures: `{summary_data['security_failures']}`",
            f"- Evidence Failures: `{summary_data['evidence_failures']}`",
            "",
            "## Case Outcomes",
            "| Case ID | Status | Run ID | Evidence Verified | Failures |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for r in self.results:
            status_emoji = "✅ PASS" if r.accepted else "❌ FAIL"
            fail_str = "; ".join(r.failures) if r.failures else "None"
            ev_str = str(r.evidence_verified)
            md_lines.append(
                f"| `{r.case_id}` | {status_emoji} | `{r.run_id}` | {ev_str} | {fail_str} |"
            )

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines) + "\n")

        # 3. Update 'latest' directory
        latest_dir = reports_base / "latest"
        if latest_dir.exists():
            shutil.rmtree(latest_dir, ignore_errors=True)
        shutil.copytree(target_dir, latest_dir)

        return target_dir


__all__ = ["AcceptanceReportAggregator"]
