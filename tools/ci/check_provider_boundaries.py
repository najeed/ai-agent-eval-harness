"""Fail CI when Core bypasses provider/runtime composition boundaries."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _python_files(directory: Path):
    yield from (p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)


def violations() -> list[str]:
    findings: list[str] = []
    runtime_services = ROOT / "eval_runner" / "runtime_services.py"
    reference_root = ROOT / "eval_runner" / "reference"
    console_forbidden = re.compile(
        r"\b(?:RUN_LOG_DIR|REPORTS_DIR|resolve_trace_path|tail_file_generator)\b"
    )
    console_run_file_bypass = re.compile(
        r"(?:getattr\([^\n]*(?:runs_dir|log_dir)|Path\([^\n]*(?:runs_dir|log_dir)|"
        r"master[-_ ]?log|status[-_ ]?vault)",
        re.IGNORECASE,
    )
    direct_reference = re.compile(r"(?:from|import)\s+eval_runner\.reference\b")
    direct_resolver = re.compile(r"\bresolve_extension\(")
    console_resolver = re.compile(r"\bresolve_run_storage_provider\b")
    for path in _python_files(ROOT / "eval_runner" / "console"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if console_forbidden.search(line):
                findings.append(f"{path.relative_to(ROOT)}:{number}: console filesystem bypass")
            if console_run_file_bypass.search(line):
                findings.append(
                    f"{path.relative_to(ROOT)}:{number}: console run-data filesystem bypass"
                )
            if console_resolver.search(line):
                findings.append(f"{path.relative_to(ROOT)}:{number}: console route resolver bypass")
    for path in _python_files(ROOT / "eval_runner"):
        if path == runtime_services or reference_root in path.parents:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if direct_reference.search(line):
                findings.append(f"{path.relative_to(ROOT)}:{number}: direct reference import")
            if direct_resolver.search(line):
                findings.append(f"{path.relative_to(ROOT)}:{number}: direct resolver call")
    return findings


if __name__ == "__main__":
    failures = violations()
    if failures:
        print("Provider-boundary audit failed:", *failures, sep="\n")
        sys.exit(1)
    print("Provider-boundary audit passed.")
